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

    def add_vector(self, vector: np.ndarray, metadata: Optional[Dict] = None):
        """添加单个向量到云中"""
        if vector.shape[0] != self.embedding_dim:
            raise ValueError(f"Expected dim {self.embedding_dim}, got {vector.shape[0]}")

        # 归一化向量
        normalized = vector / (np.linalg.norm(vector) + 1e-8)
        self.vectors.append(normalized)
        self.metadata.append(metadata or {})

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

        # 计算与云中所有向量的余弦相似度
        similarities = []
        for i, vec in enumerate(self.vectors):
            sim = np.dot(query_normalized, vec)
            similarities.append((sim, i))

        # 取top_k
        similarities.sort(reverse=True)
        top_similarities = similarities[:top_k]

        avg_score = np.mean([sim for sim, _ in top_similarities])
        top_indices = [idx for _, idx in top_similarities]

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
