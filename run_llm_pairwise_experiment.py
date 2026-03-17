"""
Run pairwise LLM experiments with order swap: baseline vs rerank and rerank vs baseline.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.evaluation.llm_pairwise import LLMPairwiseExperiment


CACHE_DIR = Path("./data/real_data_cache")
DATA_DIR = Path("datacrawl/zhihu_crawler/data")
FAVORITES_PATH = DATA_DIR / "favorites_cjm926_all_20260305_150447.json"
EXPLICIT_PROFILE_PATH = CACHE_DIR / "explicit_profile.json"
OUTPUT_PATH = CACHE_DIR / "llm_pairwise_order_experiment.json"
REPORT_PATH = CACHE_DIR / "llm_pairwise_order_experiment_report.json"
PAIRWISE_STRATEGY = os.getenv("PAIRWISE_STRATEGY", "rank_aligned")
MAX_PAIRS = int(os.getenv("MAX_PAIRS", "3"))
VERBOSE = os.getenv("VERBOSE", "1") == "1"


def main():
    experiment = LLMPairwiseExperiment()
    result = experiment.run(
        cache_dir=str(CACHE_DIR),
        explicit_profile_path=str(EXPLICIT_PROFILE_PATH),
        favorites_path=str(FAVORITES_PATH),
        strategy=PAIRWISE_STRATEGY,
        skip_same_item=True,
        max_pairs=MAX_PAIRS,
        verbose=VERBOSE,
    )

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(result["summary"], f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("LLM Pairwise Order Experiment")
    print("=" * 70)
    print(f"strategy: {result['strategy']}")
    print(f"pair_count: {result['pair_count']}")
    print(f"order_consistent_pairs: {result['summary']['order_consistent_pairs']}")
    print(f"order_inconsistent_pairs: {result['summary']['order_inconsistent_pairs']}")
    print(f"order_flip_rate: {result['summary']['order_flip_rate']}")
    print(f"forward_baseline_wins: {result['summary']['forward_baseline_wins']}")
    print(f"forward_rerank_wins: {result['summary']['forward_rerank_wins']}")
    print(f"forward_parse_failures: {result['summary']['forward_parse_failures']}")
    print(f"reverse_baseline_wins: {result['summary']['reverse_baseline_wins']}")
    print(f"reverse_rerank_wins: {result['summary']['reverse_rerank_wins']}")
    print(f"reverse_parse_failures: {result['summary']['reverse_parse_failures']}")
    print(f"resolved_baseline_wins: {result['summary']['resolved_baseline_wins']}")
    print(f"resolved_rerank_wins: {result['summary']['resolved_rerank_wins']}")
    print(f"resolved_ties: {result['summary']['resolved_ties']}")
    print(f"resolved_unstable: {result['summary']['resolved_unstable']}")
    print(f"rerank_win_rate: {result['summary']['rerank_win_rate']}")
    print(f"conclusion: {result['summary']['conclusion']}")
    print(f"\nraw output: {OUTPUT_PATH}")
    print(f"report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
