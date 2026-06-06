"""
精排机制 - 制定计分公式
加权融合多维度分数，输出最终排序
"""

import numpy as np
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


class ScoreComponent(Enum):
    """分数组成成分"""
    I2I = "i2i"              # Item-to-Item相似度 (Rocchio Score)
    TAG = "tag"              # 标签匹配分数
    POPULARITY = "popularity" # 流行度分数
    SOURCE = "source"        # 来源偏好分数
    FACET = "facet"          # 深度/风格偏好分数
    QUALITY = "quality"      # LLM 质量评分
    EXPLORE = "explore"      # 探索加分
    RERANK = "rerank"        # LLM重排分数


@dataclass
class RankedItem:
    """排序后的推荐项"""
    item_id: str
    final_score: float
    component_scores: Dict[str, float] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)
    rank: int = 0


class WeightedScorer:
    """
    加权计分器
    实现 Final_Score = Σ(Wi * Score_i) 的核心逻辑
    """

    def __init__(self, weights: Dict[ScoreComponent, float],
                 normalize: bool = True,
                 custom_scorers: Optional[Dict[str, Callable]] = None):
        """
        Args:
            weights: 各分数成分的权重，如 {ScoreComponent.I2I: 0.6, ...}
            normalize: 是否对每个成分进行归一化
            custom_scorers: 自定义评分函数
        """
        self.weights = weights
        self.normalize = normalize
        self.custom_scorers = custom_scorers or {}

        # 存储用于归一化的统计信息
        self.score_stats: Dict[str, Dict] = {}

    def _normalize_score(self, score: float, component: str,
                        all_scores: List[float]) -> float:
        """将分数归一化到[0, 1]范围"""
        if not all_scores or len(all_scores) < 2:
            return max(0.0, min(1.0, score))

        min_val = min(all_scores)
        max_val = max(all_scores)

        if max_val == min_val:
            return 1.0 if score >= max_val else 0.0

        normalized = (score - min_val) / (max_val - min_val)
        return max(0.0, min(1.0, normalized))

    def calculate(self, item_scores: Dict[str, Dict[ScoreComponent, float]],
                  item_metadata: Optional[Dict[str, Dict]] = None) -> List[RankedItem]:
        """
        计算最终排序

        Args:
            item_scores: {item_id: {ScoreComponent: raw_score}}
            item_metadata: 额外的元数据

        Returns:
            List[RankedItem]: 排序后的推荐列表
        """
        item_metadata = item_metadata or {}

        # 收集所有分数用于归一化
        all_scores_by_component: Dict[ScoreComponent, List[float]] = {
            comp: [] for comp in self.weights.keys()
        }

        for scores in item_scores.values():
            for comp, score in scores.items():
                if comp in all_scores_by_component:
                    all_scores_by_component[comp].append(score)

        # 计算每个item的最终分数
        results = []
        for item_id, scores in item_scores.items():
            component_scores = {}
            final_score = 0.0

            for component, weight in self.weights.items():
                raw_score = scores.get(component, 0.0)

                # 归一化
                if self.normalize:
                    all_comp_scores = all_scores_by_component.get(component, [])
                    norm_score = self._normalize_score(raw_score, component.value, all_comp_scores)
                else:
                    norm_score = raw_score

                component_scores[component.value] = norm_score
                final_score += weight * norm_score

            # 应用自定义评分函数
            for name, scorer_fn in self.custom_scorers.items():
                custom_score = scorer_fn(item_id, scores, item_metadata.get(item_id, {}))
                component_scores[f"custom_{name}"] = custom_score
                final_score += custom_score

            results.append(RankedItem(
                item_id=item_id,
                final_score=final_score,
                component_scores=component_scores,
                metadata=item_metadata.get(item_id, {})
            ))

        # 按最终分数降序排序
        results.sort(key=lambda x: x.final_score, reverse=True)

        # 设置排名
        for i, item in enumerate(results, 1):
            item.rank = i

        return results


class ConfigurableScorer:
    """
    可配置计分器 - 支持多种预设评分模式
    """

    # 预设配置
    PRESETS = {
        "balanced": {
            "weights": {
                ScoreComponent.I2I: 0.4,
                ScoreComponent.TAG: 0.2,
                ScoreComponent.POPULARITY: 0.1,
                ScoreComponent.SOURCE: 0.15,
                ScoreComponent.FACET: 0.1,
                ScoreComponent.QUALITY: 0.05
            },
            "description": "平衡模式 - 综合考虑内容相似度和质量"
        },
        "exploration": {
            "weights": {
                ScoreComponent.I2I: 0.3,
                ScoreComponent.TAG: 0.5,
                ScoreComponent.POPULARITY: 0.2
            },
            "description": "探索模式 - 弱化精确匹配，发现新内容"
        },
        "precision": {
            "weights": {
                ScoreComponent.I2I: 0.7,
                ScoreComponent.TAG: 0.2,
                ScoreComponent.POPULARITY: 0.1
            },
            "description": "精确模式 - 强调查找与你收藏最相似的内容"
        },
        "quality": {
            "weights": {
                ScoreComponent.I2I: 0.3,
                ScoreComponent.TAG: 0.2,
                ScoreComponent.POPULARITY: 0.5
            },
            "description": "质量模式 - 优先高质量/高互动内容"
        }
    }

    def __init__(self, preset: str = "balanced", custom_weights: Optional[Dict] = None):
        """
        Args:
            preset: 预设模式名称
            custom_weights: 自定义权重（覆盖preset）
        """
        if preset not in self.PRESETS:
            raise ValueError(f"Unknown preset: {preset}. Available: {list(self.PRESETS.keys())}")

        self.preset_name = preset
        self.config = self.PRESETS[preset]
        self.weights = custom_weights or self.config["weights"]

    def get_scorer(self, **kwargs) -> WeightedScorer:
        """创建配置好的WeightedScorer实例"""
        return WeightedScorer(weights=self.weights, **kwargs)

    def list_presets(self) -> Dict[str, str]:
        """列出所有预设及其描述"""
        return {name: config["description"] for name, config in self.PRESETS.items()}
