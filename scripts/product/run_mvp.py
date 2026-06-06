"""Run the local recommendation MVP as a single-command CLI workflow."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.contracts.config import PipelineConfig
from src.engine import CandidateItem, PersonalRecSys
from src.utils.data_loader import load_items, prepare_collection_candidates
from src.utils.embeddings import get_embedder


DEFAULT_TOP_K = 20
DEFAULT_OUTPUT_DIR = "data/experiments/mvp_runs/latest"
DEFAULT_CACHE_DIR = "data/cache/mvp"


class MVPError(RuntimeError):
    """User-facing CLI error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--collection-format", required=True, choices=["zhihu", "generic"])
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--candidates-format", required=True, choices=["zhihu", "generic"])
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    return parser.parse_args()


def _log(message: str) -> None:
    print(f"[MVP] {message}")


def _build_engine(cache_dir: str) -> PersonalRecSys:
    config = PipelineConfig(
        cache_dir=cache_dir,
        enable_reranker=False,
        preset="balanced",
        top_k=DEFAULT_TOP_K,
    )
    embedder = get_embedder("mock", dim=config.embedding_dim)
    return PersonalRecSys(
        embedder=embedder,
        embedding_dim=config.embedding_dim,
        cache_dir=cache_dir,
        config=config,
    )


def _build_candidate_items(items):
    candidates = []
    for item in items:
        metadata = dict(item.get("metadata", {}))
        metadata.setdefault("source", item.get("source", "unknown"))
        metadata["popularity"] = float(metadata.get("popularity", 0.0) or 0.0)
        candidates.append(
            CandidateItem(
                item_id=item["id"],
                title=item["title"],
                content=item["content"],
                tags=list(item.get("tags", [])),
                metadata=metadata,
            )
        )
    return candidates


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_ready_inputs(collection_items, candidate_items) -> None:
    if not collection_items:
        raise MVPError("Collection input is empty after validation and deduplication.")
    if not candidate_items:
        raise MVPError("Candidate input is empty after validation and deduplication.")


def _print_recommendations(recsys: PersonalRecSys, results, top_k: int) -> None:
    print("\n=== Recommendations ===")
    for item in results.ranked_items[:top_k]:
        candidate = recsys.candidates.get(item.item_id)
        if candidate is None:
            continue
        url = candidate.metadata.get("url", "")
        print(f"[{item.rank:02d}] {candidate.title}")
        print(f"  score={item.final_score:.4f} components={json.dumps(item.component_scores, ensure_ascii=False)}")
        if url:
            print(f"  url={url}")


def run_workflow(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    cache_dir = Path(args.cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    _log("loading inputs")
    collection_raw = load_items(args.collection, args.collection_format)
    candidates_raw = load_items(args.candidates, args.candidates_format)
    collection_items, candidate_items, input_summary = prepare_collection_candidates(collection_raw, candidates_raw)
    _validate_ready_inputs(collection_items, candidate_items)
    if input_summary["candidate_final_count"] == 0:
        raise MVPError("No candidate items remain after removing overlaps with the collection.")

    _log("building profile")
    recsys = _build_engine(str(cache_dir))
    profile_started = time.time()
    profile_summary = recsys.build_profile_from_collection(collection_items, llm_client=None, max_items=50)
    profile_elapsed = time.time() - profile_started

    _log("embedding candidates")
    recsys.add_candidates(_build_candidate_items(candidate_items))
    if not recsys.candidates:
        raise MVPError("No candidates were added to the engine.")
    embed_started = time.time()
    recsys.embed_candidates(batch_size=recsys._config.batch_size)
    embed_elapsed = time.time() - embed_started

    _log("recommending")
    recommend_started = time.time()
    results = recsys.recommend(top_k=args.top_k, preset="balanced")
    recommend_elapsed = time.time() - recommend_started

    _print_recommendations(recsys, results, top_k=args.top_k)

    _log("writing artifacts")
    run_config = {
        "collection": args.collection,
        "collection_format": args.collection_format,
        "candidates": args.candidates,
        "candidates_format": args.candidates_format,
        "top_k": args.top_k,
        "preset": "balanced",
        "output_dir": str(output_dir),
        "cache_dir": str(cache_dir),
        "enable_reranker": False,
        "enable_llm": False,
    }
    recommendation_payload = {
        "profile_summary": profile_summary,
        "recommendations": [
            {
                "rank": item.rank,
                "item_id": item.item_id,
                "title": recsys.candidates[item.item_id].title if item.item_id in recsys.candidates else "",
                "final_score": round(float(item.final_score), 6),
                "component_scores": {
                    name: round(float(score), 6) for name, score in item.component_scores.items()
                },
                "url": recsys.candidates[item.item_id].metadata.get("url", "") if item.item_id in recsys.candidates else "",
                "metadata": recsys.candidates[item.item_id].metadata if item.item_id in recsys.candidates else {},
            }
            for item in results.ranked_items[: args.top_k]
        ],
    }
    engine_meta = {
        "cache_dir": str(cache_dir),
        "total_candidates": results.total_candidates,
        "filter_count": results.filter_count,
        "timing": results.timing,
        "stage_elapsed_seconds": {
            "build_profile": round(profile_elapsed, 6),
            "embed_candidates": round(embed_elapsed, 6),
            "recommend": round(recommend_elapsed, 6),
        },
    }

    _write_json(output_dir / "run_config.json", run_config)
    _write_json(output_dir / "input_summary.json", input_summary)
    _write_json(output_dir / "recommendations.json", recommendation_payload)
    _write_json(output_dir / "engine_meta.json", engine_meta)
    return 0


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(run_workflow(args))
    except (FileNotFoundError, ValueError, MVPError) as exc:
        print(f"[MVP] error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
