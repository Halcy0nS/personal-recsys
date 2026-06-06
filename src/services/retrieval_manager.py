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
    """I2I 召回器 - 封装 I2IMatcher 并应用 Rocchio 负反馈机制"""

    def __init__(self, top_k: int = 3, metric: str = "cosine", gamma: float = 1.5,
                 duplicate_threshold: float = 0.95, negative_soft_threshold: float = 0.80, max_negative_penalty: float = 0.5):
        self.matcher = I2IMatcher(top_k=top_k, metric=metric)
        self.gamma = gamma
        self.duplicate_threshold = duplicate_threshold
        self.negative_soft_threshold = negative_soft_threshold
        self.max_negative_penalty = max_negative_penalty

    def name(self) -> str:
        return ScoreComponent.I2I.value

    def score(self, candidates: Dict, profile_ctx: ProfileContext) -> Dict[str, float]:
        vector_cloud = profile_ctx.vector_cloud
        fml = profile_ctx.feedback_memory
        scores = {}

        for item_id, candidate in candidates.items():
            embedding = candidate.embedding
            if embedding is not None:
                # 1. 正向相似度 S_pos
                s_pos = self.matcher.match(embedding, vector_cloud).i2i_score
                
                # 2. 负向相似度 S_neg
                s_neg = 0.0
                if fml and fml.negative_vectors:
                    neg_mat = fml.get_negative_vectors_matrix()
                    sims = [self.matcher.compute_similarity(embedding, v) for v in neg_mat]
                    sims.sort(reverse=True)
                    s_neg = np.mean(sims[:self.matcher.top_k]) if sims else 0.0
                
                # 3. 查重相似度 S_dup
                s_dup = 0.0
                if fml and fml.duplicate_vectors:
                    dup_mat = fml.get_duplicate_vectors_matrix()
                    sims = [self.matcher.compute_similarity(embedding, v) for v in dup_mat]
                    s_dup = max(sims) if sims else 0.0
                
                # Rocchio 公式与双层惩罚
                if s_dup > self.duplicate_threshold:
                    final_score = -999.0 # 硬惩罚：直接拉黑
                else:
                    if s_neg > self.negative_soft_threshold:
                        penalty = min(self.gamma * s_neg, self.max_negative_penalty)
                        final_score = s_pos - penalty
                    else:
                        final_score = s_pos
                        
                scores[item_id] = final_score
            else:
                scores[item_id] = 0.0

        return scores


class FeedbackRetriever(BaseRetriever):
    """反馈记忆召回器 - 提取来源偏好、标签偏好与 LLM 质量分"""
    
    def name(self) -> str:
        return "feedback_memory_multi" # 这是一个占位，在 RetrievalManager 中会特殊处理

    def score(self, candidates: Dict, profile_ctx: ProfileContext) -> Dict[str, float]:
        fml = profile_ctx.feedback_memory
        
        scores = {item_id: {
            ScoreComponent.SOURCE.value: 0.0,
            ScoreComponent.FACET.value: 0.0,
            ScoreComponent.QUALITY.value: 0.0,
            ScoreComponent.EXPLORE.value: 0.0
        } for item_id in candidates.keys()}
        
        for item_id, candidate in candidates.items():
            metadata = candidate.metadata.get("frontmatter", {})
            source = candidate.metadata.get("source", "unknown")
            author = metadata.get("author", "unknown")
            depth = metadata.get("depth", "unknown")
            style = metadata.get("style", "unknown")
            quality = metadata.get("quality", 3) # 默认为3
            
            try:
                scores[item_id][ScoreComponent.QUALITY.value] = float(quality) / 5.0 # 归一化质量
            except (ValueError, TypeError):
                scores[item_id][ScoreComponent.QUALITY.value] = 0.6
                
            if fml:
                src_score = fml.get_source_score(source) + fml.get_author_score(author)
                facet_score = fml.get_facet_score(depth) + fml.get_facet_score(style)
                
                scores[item_id][ScoreComponent.SOURCE.value] = float(src_score)
                scores[item_id][ScoreComponent.FACET.value] = float(facet_score)
                
                # 探索加分: 如果该来源和特征之前从未获得过正负反馈，给予探索奖励
                if src_score == 0 and facet_score == 0:
                    scores[item_id][ScoreComponent.EXPLORE.value] = 1.0
                    
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
                     profile_ctx: ProfileContext) -> ScoreMap:
        """
        运行所有召回器，聚合为统一 ScoreMap

        Args:
            candidates: {item_id: CandidateItem}
            profile_ctx: 画像上下文

        Returns:
            ScoreMap: {item_id: {component_name: score}}
        """
        score_map: ScoreMap = {item_id: {} for item_id in candidates.keys()}

        # 运行每个召回器
        for retriever in self.retrievers:
            retriever_scores = retriever.score(candidates, profile_ctx)
            component_name = retriever.name()

            if component_name == "feedback_memory_multi":
                # FeedbackRetriever 返回的是 Dict[str, Dict[str, float]]
                for item_id, multi_scores in retriever_scores.items():
                    if item_id in score_map:
                        score_map[item_id].update(multi_scores)
            else:
                for item_id, s in retriever_scores.items():
                    if item_id in score_map:
                        score_map[item_id][component_name] = s

        # 补充 popularity 等元数据分数（仅当候选包含 popularity 元数据时生效）
        for item_id, candidate in candidates.items():
            pop = candidate.metadata.get("popularity")
            if pop is not None:
                score_map[item_id][ScoreComponent.POPULARITY.value] = float(pop)

        return score_map
