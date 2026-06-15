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

    def __init__(self, top_k: int = 3, metric: str = "cosine", time_decay_rate: float = 0.05):
        """
        Args:
            top_k: 取收藏夹中最近的top_k个向量的平均相似度
            metric: 距离度量 (cosine/dot/euclidean)
            time_decay_rate: 时序衰减率
        """
        self.top_k = top_k
        self.metric = metric
        self.time_decay_rate = time_decay_rate

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

        # 取top_k
        similarities.sort(reverse=True, key=lambda x: x[0])
        top_similarities = similarities[:self.top_k]

        if not top_similarities:
            avg_score = 0.0
        else:
            time_weights = user_vector_cloud.get_time_weights(self.time_decay_rate)
            weighted_sum = sum(sim * time_weights[idx] for sim, idx in top_similarities)
            weight_total = sum(time_weights[idx] for _, idx in top_similarities)
            avg_score = weighted_sum / weight_total if weight_total > 0 else 0.0

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
        批量计算匹配分数 (完全向量化版本)
        """
        from ..profiling.implicit_profile import VectorCloud
        if not isinstance(user_vector_cloud, VectorCloud) or not user_vector_cloud.vectors:
            return [I2IResult(item_id=cid, i2i_score=0.0, matched_source_indices=[], similarities=[]) 
                    for cid in candidate_ids]

        if not candidate_vectors:
            return []

        # 构建候选矩阵并归一化
        cand_mat = np.vstack(candidate_vectors).astype(np.float32)
        norms = np.linalg.norm(cand_mat, axis=1, keepdims=True)
        cand_mat = cand_mat / (norms + 1e-8)

        # 获取向量云矩阵 (已归一化)
        cloud_mat = user_vector_cloud.vectors_matrix

        # 计算余弦相似度矩阵: shape (N_candidates, M_cloud_vectors)
        sim_mat = np.dot(cand_mat, cloud_mat.T)
        
        N, M = sim_mat.shape
        top_k = min(self.matcher.top_k, M)

        if top_k == M:
            top_indices = np.argsort(sim_mat, axis=1)[:, ::-1]
            top_sims = np.take_along_axis(sim_mat, top_indices, axis=1)
        else:
            # np.argpartition is faster for O(N) extraction
            top_indices_unsorted = np.argpartition(sim_mat, -top_k, axis=1)[:, -top_k:]
            top_sims_unsorted = np.take_along_axis(sim_mat, top_indices_unsorted, axis=1)
            
            # Sort locally for each row
            local_sort_idx = np.argsort(top_sims_unsorted, axis=1)[:, ::-1]
            top_indices = np.take_along_axis(top_indices_unsorted, local_sort_idx, axis=1)
            top_sims = np.take_along_axis(top_sims_unsorted, local_sort_idx, axis=1)

        # 获取时序权重
        time_weights = user_vector_cloud.get_time_weights(self.matcher.time_decay_rate)
        weights_for_top = time_weights[top_indices]  # shape: (N, top_k)
        weight_sums = np.sum(weights_for_top, axis=1)
        weight_sums[weight_sums == 0] = 1e-8
        
        avg_scores = np.sum(top_sims * weights_for_top, axis=1) / weight_sums

        results = []
        for i in range(N):
            results.append(I2IResult(
                item_id=candidate_ids[i],
                i2i_score=float(avg_scores[i]),
                matched_source_indices=top_indices[i].tolist(),
                similarities=top_sims[i].tolist()
            ))

        return results
