"""
DefaultRanker - 封装现有精排逻辑
"""

from typing import Dict, List, Optional

from ..contracts.interfaces import BaseRanker
from ..contracts.types import ScoreMap
from ..ranking.scorer import (
    ConfigurableScorer, WeightedScorer, ScoreComponent, RankedItem
)


class DefaultRanker(BaseRanker):
    """默认精排器 - 封装 ConfigurableScorer + WeightedScorer"""

    def __init__(self, preset: str = "balanced",
                 custom_weights: Optional[Dict] = None):
        self.preset = preset
        self.custom_weights = self._normalize_weights(custom_weights)

    def _normalize_weights(self, custom_weights: Optional[Dict]) -> Optional[Dict]:
        """允许调用方使用字符串或 ScoreComponent 作为权重 key。"""
        if custom_weights is None:
            return None

        normalized = {}
        for component, weight in custom_weights.items():
            if isinstance(component, ScoreComponent):
                normalized[component] = weight
                continue

            try:
                normalized[ScoreComponent(component)] = weight
            except ValueError:
                raise ValueError(f"Unknown score component in custom_weights: {component}")

        return normalized

    def rank(self, score_map: ScoreMap,
             item_metadata: Optional[Dict] = None,
             top_k: int = 20,
             min_score: Optional[float] = None) -> List[RankedItem]:
        """精排融合"""

        # 将字符串 key 转换回 ScoreComponent enum
        item_scores = {}
        for item_id, component_scores in score_map.items():
            enum_scores = {}
            for comp_name, score in component_scores.items():
                try:
                    comp = ScoreComponent(comp_name)
                    enum_scores[comp] = score
                except ValueError:
                    pass  # 跳过未知的 component
            item_scores[item_id] = enum_scores

        # 使用 ConfigurableScorer
        config_scorer = ConfigurableScorer(
            preset=self.preset,
            custom_weights=self.custom_weights
        )
        scorer = config_scorer.get_scorer()

        ranked_items = scorer.calculate(item_scores)

        # 应用最低分数阈值
        if min_score is not None:
            ranked_items = [item for item in ranked_items if item.final_score >= min_score]

        # 截取 top_k
        ranked_items = ranked_items[:top_k]

        return ranked_items
