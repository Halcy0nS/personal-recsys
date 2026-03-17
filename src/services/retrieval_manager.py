"""
RetrievalManager - 聚合多个召回器输出为统一 ScoreMap
"""

import numpy as np
from typing import Dict, List

from ..contracts.interfaces import BaseRetriever
from ..contracts.types import ProfileContext, ScoreMap
from ..retrieval.i2i_matcher import I2IMatcher
from ..retrieval.tag_matcher import TagMatcher
from ..ranking.scorer import ScoreComponent


class I2IRetriever(BaseRetriever):
    """I2I 召回器 - 封装 I2IMatcher"""

    def __init__(self, top_k: int = 3, metric: str = "cosine"):
        self.matcher = I2IMatcher(top_k=top_k, metric=metric)

    def name(self) -> str:
        return ScoreComponent.I2I.value

    def score(self, candidates: Dict, profile_ctx: ProfileContext) -> Dict[str, float]:
        """计算所有候选的 I2I 分数"""
        vector_cloud = profile_ctx.vector_cloud
        scores = {}

        for item_id, candidate in candidates.items():
            embedding = candidate.embedding
            if embedding is not None:
                result = self.matcher.match(embedding, vector_cloud)
                scores[item_id] = result.i2i_score
            else:
                scores[item_id] = 0.0

        return scores


class TagRetriever(BaseRetriever):
    """标签召回器 - 封装 TagMatcher"""

    def __init__(self, positive_weight: float = 1.0,
                 negative_weight: float = -2.0,
                 hard_filter_negative: bool = True):
        self.matcher = TagMatcher(
            positive_weight=positive_weight,
            negative_weight=negative_weight,
            hard_filter_negative=hard_filter_negative
        )

    def name(self) -> str:
        return ScoreComponent.TAG.value

    def score(self, candidates: Dict, profile_ctx: ProfileContext) -> Dict[str, float]:
        """计算所有候选的标签匹配分数"""
        explicit_profile = profile_ctx.explicit_profile

        if not explicit_profile:
            # 无显式画像，标签分统一回退为 0.5
            return {item_id: 0.5 for item_id in candidates.keys()}

        results = self.matcher.match_batch(
            [
                {
                    "id": candidate.item_id,
                    "tags": candidate.tags,
                    "title": candidate.title,
                    "content": candidate.content
                }
                for candidate in candidates.values()
            ],
            explicit_profile
        )

        return {r.item_id: r.tag_score for r in results}


class RetrievalManager:
    """召回管理器 - 聚合多个召回器输出"""

    def __init__(self, retrievers: List[BaseRetriever] = None):
        self.retrievers = retrievers or []

    def add_retriever(self, retriever: BaseRetriever):
        self.retrievers.append(retriever)

    def retrieve_all(self, candidates: Dict,
                     profile_ctx: ProfileContext,
                     candidate_metadata: Dict = None) -> ScoreMap:
        """
        运行所有召回器，聚合为统一 ScoreMap

        Args:
            candidates: {item_id: CandidateItem}
            profile_ctx: 画像上下文
            candidate_metadata: 额外元数据

        Returns:
            ScoreMap: {item_id: {component_name: score}}
        """
        score_map: ScoreMap = {item_id: {} for item_id in candidates.keys()}

        # 运行每个召回器
        for retriever in self.retrievers:
            retriever_scores = retriever.score(candidates, profile_ctx)
            component_name = retriever.name()

            for item_id, s in retriever_scores.items():
                if item_id in score_map:
                    score_map[item_id][component_name] = s

        # 补充 popularity 等元数据分数
        for item_id, candidate in candidates.items():
            if "popularity" in candidate.metadata:
                score_map[item_id][ScoreComponent.POPULARITY.value] = candidate.metadata["popularity"]

        return score_map
