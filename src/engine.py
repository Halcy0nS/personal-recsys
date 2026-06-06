"""
Personal RecSys - 主推荐引擎
整合画像、召回、精排三层架构

公共 API 保持不变：
  - build_profile_from_collection()
  - add_candidates() / embed_candidates()
  - recommend()
  - save() / load()

内部通过 PipelineOrchestrator 委托执行。
"""

import numpy as np
from typing import List, Dict, Optional, Union, Callable
from dataclasses import dataclass, field
import json
import hashlib
from pathlib import Path

from .profiling.implicit_profile import VectorCloud
from .profiling.explicit_profile import UserExplicitProfile
from .profiling.feedback_memory import FeedbackMemory
from .ranking.scorer import RankedItem
from .utils.embeddings import BaseEmbedder, get_embedder

from .contracts.config import PipelineConfig
from .contracts.types import ProfileContext
from .pipeline.orchestrator import PipelineOrchestrator


@dataclass
class CandidateItem:
    """候选内容"""
    item_id: str
    title: str
    content: str
    embedding: Optional[np.ndarray] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


@dataclass
class RecommendationResult:
    """推荐结果"""
    ranked_items: List[RankedItem]
    total_candidates: int
    filter_count: int
    profile_summary: Dict
    timing: Dict = field(default_factory=dict)


class PersonalRecSys:
    """
    个人推荐系统主引擎

    使用示例:
        recsys = PersonalRecSys()

        # 1. 构建用户画像
        recsys.build_profile_from_collection(collection_items)

        # 2. 添加候选内容
        recsys.add_candidates(candidate_items)

        # 3. 生成推荐
        results = recsys.recommend(top_k=20, preset="balanced")
    """

    def __init__(self,
                 embedder: Optional[BaseEmbedder] = None,
                 embedding_dim: int = 1024,
                 cache_dir: Optional[str] = None,
                 config: Optional[PipelineConfig] = None):
        """
        Args:
            embedder: Embedding模型，默认使用Mock
            embedding_dim: 向量维度
            cache_dir: 缓存目录路径
            config: 管线配置 (可选，新增参数)
        """
        self.embedder = embedder or get_embedder("mock", dim=embedding_dim)
        self.embedding_dim = embedding_dim
        self.cache_dir = Path(cache_dir) if cache_dir else None

        # 构建配置
        self._config = config or PipelineConfig(
            embedding_dim=embedding_dim,
            cache_dir=cache_dir,
        )

        # 编排器
        self._orchestrator = PipelineOrchestrator(
            config=self._config,
            embedder=self.embedder
        )

        # 用户画像
        self.vector_cloud: Optional[VectorCloud] = None
        self.explicit_profile: Optional[UserExplicitProfile] = None
        self.feedback_memory: FeedbackMemory = FeedbackMemory()
        self.collection_items: List[Dict] = []

        # 候选内容池
        self.candidates: Dict[str, CandidateItem] = {}
        self.candidate_embeddings: Dict[str, np.ndarray] = {}

        # 加载缓存
        if self.cache_dir:
            self._load_cache()

    def _load_cache(self):
        """从缓存加载画像数据"""
        if not self.cache_dir:
            return

        # 加载向量云
        vector_cloud_path = self.cache_dir / "vector_cloud.json"
        if vector_cloud_path.exists():
            try:
                self.vector_cloud = VectorCloud.load(str(vector_cloud_path))
                print(f"Loaded vector cloud from cache: {len(self.vector_cloud.vectors)} vectors")
            except Exception as e:
                print(f"Failed to load vector cloud: {e}")

        # 加载显式画像
        profile_path = self.cache_dir / "explicit_profile.json"
        if profile_path.exists():
            try:
                self.explicit_profile = UserExplicitProfile.load(str(profile_path))
                print(f"Loaded explicit profile from cache")
            except Exception as e:
                print(f"Failed to load explicit profile: {e}")

    def _save_cache(self):
        """保存画像数据到缓存"""
        if not self.cache_dir:
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 保存向量云
        if self.vector_cloud:
            vector_cloud_path = self.cache_dir / "vector_cloud.json"
            self.vector_cloud.save(str(vector_cloud_path))

        # 保存显式画像
        if self.explicit_profile:
            profile_path = self.cache_dir / "explicit_profile.json"
            self.explicit_profile.save(str(profile_path))

    def _get_candidate_embedding_cache_path(self) -> Optional[Path]:
        if not self.cache_dir:
            return None

        return self.cache_dir / "candidate_embeddings.npz"

    def _build_candidate_text(self, item: CandidateItem) -> str:
        text = f"{item.title}\n{item.content}".strip()
        return text[:2000]

    def _hash_candidate_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_candidate_embedding_cache(self) -> Dict[str, tuple[str, np.ndarray]]:
        """加载候选 embedding 缓存。"""
        cache_path = self._get_candidate_embedding_cache_path()
        if cache_path is None or not cache_path.exists():
            return {}

        try:
            with np.load(cache_path, allow_pickle=False) as data:
                item_ids = data["item_ids"]
                text_hashes = data["text_hashes"]
                embeddings = data["embeddings"]
        except Exception as e:
            print(f"Failed to load candidate embedding cache: {e}")
            return {}

        cache = {}
        for item_id, text_hash, embedding in zip(item_ids.tolist(), text_hashes.tolist(), embeddings):
            cache[str(item_id)] = (str(text_hash), np.array(embedding))

        return cache

    def _save_candidate_embedding_cache(self, cache: Dict[str, tuple[str, np.ndarray]]):
        """保存候选 embedding 缓存。"""
        cache_path = self._get_candidate_embedding_cache_path()
        if cache_path is None:
            return

        cache_path.parent.mkdir(parents=True, exist_ok=True)

        item_ids = np.array(list(cache.keys()), dtype=str)
        text_hashes = np.array([cache[item_id][0] for item_id in item_ids], dtype=str)

        if len(item_ids) > 0:
            embeddings = np.stack([
                np.asarray(cache[item_id][1], dtype=np.float32) for item_id in item_ids
            ])
        else:
            embeddings = np.empty((0, self.embedding_dim), dtype=np.float32)

        np.savez_compressed(
            cache_path,
            item_ids=item_ids,
            text_hashes=text_hashes,
            embeddings=embeddings,
        )

    def build_profile_from_collection(self,
                                      collection_items: List[Dict],
                                      llm_client=None,
                                      max_items: int = 50) -> Dict:
        """
        从收藏夹构建用户画像（双轨制）

        Args:
            collection_items: 收藏夹内容列表，每项包含title, content, url等
            llm_client: LLM客户端（用于提取显式标签，为None则跳过）
            max_items: 最大处理数量

        Returns:
            Dict: 画像摘要信息
        """
        if not collection_items:
            raise ValueError("Collection items cannot be empty")

        # 通过编排器的 ProfileBuilder 构建
        profile_ctx = self._orchestrator.build_profile(
            collection_items,
            llm_client=llm_client,
            max_items=max_items
        )

        # 同步到引擎状态
        self.vector_cloud = profile_ctx.vector_cloud
        self.explicit_profile = profile_ctx.explicit_profile
        self.collection_items = list(collection_items)

        # 保存缓存
        self._save_cache()

        return self.get_profile_summary()

    def add_candidates(self, items: List[CandidateItem]):
        """
        添加候选内容到内容池

        Args:
            items: 候选内容列表
        """
        for item in items:
            self.candidates[item.item_id] = item

            # 缓存embedding
            if item.embedding is not None:
                self.candidate_embeddings[item.item_id] = item.embedding

        print(f"Added {len(items)} candidates, total: {len(self.candidates)}")

    def embed_candidates(self, batch_size: int = 32):
        """为没有embedding的候选内容生成embedding"""
        embedding_cache = self._load_candidate_embedding_cache()
        items_to_embed = []
        texts = []
        cache_hits = 0

        for item in self.candidates.values():
            if item.item_id in self.candidate_embeddings:
                continue

            text = self._build_candidate_text(item)
            text_hash = self._hash_candidate_text(text)
            cached = embedding_cache.get(item.item_id)

            if cached and cached[0] == text_hash:
                embedding = np.asarray(cached[1], dtype=np.float32)
                self.candidate_embeddings[item.item_id] = embedding
                item.embedding = embedding
                cache_hits += 1
                continue

            items_to_embed.append((item, text_hash))
            texts.append(text)

        if not items_to_embed:
            if cache_hits:
                print(f"Embedded 0 candidates ({cache_hits} cache hits)")
            return

        embeddings = self.embedder.embed_batch(texts, batch_size=batch_size)

        for (item, text_hash), emb in zip(items_to_embed, embeddings):
            embedding = np.asarray(emb, dtype=np.float32)
            self.candidate_embeddings[item.item_id] = embedding
            item.embedding = embedding
            embedding_cache[item.item_id] = (text_hash, embedding)

        self._save_candidate_embedding_cache(embedding_cache)
        print(f"Embedded {len(items_to_embed)} candidates ({cache_hits} cache hits)")

    def recommend(self,
                  top_k: int = 20,
                  preset: str = "balanced",
                  custom_weights: Optional[Dict] = None,
                  min_score: Optional[float] = None) -> RecommendationResult:
        """
        生成推荐

        Args:
            top_k: 返回的推荐数量
            preset: 评分预设模式
            custom_weights: 自定义权重
            min_score: 最低分数阈值

        Returns:
            RecommendationResult: 推荐结果
        """
        if not self.candidates:
            raise ValueError("No candidates available. Call add_candidates() first.")

        if not self.vector_cloud or not self.vector_cloud.vectors:
            raise ValueError("User profile not built. Call build_profile_from_collection() first.")

        # 构建 ProfileContext
        profile_ctx = ProfileContext(
            vector_cloud=self.vector_cloud,
            explicit_profile=self.explicit_profile,
            feedback_memory=self.feedback_memory,
            summary=self.get_profile_summary()
        )

        # 通过编排器执行推荐
        result = self._orchestrator.recommend(
            candidates=self.candidates,
            profile_ctx=profile_ctx,
            top_k=top_k,
            preset=preset,
            custom_weights=custom_weights,
            min_score=min_score,
            collection_items=self.collection_items,
        )

        return RecommendationResult(
            ranked_items=result["ranked_items"],
            total_candidates=result["total_candidates"],
            filter_count=result["filter_count"],
            profile_summary=result["profile_summary"],
            timing=result["timing"]
        )

    def get_profile_summary(self) -> Dict:
        """获取画像摘要"""
        return self._orchestrator.profile_builder.summarize(
            self.vector_cloud, self.explicit_profile
        )

    def save(self, path: str):
        """保存引擎状态"""
        save_dir = Path(path)
        save_dir.mkdir(parents=True, exist_ok=True)

        # 保存画像
        if self.vector_cloud:
            self.vector_cloud.save(str(save_dir / "vector_cloud.json"))

        if self.explicit_profile:
            self.explicit_profile.save(str(save_dir / "explicit_profile.json"))

        # 保存元数据
        meta = {
            "candidate_count": len(self.candidates),
            "embedding_dim": self.embedding_dim
        }
        with open(save_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, path: str, embedder: Optional[BaseEmbedder] = None) -> "PersonalRecSys":
        """加载引擎状态"""
        load_dir = Path(path)

        # 读取元数据
        with open(load_dir / "meta.json", "r", encoding="utf-8") as f:
            meta = json.load(f)

        # 创建实例
        instance = cls(
            embedder=embedder,
            embedding_dim=meta.get("embedding_dim", 1024)
        )

        # 加载向量云
        vector_cloud_path = load_dir / "vector_cloud.json"
        if vector_cloud_path.exists():
            instance.vector_cloud = VectorCloud.load(str(vector_cloud_path))

        # 加载显式画像
        profile_path = load_dir / "explicit_profile.json"
        if profile_path.exists():
            instance.explicit_profile = UserExplicitProfile.load(str(profile_path))

        return instance
