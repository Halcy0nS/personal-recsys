"""
Monte Carlo stability analysis for reranker outputs.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class TrialItemResult:
    item_id: str
    title: str
    score: float
    confidence: float
    reasoning: str
    rank: int


class RerankerStabilityExperiment:
    """Run the same rerank task multiple times and summarize volatility."""

    def __init__(self, reranker):
        self.reranker = reranker

    def run(
        self,
        candidates: Dict,
        profile_topics: List[str],
        profile_styles: List[str],
        profile_negatives: List[str],
        exemplar_titles: List[str],
        coarse_ranked_ids: List[str],
        trials: int = 10,
        analysis_top_k: int = 5,
        verbose: bool = False,
    ) -> Dict:
        if trials <= 0:
            raise ValueError("trials must be > 0")

        trial_results = []
        selected_ids = list(coarse_ranked_ids[: getattr(self.reranker, "rerank_top_n", len(coarse_ranked_ids))])

        for trial_index in range(1, trials + 1):
            if verbose:
                print(f"[trial {trial_index}/{trials}] reranking {len(selected_ids)} items...", flush=True)

            results = self.reranker.rerank(
                candidates=candidates,
                profile_topics=profile_topics,
                profile_styles=profile_styles,
                profile_negatives=profile_negatives,
                exemplar_titles=exemplar_titles,
                coarse_ranked_ids=selected_ids,
            )
            trial_results.append(self._serialize_trial(results, candidates, trial_index))

        summary = self.summarize_results(trial_results, analysis_top_k=analysis_top_k)
        return {
            "created_at": datetime.now().isoformat(),
            "trial_count": trials,
            "candidate_count": len(selected_ids),
            "analysis_top_k": analysis_top_k,
            "candidate_ids": selected_ids,
            "trial_results": trial_results,
            "summary": summary,
        }

    def _serialize_trial(self, results: List, candidates: Dict, trial_index: int) -> Dict:
        ranked_items = []
        for rank, result in enumerate(results, 1):
            candidate = candidates.get(result.item_id)
            ranked_items.append(
                TrialItemResult(
                    item_id=result.item_id,
                    title=candidate.title if candidate else result.item_id,
                    score=float(result.relevance_score),
                    confidence=float(result.confidence),
                    reasoning=str(result.reasoning),
                    rank=rank,
                )
            )

        return {
            "trial_index": trial_index,
            "items": [asdict(item) for item in ranked_items],
        }

    def summarize_results(self, trial_results: List[Dict], analysis_top_k: int = 5) -> Dict:
        if not trial_results:
            return {
                "top1_mode_rate": None,
                "top1_unique_count": 0,
                "mean_score_std": None,
                "mean_rank_std": None,
                "mean_pairwise_order_stability": None,
                "mean_topk_jaccard": None,
                "mean_spearman": None,
                "conclusion": "No rerank trials recorded",
                "items": [],
            }

        item_scores = defaultdict(list)
        item_ranks = defaultdict(list)
        item_titles = {}
        top1_counter = Counter()
        topk_sets = []
        rank_maps = []

        for trial in trial_results:
            rank_map = {}
            topk = []
            for item in trial["items"]:
                item_id = item["item_id"]
                item_titles[item_id] = item["title"]
                item_scores[item_id].append(float(item["score"]))
                item_ranks[item_id].append(int(item["rank"]))
                rank_map[item_id] = int(item["rank"])
                if item["rank"] == 1:
                    top1_counter[item_id] += 1
                if item["rank"] <= analysis_top_k:
                    topk.append(item_id)
            topk_sets.append(set(topk))
            rank_maps.append(rank_map)

        item_summaries = []
        score_stds = []
        rank_stds = []
        total_trials = len(trial_results)

        for item_id in sorted(item_titles.keys()):
            scores = item_scores[item_id]
            ranks = item_ranks[item_id]
            score_std = self._std(scores)
            rank_std = self._std(ranks)
            score_stds.append(score_std)
            rank_stds.append(rank_std)

            item_summaries.append({
                "item_id": item_id,
                "title": item_titles[item_id],
                "mean_score": round(self._mean(scores), 4),
                "score_std": round(score_std, 4),
                "min_score": round(min(scores), 4),
                "max_score": round(max(scores), 4),
                "mean_rank": round(self._mean(ranks), 4),
                "rank_std": round(rank_std, 4),
                "top1_count": top1_counter[item_id],
                "top1_rate": round(top1_counter[item_id] / total_trials, 4),
                "topk_count": sum(1 for rank in ranks if rank <= analysis_top_k),
                "topk_rate": round(sum(1 for rank in ranks if rank <= analysis_top_k) / total_trials, 4),
            })

        item_summaries.sort(key=lambda item: (item["mean_rank"], -item["mean_score"]))

        top1_mode_id, top1_mode_count = top1_counter.most_common(1)[0]
        pairwise_stability = self._mean_pairwise_order_stability(rank_maps)
        topk_jaccard = self._mean_topk_jaccard(topk_sets)
        spearman = self._mean_spearman(rank_maps)

        summary = {
            "top1_mode_item_id": top1_mode_id,
            "top1_mode_title": item_titles[top1_mode_id],
            "top1_mode_count": top1_mode_count,
            "top1_mode_rate": round(top1_mode_count / total_trials, 4),
            "top1_unique_count": len(top1_counter),
            "mean_score_std": round(self._mean(score_stds), 4),
            "mean_rank_std": round(self._mean(rank_stds), 4),
            "mean_pairwise_order_stability": round(pairwise_stability, 4),
            "mean_topk_jaccard": round(topk_jaccard, 4),
            "mean_spearman": round(spearman, 4),
            "items": item_summaries,
        }
        summary["conclusion"] = self._build_conclusion(summary)
        return summary

    def _build_conclusion(self, summary: Dict) -> str:
        top1_rate = summary["top1_mode_rate"]
        pairwise_stability = summary["mean_pairwise_order_stability"]
        mean_rank_std = summary["mean_rank_std"]

        if top1_rate >= 0.9 and pairwise_stability >= 0.95 and mean_rank_std <= 0.5:
            return "Reranker output is highly stable under repeated trials"
        if top1_rate >= 0.7 and pairwise_stability >= 0.85 and mean_rank_std <= 1.0:
            return "Reranker output is moderately stable under repeated trials"
        return "Reranker output shows notable Monte Carlo volatility"

    def _mean_pairwise_order_stability(self, rank_maps: List[Dict[str, int]]) -> float:
        if len(rank_maps) < 1:
            return 0.0

        item_ids = sorted(rank_maps[0].keys())
        pair_scores = []

        for left_id, right_id in itertools.combinations(item_ids, 2):
            left_wins = 0
            for rank_map in rank_maps:
                if rank_map[left_id] < rank_map[right_id]:
                    left_wins += 1
            win_rate = left_wins / len(rank_maps)
            pair_scores.append(max(win_rate, 1.0 - win_rate))

        return self._mean(pair_scores) if pair_scores else 1.0

    def _mean_topk_jaccard(self, topk_sets: List[set]) -> float:
        if len(topk_sets) < 2:
            return 1.0

        values = []
        for left, right in itertools.combinations(topk_sets, 2):
            union = left | right
            if not union:
                values.append(1.0)
            else:
                values.append(len(left & right) / len(union))
        return self._mean(values)

    def _mean_spearman(self, rank_maps: List[Dict[str, int]]) -> float:
        if len(rank_maps) < 2:
            return 1.0

        values = []
        for left, right in itertools.combinations(rank_maps, 2):
            values.append(self._spearman(left, right))
        return self._mean(values)

    def _spearman(self, left: Dict[str, int], right: Dict[str, int]) -> float:
        item_ids = sorted(left.keys())
        n = len(item_ids)
        if n < 2:
            return 1.0

        diff_sum = 0.0
        for item_id in item_ids:
            diff = left[item_id] - right[item_id]
            diff_sum += diff * diff

        return 1.0 - (6.0 * diff_sum) / (n * (n * n - 1))

    def _mean(self, values: List[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _std(self, values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = self._mean(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return math.sqrt(variance)
