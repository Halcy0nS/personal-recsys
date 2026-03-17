"""
RecommendationComparator - 保存 baseline 与 rerank 结果的盲测数据与人工评估记录
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ComparisonDecision:
    """人工评估记录。"""
    comparison_id: str
    winner: str  # baseline | rerank | tie
    reason: str
    created_at: str


class RecommendationComparator:
    """比较 baseline 与 rerank 推荐结果并保存盲测数据。"""

    def __init__(self, output_dir: str = "./data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.output_dir / "comparison_history.json"

    def _load_history(self) -> List[Dict]:
        if not self.history_path.exists():
            return []

        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def build_blind_comparison(
        self,
        baseline_results: List,
        rerank_results: List,
        candidates: Dict[str, object],
        top_k: int = 10,
        seed: int = 42,
    ) -> Dict:
        """生成隐藏来源的盲测对比数据。"""
        items = []

        for method_name, results in (
            ("baseline", baseline_results[:top_k]),
            ("rerank", rerank_results[:top_k]),
        ):
            for rank, result in enumerate(results, 1):
                candidate = candidates.get(result.item_id)
                items.append({
                    "blind_id": f"{method_name}_{rank}_{result.item_id}",
                    "item_id": result.item_id,
                    "title": getattr(candidate, "title", ""),
                    "summary": getattr(candidate, "content", "")[:240],
                    "url": getattr(candidate, "metadata", {}).get("url", ""),
                    "source": method_name,
                    "source_rank": rank,
                    "final_score": round(result.final_score, 6),
                })

        shuffled_items = list(items)
        random.Random(seed).shuffle(shuffled_items)

        answer_key = {
            item["blind_id"]: {
                "source": item["source"],
                "source_rank": item["source_rank"],
            }
            for item in shuffled_items
        }

        blind_items = []
        for item in shuffled_items:
            blind_items.append({
                "blind_id": item["blind_id"],
                "item_id": item["item_id"],
                "title": item["title"],
                "summary": item["summary"],
                "url": item["url"],
                "final_score": item["final_score"],
            })

        return {
            "comparison_id": f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "created_at": datetime.now().isoformat(),
            "baseline_count": min(len(baseline_results), top_k),
            "rerank_count": min(len(rerank_results), top_k),
            "blind_items": blind_items,
            "answer_key": answer_key,
        }

    def save_blind_comparison(
        self,
        comparison: Dict,
        filename: str = "blind_comparison.json",
    ) -> Path:
        """保存盲测对比数据。"""
        output_path = self.output_dir / filename
        answer_key_path = self.output_dir / "blind_comparison_answer_key.json"

        public_payload = {
            key: value for key, value in comparison.items()
            if key != "answer_key"
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(public_payload, f, ensure_ascii=False, indent=2)
        with open(answer_key_path, "w", encoding="utf-8") as f:
            json.dump(comparison.get("answer_key", {}), f, ensure_ascii=False, indent=2)
        return output_path

    def record_decision(self, winner: str, reason: str, comparison_id: Optional[str] = None) -> ComparisonDecision:
        """保存一次人工判断。"""
        decision = ComparisonDecision(
            comparison_id=comparison_id or f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            winner=winner,
            reason=reason,
            created_at=datetime.now().isoformat(),
        )

        history = self._load_history()
        history.append(asdict(decision))
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        return decision

    def generate_report(self, n_recent: int = 20) -> Dict:
        """汇总历史人工判断。"""
        history = self._load_history()
        recent = history[-n_recent:]

        if not recent:
            return {
                "total_decisions": 0,
                "baseline_wins": 0,
                "rerank_wins": 0,
                "ties": 0,
                "conclusion": "No manual decisions recorded yet",
            }

        baseline_wins = sum(1 for item in recent if item["winner"] == "baseline")
        rerank_wins = sum(1 for item in recent if item["winner"] == "rerank")
        ties = sum(1 for item in recent if item["winner"] == "tie")

        if rerank_wins > baseline_wins:
            conclusion = "Rerank performing better in recent manual evaluations"
        elif baseline_wins > rerank_wins:
            conclusion = "Baseline performing better in recent manual evaluations"
        else:
            conclusion = "Baseline and rerank are tied in recent manual evaluations"

        return {
            "total_decisions": len(recent),
            "baseline_wins": baseline_wins,
            "rerank_wins": rerank_wins,
            "ties": ties,
            "conclusion": conclusion,
        }

    def save_report(self, report: Dict, filename: str = "comparison_report.json") -> Path:
        """保存评估汇总。"""
        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return output_path
