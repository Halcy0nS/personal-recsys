import json
import os
import logging
from typing import Dict, List, Any
import numpy as np

logger = logging.getLogger(__name__)

class FeedbackMemory:
    """
    多维反馈记忆层 (Feedback Memory Layer)
    
    记录用户长期的显式偏好，包含：
    - 主题偏好向量 (Positive / Negative)
    - 来源偏好 (Source / Author)
    - 属性偏好 (Facet: depth, style)
    - 查重记忆 (Duplicate Memory Vectors)
    """
    
    def __init__(self, storage_path: str = "data/feedback_memory.json"):
        self.storage_path = storage_path
        self.positive_vectors: Dict[str, List[float]] = {}
        self.negative_vectors: Dict[str, List[float]] = {}
        self.duplicate_vectors: Dict[str, List[float]] = {}
        
        self.source_prefs: Dict[str, int] = {}
        self.author_prefs: Dict[str, int] = {}
        self.facet_prefs: Dict[str, int] = {}
        
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.positive_vectors = data.get("positive_vectors", {})
                self.negative_vectors = data.get("negative_vectors", {})
                self.duplicate_vectors = data.get("duplicate_vectors", {})
                self.source_prefs = data.get("source_prefs", {})
                self.author_prefs = data.get("author_prefs", {})
                self.facet_prefs = data.get("facet_prefs", {})
                logger.info(f"FeedbackMemory loaded from {self.storage_path}")
            except Exception as e:
                logger.error(f"Failed to load FeedbackMemory: {e}")
                
    def save(self):
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        data = {
            "positive_vectors": self.positive_vectors,
            "negative_vectors": self.negative_vectors,
            "duplicate_vectors": self.duplicate_vectors,
            "source_prefs": self.source_prefs,
            "author_prefs": self.author_prefs,
            "facet_prefs": self.facet_prefs
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
    def _normalize(self, vec: np.ndarray) -> List[float]:
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()
        
    def add_positive(self, item_id: str, vector: np.ndarray, source: str = None, author: str = None, facets: List[str] = None):
        """用户点击 👍 喜欢"""
        self.positive_vectors[item_id] = self._normalize(vector)
        if source:
            self.source_prefs[source] = self.source_prefs.get(source, 0) + 1
        if author:
            self.author_prefs[author] = self.author_prefs.get(author, 0) + 1
        if facets:
            for facet in facets:
                self.facet_prefs[facet] = self.facet_prefs.get(facet, 0) + 1
        self.save()

    def add_negative_topic(self, item_id: str, vector: np.ndarray, facets: List[str] = None):
        """用户点击 👎 主题不相关"""
        self.negative_vectors[item_id] = self._normalize(vector)
        if facets:
            for facet in facets:
                # 主题不相关时，我们也微量扣除涉及到的 facet 分数
                self.facet_prefs[facet] = self.facet_prefs.get(facet, 0) - 1
        self.save()
        
    def add_negative_source(self, source: str = None, author: str = None):
        """用户点击 👎 来源/作者太差 (不进向量云)"""
        if source:
            self.source_prefs[source] = self.source_prefs.get(source, 0) - 2
        if author:
            self.author_prefs[author] = self.author_prefs.get(author, 0) - 2
        self.save()
        
    def add_negative_facet(self, facets: List[str]):
        """用户点击 👎 太浅/太水 (仅针对属性惩罚)"""
        for facet in facets:
            self.facet_prefs[facet] = self.facet_prefs.get(facet, 0) - 2
        self.save()
        
    def add_duplicate(self, item_id: str, vector: np.ndarray):
        """用户点击 👎 重复看过"""
        self.duplicate_vectors[item_id] = self._normalize(vector)
        self.save()

    # --- 查询接口 ---
    def get_source_score(self, source: str) -> int:
        return self.source_prefs.get(source, 0)
        
    def get_author_score(self, author: str) -> int:
        return self.author_prefs.get(author, 0)
        
    def get_facet_score(self, facet: str) -> int:
        return self.facet_prefs.get(facet, 0)
        
    def get_negative_vectors_matrix(self) -> np.ndarray:
        if not self.negative_vectors:
            return np.empty((0, 0))
        return np.array(list(self.negative_vectors.values()), dtype=np.float32)
        
    def get_duplicate_vectors_matrix(self) -> np.ndarray:
        if not self.duplicate_vectors:
            return np.empty((0, 0))
        return np.array(list(self.duplicate_vectors.values()), dtype=np.float32)
