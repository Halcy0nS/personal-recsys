"""
Item-to-Item (I2I) 最近邻匹配算法
基于向量云的相似度计算
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class I2IResult:
    """I2I匹配结果"""
    item_id: str
    i2i_score: float
    matched_source_indices: List[int]  # 匹配到的收藏夹中的索引
    similarities: List[float]


class I2IMatcher:
    """
    Item-to-Item 匹配器
    实现 "因为我收藏了X，所以推荐像X的内容" 逻辑
    """

    def __init__(self, top_k: int = 3, metric: str = "cosine"):
        """
        Args:
            top_k: 取收藏夹中最近的top_k个向量的平均相似度
            metric: 距离度量 (cosine/dot/euclidean)
        """
        self.top_k = top_k
        self.metric = metric

    def compute_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """计算两个向量的相似度"""
        # 归一化
        v1 = vec1 / (np.linalg.norm(vec1) + 1e-8)
        v2 = vec2 / (np.linalg.norm(vec2) + 1e-8)

        if self.metric == "cosine":
            return float(np.dot(v1, v2))
        elif self.metric == "dot":
            return float(np.dot(vec1, vec2))
        elif self.metric == "euclidean":
            return 1.0 / (1.0 + np.linalg.norm(v1 - v2))
        else:
            return float(np.dot(v1, v2))

    def match(self, candidate_vector: np.ndarray,
              user_vector_cloud: "VectorCloud") -> I2IResult:
        """
        计算候选内容与用户向量云的I2I匹配分数

        Args:
            candidate_vector: 候选内容的embedding向量
            user_vector_cloud: 用户的向量云（收藏夹）

        Returns:
            I2IResult: 匹配结果
        """
        from ..profiling.implicit_profile import VectorCloud

        if not isinstance(user_vector_cloud, VectorCloud):
            raise TypeError("user_vector_cloud must be a VectorCloud instance")

        if not user_vector_cloud.vectors:
            return I2IResult(
                item_id="",
                i2i_score=0.0,
                matched_source_indices=[],
                similarities=[]
            )

        # 计算与收藏夹中每个向量的相似度
        similarities = []
        for i, vec in enumerate(user_vector_cloud.vectors):
            sim = self.compute_similarity(candidate_vector, vec)
            similarities.append((sim, i))

        # 排序取top_k
        similarities.sort(reverse=True, key=lambda x: x[0])
        top_similarities = similarities[:self.top_k]

        # 计算平均分
        avg_score = np.mean([sim for sim, _ in top_similarities]) if top_similarities else 0.0

        return I2IResult(
            item_id="",  # 由调用方填充
            i2i_score=float(avg_score),
            matched_source_indices=[idx for _, idx in top_similarities],
            similarities=[float(sim) for sim, _ in top_similarities]
        )


class BatchI2IMatcher:
    """批量I2I匹配器，用于高效处理大量候选内容"""

    def __init__(self, matcher: I2IMatcher):
        self.matcher = matcher

    def match_batch(self, candidate_vectors: List[np.ndarray],
                    candidate_ids: List[str],
                    user_vector_cloud: "VectorCloud") -> List[I2IResult]:
        """
        批量计算匹配分数

        Args:
            candidate_vectors: 候选内容的embedding向量列表
            candidate_ids: 对应的ID列表
            user_vector_cloud: 用户的向量云

        Returns:
            List[I2IResult]: 匹配结果列表
        """
        results = []
        for vec, item_id in zip(candidate_vectors, candidate_ids):
            result = self.matcher.match(vec, user_vector_cloud)
            result.item_id = item_id
            results.append(result)
        return results
