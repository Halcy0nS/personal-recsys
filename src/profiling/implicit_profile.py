"""
隐式画像 - Vector Cloud
将收藏夹内容转化为向量云，保留多峰兴趣分布
"""

import numpy as np
from typing import List, Dict, Optional
import json


class VectorCloud:
    """
    用户兴趣向量云 - 不平均化，保留多个兴趣聚类
    """

    def __init__(self, embedding_dim: int = 1024):
        self.embedding_dim = embedding_dim
        self.vectors: List[np.ndarray] = []
        self.metadata: List[Dict] = []  # 存储来源文章信息
        self._vectors_mat: Optional[np.ndarray] = None  # Cache for matrix operations

    def _invalidate_cache(self):
        self._vectors_mat = None

    @property
    def vectors_matrix(self) -> np.ndarray:
        """Get or create the 2D numpy array of all vectors"""
        if self._vectors_mat is None:
            if not self.vectors:
                self._vectors_mat = np.empty((0, self.embedding_dim), dtype=np.float32)
            else:
                self._vectors_mat = np.vstack(self.vectors).astype(np.float32)
        return self._vectors_mat

    def get_time_weights(self, decay_rate: float = 0.05) -> np.ndarray:
        """
        计算时序衰减权重。假设列表末尾的向量是最新的兴趣。
        Args:
            decay_rate: 衰减系数
        Returns:
            np.ndarray: 权重数组，shape=(M,)
        """
        M = len(self.vectors)
        if M == 0:
            return np.array([], dtype=np.float32)
        # 权重公式: exp(-decay_rate * (M - 1 - i))
        # i 越大 (越新)，权重越接近 1.0
        indices = np.arange(M)
        weights = np.exp(-decay_rate * (M - 1 - indices))
        return weights.astype(np.float32)

    def add_vector(self, vector: np.ndarray, metadata: Optional[Dict] = None):
        """添加单个向量到云中"""
        if vector.shape[-1] != self.embedding_dim:
            raise ValueError(f"Expected dim {self.embedding_dim}, got {vector.shape[-1]}")

        # 归一化向量
        normalized = vector / (np.linalg.norm(vector) + 1e-8)
        self.vectors.append(normalized)
        self.metadata.append(metadata or {})
        self._invalidate_cache()

    def add_from_collection(self, embeddings: List[np.ndarray],
                           metadatas: Optional[List[Dict]] = None):
        """批量添加收藏夹内容"""
        metadatas = metadatas or [None] * len(embeddings)
        for emb, meta in zip(embeddings, metadatas):
            self.add_vector(emb, meta)

    def find_closest_in_cloud(self, query_vector: np.ndarray, top_k: int = 3) -> tuple:
        """
        计算查询向量与云中最接近的top_k个向量的平均相似度
        用于Item-to-Item匹配
        """
        if not self.vectors:
            return 0.0, []

        # 归一化查询向量
        query_normalized = query_vector / (np.linalg.norm(query_vector) + 1e-8)

        # Vectorized cosine similarity computation
        similarities = np.dot(self.vectors_matrix, query_normalized)

        if len(similarities) <= top_k:
            top_indices = np.argsort(similarities)[::-1].tolist()
        else:
            # Use argpartition for O(N) top_k extraction
            top_indices_unsorted = np.argpartition(similarities, -top_k)[-top_k:]
            top_similarities_unsorted = similarities[top_indices_unsorted]
            # Sort the top_k locally
            local_sort_idx = np.argsort(top_similarities_unsorted)[::-1]
            top_indices = top_indices_unsorted[local_sort_idx].tolist()

        avg_score = float(np.mean(similarities[top_indices]))

        return avg_score, top_indices

    def get_clusters(self, n_clusters: int = 3) -> List[Dict]:
        """
        使用简单聚类识别兴趣簇（用于可视化/分析）
        """
        if len(self.vectors) < n_clusters:
            n_clusters = len(self.vectors) or 1

        from sklearn.cluster import KMeans

        X = np.array(self.vectors)
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)

        clusters = []
        for i in range(n_clusters):
            cluster_vectors = X[labels == i]
            centroid = kmeans.cluster_centers_[i]
            clusters.append({
                "cluster_id": i,
                "size": len(cluster_vectors),
                "centroid": centroid,
                "members": [self.metadata[j] for j, label in enumerate(labels) if label == i]
            })

        return clusters

    def save(self, path: str):
        """保存向量云到磁盘"""
        data = {
            "embedding_dim": self.embedding_dim,
            "vectors": [v.tolist() for v in self.vectors],
            "metadata": self.metadata
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "VectorCloud":
        """从磁盘加载向量云"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cloud = cls(embedding_dim=data["embedding_dim"])
        cloud.vectors = [np.array(v) for v in data["vectors"]]
        cloud.metadata = data["metadata"]
        return cloud
