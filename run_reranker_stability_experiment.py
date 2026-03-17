"""
Monte Carlo reranker stability experiment on fixed coarse top-N candidates.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from run_real_data import (
    AUTHOR_PATH,
    CACHE_DIR,
    FAVORITES_PATH,
    build_candidate_items,
    build_engine,
    ensure_profile,
)
from src.contracts.types import ProfileContext
from src.evaluation.reranker_stability import RerankerStabilityExperiment
from src.services.ranker_adapter import DefaultRanker
from src.services.reranker import LLMReranker
from src.utils.data_loader import load_zhihu_items, split_collection_candidates
from src.utils.lm_studio_client import LMStudioLLMClient


TRIALS = int(os.getenv("TRIALS", "10"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "10"))
ANALYSIS_TOP_K = int(os.getenv("ANALYSIS_TOP_K", "5"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
VERBOSE = os.getenv("VERBOSE", "1") == "1"

OUTPUT_PATH = Path(CACHE_DIR) / "reranker_stability_experiment.json"
REPORT_PATH = Path(CACHE_DIR) / "reranker_stability_experiment_report.json"


def prepare_inputs(rerank_top_n: int = RERANK_TOP_N, temperature: float = TEMPERATURE):
    favorites = load_zhihu_items(str(FAVORITES_PATH))
    author_data = load_zhihu_items(str(AUTHOR_PATH))
    collection, candidates_raw = split_collection_candidates(favorites, author_data)

    recsys = build_engine(enable_reranker=True)
    ensure_profile(recsys, collection)

    recsys.add_candidates(build_candidate_items(candidates_raw))
    recsys.embed_candidates(batch_size=recsys._config.batch_size)

    profile_ctx = ProfileContext(
        vector_cloud=recsys.vector_cloud,
        explicit_profile=recsys.explicit_profile,
        summary=recsys.get_profile_summary(),
    )

    score_map = recsys._orchestrator.retrieval_manager.retrieve_all(
        recsys.candidates,
        profile_ctx,
    )
    coarse_ranker = DefaultRanker(
        preset=recsys._config.preset,
        custom_weights=recsys._config.custom_weights,
    )
    coarse_ranked = coarse_ranker.rank(
        score_map,
        top_k=len(recsys.candidates),
        min_score=None,
    )
    coarse_ranked_ids = [item.item_id for item in coarse_ranked][:rerank_top_n]

    ep = recsys.explicit_profile
    exemplar_titles = [
        item.get("title", "")
        for item in recsys.collection_items[:10]
        if item.get("title")
    ]

    llm_client = LMStudioLLMClient(
        base_url=recsys._config.lm_studio_base_url,
        model=recsys._config.reranker_model,
        temperature=temperature,
        max_tokens=500,
    )
    reranker = LLMReranker(
        llm_client=llm_client,
        rerank_top_n=rerank_top_n,
        strategy="pointwise",
    )

    return {
        "recsys": recsys,
        "coarse_ranked_ids": coarse_ranked_ids,
        "profile_topics": getattr(ep, "core_topics", []) if ep else [],
        "profile_styles": getattr(ep, "writing_style", []) if ep else [],
        "profile_negatives": getattr(ep, "negative_tags", []) if ep else [],
        "exemplar_titles": exemplar_titles,
        "reranker": reranker,
    }


def main():
    print("=" * 70)
    print("Monte Carlo Reranker Stability Experiment")
    print("=" * 70)
    print(f"trials={TRIALS}, rerank_top_n={RERANK_TOP_N}, analysis_top_k={ANALYSIS_TOP_K}, temperature={TEMPERATURE}")

    t0 = time.time()
    prepared = prepare_inputs()
    print(f"prepared coarse candidate set in {time.time() - t0:.1f}s")

    experiment = RerankerStabilityExperiment(prepared["reranker"])
    result = experiment.run(
        candidates=prepared["recsys"].candidates,
        profile_topics=prepared["profile_topics"],
        profile_styles=prepared["profile_styles"],
        profile_negatives=prepared["profile_negatives"],
        exemplar_titles=prepared["exemplar_titles"],
        coarse_ranked_ids=prepared["coarse_ranked_ids"],
        trials=TRIALS,
        analysis_top_k=ANALYSIS_TOP_K,
        verbose=VERBOSE,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(result["summary"], f, ensure_ascii=False, indent=2)

    summary = result["summary"]
    print(f"top1_mode_title: {summary['top1_mode_title']}")
    print(f"top1_mode_rate: {summary['top1_mode_rate']}")
    print(f"top1_unique_count: {summary['top1_unique_count']}")
    print(f"mean_score_std: {summary['mean_score_std']}")
    print(f"mean_rank_std: {summary['mean_rank_std']}")
    print(f"mean_pairwise_order_stability: {summary['mean_pairwise_order_stability']}")
    print(f"mean_topk_jaccard: {summary['mean_topk_jaccard']}")
    print(f"mean_spearman: {summary['mean_spearman']}")
    print(f"conclusion: {summary['conclusion']}")
    print(f"\nraw output: {OUTPUT_PATH}")
    print(f"report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
