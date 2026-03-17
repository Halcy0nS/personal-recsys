"""
Heuristic attribution experiment:
how much ranking instability comes from judge order bias vs reranker variance.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from run_reranker_stability_experiment import prepare_inputs
from run_real_data import CACHE_DIR, FAVORITES_PATH
from src.evaluation.llm_pairwise import LLMPairwiseExperiment
from src.evaluation.order_instability_attribution import OrderInstabilityAttributionExperiment
from src.evaluation.reranker_stability import RerankerStabilityExperiment


RERANKER_TRIALS = int(os.getenv("RERANKER_TRIALS", "3"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "5"))
RERANK_ANALYSIS_TOP_K = int(os.getenv("RERANK_ANALYSIS_TOP_K", "3"))
JUDGE_PAIR_COUNT = int(os.getenv("JUDGE_PAIR_COUNT", "2"))
JUDGE_TEMPERATURE = float(os.getenv("JUDGE_TEMPERATURE", "0.0"))
VERBOSE = os.getenv("VERBOSE", "1") == "1"

OUTPUT_PATH = Path(CACHE_DIR) / "order_instability_attribution_experiment.json"
REPORT_PATH = Path(CACHE_DIR) / "order_instability_attribution_experiment_report.json"


def main():
    print("=" * 70)
    print("Order Instability Attribution Experiment")
    print("=" * 70)
    print(
        f"reranker_trials={RERANKER_TRIALS}, rerank_top_n={RERANK_TOP_N}, "
        f"rerank_analysis_top_k={RERANK_ANALYSIS_TOP_K}, judge_pair_count={JUDGE_PAIR_COUNT}"
    )

    t0 = time.time()
    prepared = prepare_inputs(rerank_top_n=RERANK_TOP_N, temperature=0.1)
    print(f"prepared inputs in {time.time() - t0:.1f}s")

    judge_experiment = LLMPairwiseExperiment(temperature=JUDGE_TEMPERATURE)
    user_profile = judge_experiment.build_profile_from_cache(
        explicit_profile_path=str(Path(CACHE_DIR) / "explicit_profile.json"),
        favorites_path=str(FAVORITES_PATH),
        exemplar_count=3,
    )

    experiment = OrderInstabilityAttributionExperiment(
        reranker_experiment=RerankerStabilityExperiment(prepared["reranker"]),
        judge_experiment=judge_experiment,
    )

    result = experiment.run(
        candidates=prepared["recsys"].candidates,
        user_profile=user_profile,
        profile_topics=prepared["profile_topics"],
        profile_styles=prepared["profile_styles"],
        profile_negatives=prepared["profile_negatives"],
        exemplar_titles=prepared["exemplar_titles"],
        coarse_ranked_ids=prepared["coarse_ranked_ids"],
        reranker_trials=RERANKER_TRIALS,
        rerank_analysis_top_k=RERANK_ANALYSIS_TOP_K,
        judge_pair_count=JUDGE_PAIR_COUNT,
        verbose=VERBOSE,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "reranker_summary": result["reranker_summary"],
                "fixed_pair_judge_summary": result["fixed_pair_judge_summary"],
                "combined_summary": result["combined_summary"],
                "attribution_estimate": result["attribution_estimate"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\n[Reranker]")
    print(f"mean_pairwise_order_stability: {result['reranker_summary']['mean_pairwise_order_stability']}")
    print(f"mean_rank_std: {result['reranker_summary']['mean_rank_std']}")
    print(f"top1_mode_rate: {result['reranker_summary']['top1_mode_rate']}")

    print("\n[Judge Fixed Pairs]")
    print(f"order_flip_rate: {result['fixed_pair_judge_summary']['order_flip_rate']}")
    print(f"resolved_unstable: {result['fixed_pair_judge_summary']['resolved_unstable']}")

    print("\n[Combined]")
    print(f"order_flip_rate: {result['combined_summary']['order_flip_rate']}")
    print(f"resolved_unstable: {result['combined_summary']['resolved_unstable']}")

    print("\n[Attribution]")
    print(f"judge_order_flip_rate: {result['attribution_estimate']['judge_order_flip_rate']}")
    print(f"reranker_pair_instability: {result['attribution_estimate']['reranker_pair_instability']}")
    print(f"estimated_judge_share: {result['attribution_estimate']['estimated_judge_share']}")
    print(f"estimated_reranker_share: {result['attribution_estimate']['estimated_reranker_share']}")
    print(f"dominant_source: {result['attribution_estimate']['dominant_source']}")
    print(f"note: {result['attribution_estimate']['note']}")

    print(f"\nraw output: {OUTPUT_PATH}")
    print(f"report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
