"""
Utilities for pairwise evaluation over baseline vs rerank blind comparison files.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .glicko2 import GlickoRating, batch_update


@dataclass
class PairwiseMatchup:
    comparison_id: str
    pair_id: str
    blind_id_a: str
    blind_id_b: str
    item_id_a: str
    item_id_b: str
    title_a: str
    title_b: str
    summary_a: str
    summary_b: str
    url_a: str
    url_b: str
    system_a: str
    system_b: str
    rank_a: int
    rank_b: int


@dataclass
class PairwiseDecision:
    comparison_id: str
    pair_id: str
    blind_id_a: str
    blind_id_b: str
    winner: str  # A | B | tie
    winning_system: str  # baseline | rerank | tie
    note: str
    created_at: str

    def to_dict(self) -> Dict:
        return asdict(self)


class PairwiseEvaluationSession:
    """Load blind comparison data and manage pairwise decisions."""

    def __init__(self, cache_dir: str = "./data/real_data_cache"):
        self.cache_dir = Path(cache_dir)
        self.blind_path = self.cache_dir / "blind_comparison.json"
        self.answer_key_path = self.cache_dir / "blind_comparison_answer_key.json"
        self.decisions_path = self.cache_dir / "pairwise_decisions.json"
        self.report_path = self.cache_dir / "pairwise_report.json"
        self.glicko_path = self.cache_dir / "glicko2_ratings.json"

    def _load_json(self, path: Path) -> Dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_comparison(self) -> Tuple[Dict, Dict]:
        return self._load_json(self.blind_path), self._load_json(self.answer_key_path)

    def load_matchups(self, skip_same_item: bool = True) -> List[PairwiseMatchup]:
        return self.load_matchups_by_strategy(
            strategy="cross_system_full",
            skip_same_item=skip_same_item,
        )

    def load_matchups_by_strategy(
        self,
        strategy: str = "cross_system_full",
        skip_same_item: bool = True,
    ) -> List[PairwiseMatchup]:
        comparison, answer_key = self.load_comparison()
        item_by_blind_id = {item["blind_id"]: item for item in comparison["blind_items"]}

        baseline_by_rank = {}
        rerank_by_rank = {}
        for blind_id, meta in answer_key.items():
            source = meta["source"]
            rank = meta["source_rank"]
            if source == "baseline":
                baseline_by_rank[rank] = blind_id
            elif source == "rerank":
                rerank_by_rank[rank] = blind_id

        if strategy == "rank_aligned":
            return self._build_rank_aligned_matchups(
                comparison_id=comparison["comparison_id"],
                item_by_blind_id=item_by_blind_id,
                baseline_by_rank=baseline_by_rank,
                rerank_by_rank=rerank_by_rank,
                skip_same_item=skip_same_item,
            )
        if strategy == "cross_system_full":
            return self._build_cross_system_matchups(
                comparison_id=comparison["comparison_id"],
                item_by_blind_id=item_by_blind_id,
                baseline_by_rank=baseline_by_rank,
                rerank_by_rank=rerank_by_rank,
                skip_same_item=skip_same_item,
            )

        raise ValueError(f"Unknown pairwise strategy: {strategy}")

    def _build_rank_aligned_matchups(
        self,
        comparison_id: str,
        item_by_blind_id: Dict[str, Dict],
        baseline_by_rank: Dict[int, str],
        rerank_by_rank: Dict[int, str],
        skip_same_item: bool,
    ) -> List[PairwiseMatchup]:
        matchups = []
        for rank in sorted(set(baseline_by_rank.keys()) & set(rerank_by_rank.keys())):
            blind_id_a = baseline_by_rank[rank]
            blind_id_b = rerank_by_rank[rank]
            item_a = item_by_blind_id[blind_id_a]
            item_b = item_by_blind_id[blind_id_b]

            if skip_same_item and item_a["item_id"] == item_b["item_id"]:
                continue

            matchups.append(PairwiseMatchup(
                comparison_id=comparison_id,
                pair_id=f"{comparison_id}_rank_{rank}",
                blind_id_a=blind_id_a,
                blind_id_b=blind_id_b,
                item_id_a=item_a["item_id"],
                item_id_b=item_b["item_id"],
                title_a=item_a["title"],
                title_b=item_b["title"],
                summary_a=item_a.get("summary", ""),
                summary_b=item_b.get("summary", ""),
                url_a=item_a["url"],
                url_b=item_b["url"],
                system_a="baseline",
                system_b="rerank",
                rank_a=rank,
                rank_b=rank,
            ))

        return matchups

    def _build_cross_system_matchups(
        self,
        comparison_id: str,
        item_by_blind_id: Dict[str, Dict],
        baseline_by_rank: Dict[int, str],
        rerank_by_rank: Dict[int, str],
        skip_same_item: bool,
    ) -> List[PairwiseMatchup]:
        matchups = []

        for baseline_rank, blind_id_a in sorted(baseline_by_rank.items()):
            item_a = item_by_blind_id[blind_id_a]
            for rerank_rank, blind_id_b in sorted(rerank_by_rank.items()):
                item_b = item_by_blind_id[blind_id_b]

                if skip_same_item and item_a["item_id"] == item_b["item_id"]:
                    continue

                matchups.append(PairwiseMatchup(
                    comparison_id=comparison_id,
                    pair_id=f"{comparison_id}_baseline_{baseline_rank}_vs_rerank_{rerank_rank}",
                    blind_id_a=blind_id_a,
                    blind_id_b=blind_id_b,
                    item_id_a=item_a["item_id"],
                    item_id_b=item_b["item_id"],
                    title_a=item_a["title"],
                    title_b=item_b["title"],
                    summary_a=item_a.get("summary", ""),
                    summary_b=item_b.get("summary", ""),
                    url_a=item_a["url"],
                    url_b=item_b["url"],
                    system_a="baseline",
                    system_b="rerank",
                    rank_a=baseline_rank,
                    rank_b=rerank_rank,
                ))

        return matchups

    def load_decisions(self) -> List[Dict]:
        if not self.decisions_path.exists():
            return []

        try:
            return self._load_json(self.decisions_path)
        except (json.JSONDecodeError, OSError):
            return []

    def save_decision(self, decision: PairwiseDecision) -> None:
        decisions = self.load_decisions()
        decisions = [item for item in decisions if item["pair_id"] != decision.pair_id]
        decisions.append(decision.to_dict())
        decisions.sort(key=lambda item: item["pair_id"])
        with open(self.decisions_path, "w", encoding="utf-8") as f:
            json.dump(decisions, f, ensure_ascii=False, indent=2)

    def build_report(self) -> Dict:
        decisions = self.load_decisions()

        if not decisions:
            report = {
                "total_pairs_decided": 0,
                "baseline_wins": 0,
                "rerank_wins": 0,
                "ties": 0,
                "rerank_win_rate": None,
                "conclusion": "No pairwise decisions recorded yet",
                "updated_at": datetime.now().isoformat(),
            }
            self._save_report(report)
            return report

        baseline_wins = sum(1 for item in decisions if item["winning_system"] == "baseline")
        rerank_wins = sum(1 for item in decisions if item["winning_system"] == "rerank")
        ties = sum(1 for item in decisions if item["winning_system"] == "tie")
        decisive = baseline_wins + rerank_wins
        rerank_win_rate = round(rerank_wins / decisive, 4) if decisive else None

        if rerank_wins > baseline_wins:
            conclusion = "Rerank currently wins more pairwise comparisons"
        elif baseline_wins > rerank_wins:
            conclusion = "Baseline currently wins more pairwise comparisons"
        else:
            conclusion = "Baseline and rerank are currently tied"

        report = {
            "total_pairs_decided": len(decisions),
            "baseline_wins": baseline_wins,
            "rerank_wins": rerank_wins,
            "ties": ties,
            "rerank_win_rate": rerank_win_rate,
            "conclusion": conclusion,
            "updated_at": datetime.now().isoformat(),
        }
        self._save_report(report)
        return report

    def _save_report(self, report: Dict) -> None:
        with open(self.report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def build_glicko_ratings(self) -> Dict[str, Dict]:
        decisions = self.load_decisions()
        match_results = []

        for item in decisions:
            if item["winner"] == "A":
                score_a = 1.0
            elif item["winner"] == "B":
                score_a = 0.0
            else:
                score_a = 0.5

            blind_id_a = item["blind_id_a"]
            blind_id_b = item["blind_id_b"]
            match_results.append((blind_id_a, blind_id_b, score_a))

        updated = batch_update({}, match_results) if match_results else {}

        serialized = {
            blind_id: rating.to_dict()
            for blind_id, rating in updated.items()
        }
        with open(self.glicko_path, "w", encoding="utf-8") as f:
            json.dump(serialized, f, ensure_ascii=False, indent=2)
        return serialized

    def summarize_rankings(self, top_n: int = 10) -> Dict[str, List[Tuple[str, float]]]:
        ratings = self.build_glicko_ratings()
        if not ratings:
            return {"top_items": []}

        sorted_items = sorted(
            ratings.items(),
            key=lambda item: (item[1]["rating"], -item[1]["rd"]),
            reverse=True,
        )
        return {
            "top_items": [
                (blind_id, round(values["rating"], 2))
                for blind_id, values in sorted_items[:top_n]
            ]
        }
