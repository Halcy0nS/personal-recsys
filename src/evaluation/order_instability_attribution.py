"""
Heuristic attribution of ranking instability between judge order bias and reranker variance.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from .llm_pairwise import LLMPairwiseExperiment, PairwiseArticle, PairwiseUserProfile
from .reranker_stability import RerankerStabilityExperiment


@dataclass
class TrialPair:
    pair_id: str
    trial_index: int
    left_item_id: str
    right_item_id: str
    left_title: str
    right_title: str


class OrderInstabilityAttributionExperiment:
    """
    Split observed instability into:
    1. judge order bias on fixed article pairs
    2. reranker intrinsic variance across repeated trials
    3. combined instability when both effects are present
    """

    def __init__(
        self,
        reranker_experiment: RerankerStabilityExperiment,
        judge_experiment: LLMPairwiseExperiment,
    ):
        self.reranker_experiment = reranker_experiment
        self.judge_experiment = judge_experiment

    def run(
        self,
        candidates: Dict,
        user_profile: PairwiseUserProfile,
        profile_topics: List[str],
        profile_styles: List[str],
        profile_negatives: List[str],
        exemplar_titles: List[str],
        coarse_ranked_ids: List[str],
        reranker_trials: int = 5,
        rerank_analysis_top_k: int = 5,
        judge_pair_count: int = 3,
        verbose: bool = False,
    ) -> Dict:
        reranker_result = self.reranker_experiment.run(
            candidates=candidates,
            profile_topics=profile_topics,
            profile_styles=profile_styles,
            profile_negatives=profile_negatives,
            exemplar_titles=exemplar_titles,
            coarse_ranked_ids=coarse_ranked_ids,
            trials=reranker_trials,
            analysis_top_k=rerank_analysis_top_k,
            verbose=verbose,
        )

        fixed_pairs = self._build_fixed_pairs(
            reranker_result["trial_results"][0]["items"],
            judge_pair_count=judge_pair_count,
            trial_index=1,
            prefix="fixed",
        )
        fixed_pair_results = self._evaluate_pairs(fixed_pairs, user_profile, candidates)

        combined_pairs = []
        for trial in reranker_result["trial_results"]:
            combined_pairs.extend(
                self._build_fixed_pairs(
                    trial["items"],
                    judge_pair_count=judge_pair_count,
                    trial_index=trial["trial_index"],
                    prefix="combined",
                )
            )
        combined_pair_results = self._evaluate_pairs(combined_pairs, user_profile, candidates)

        fixed_summary = self._summarize_pair_results(fixed_pair_results)
        combined_summary = self._summarize_pair_results(combined_pair_results)
        attribution = self._estimate_attribution(
            judge_order_flip_rate=fixed_summary["order_flip_rate"],
            reranker_pair_instability=1.0 - reranker_result["summary"]["mean_pairwise_order_stability"],
        )

        return {
            "created_at": datetime.now().isoformat(),
            "reranker_trials": reranker_trials,
            "rerank_analysis_top_k": rerank_analysis_top_k,
            "judge_pair_count": judge_pair_count,
            "reranker_summary": reranker_result["summary"],
            "fixed_pair_judge_summary": fixed_summary,
            "combined_summary": combined_summary,
            "attribution_estimate": attribution,
            "fixed_pairs": [asdict(pair) for pair in fixed_pairs],
            "fixed_pair_results": fixed_pair_results,
            "combined_pairs": [asdict(pair) for pair in combined_pairs],
            "combined_pair_results": combined_pair_results,
        }

    def _build_fixed_pairs(
        self,
        ranked_items: List[Dict],
        judge_pair_count: int,
        trial_index: int,
        prefix: str,
    ) -> List[TrialPair]:
        selected = ranked_items[: max(2, judge_pair_count + 1)]
        pairs = []

        for idx in range(min(judge_pair_count, len(selected) - 1)):
            left = selected[idx]
            right = selected[idx + 1]
            pairs.append(
                TrialPair(
                    pair_id=f"{prefix}_trial_{trial_index}_pair_{idx + 1}",
                    trial_index=trial_index,
                    left_item_id=left["item_id"],
                    right_item_id=right["item_id"],
                    left_title=left["title"],
                    right_title=right["title"],
                )
            )

        return pairs

    def _evaluate_pairs(
        self,
        pairs: List[TrialPair],
        user_profile: PairwiseUserProfile,
        candidates: Dict,
    ) -> List[Dict]:
        results = []

        for pair in pairs:
            left_candidate = candidates.get(pair.left_item_id)
            right_candidate = candidates.get(pair.right_item_id)
            article_a = PairwiseArticle(
                article_id=pair.left_item_id,
                title=pair.left_title,
                summary=(left_candidate.content[:220] if left_candidate else ""),
            )
            article_b = PairwiseArticle(
                article_id=pair.right_item_id,
                title=pair.right_title,
                summary=(right_candidate.content[:220] if right_candidate else ""),
            )
            result = self.judge_experiment.evaluate_articles(
                user_profile=user_profile,
                article_a=article_a,
                article_b=article_b,
                system_a="left",
                system_b="right",
                pair_id=pair.pair_id,
            )
            result["trial_index"] = pair.trial_index
            results.append(result)

        return results

    def _summarize_pair_results(self, results: List[Dict]) -> Dict:
        summary = {
            "total_pairs": len(results),
            "order_consistent_pairs": 0,
            "order_inconsistent_pairs": 0,
            "order_flip_rate": 0.0,
            "resolved_left_wins": 0,
            "resolved_right_wins": 0,
            "resolved_ties": 0,
            "resolved_unstable": 0,
            "forward_parse_failures": 0,
            "reverse_parse_failures": 0,
        }

        for result in results:
            if result["order_consistent"]:
                summary["order_consistent_pairs"] += 1
            else:
                summary["order_inconsistent_pairs"] += 1

            if not result["forward"]["parsed_ok"]:
                summary["forward_parse_failures"] += 1
            if not result["reverse"]["parsed_ok"]:
                summary["reverse_parse_failures"] += 1

            winner = result["resolved_winner"]
            if winner == "left":
                summary["resolved_left_wins"] += 1
            elif winner == "right":
                summary["resolved_right_wins"] += 1
            elif winner == "tie":
                summary["resolved_ties"] += 1
            else:
                summary["resolved_unstable"] += 1

        if results:
            summary["order_flip_rate"] = round(
                summary["order_inconsistent_pairs"] / len(results),
                4,
            )

        return summary

    def _estimate_attribution(
        self,
        judge_order_flip_rate: float,
        reranker_pair_instability: float,
    ) -> Dict:
        judge_component = max(0.0, judge_order_flip_rate)
        reranker_component = max(0.0, reranker_pair_instability)
        total = judge_component + reranker_component

        if total > 0:
            judge_share = judge_component / total
            reranker_share = reranker_component / total
        else:
            judge_share = 0.0
            reranker_share = 0.0

        if judge_share > reranker_share:
            dominant = "judge_order_bias"
        elif reranker_share > judge_share:
            dominant = "reranker_variance"
        else:
            dominant = "balanced_or_low_signal"

        return {
            "judge_order_flip_rate": round(judge_component, 4),
            "reranker_pair_instability": round(reranker_component, 4),
            "estimated_judge_share": round(judge_share, 4),
            "estimated_reranker_share": round(reranker_share, 4),
            "dominant_source": dominant,
            "note": "This is a heuristic decomposition, not a causal proof.",
        }
