"""
DefaultProfileBuilder - 封装现有画像构建逻辑
"""

from typing import Dict, List, Optional

from ..contracts.interfaces import BaseProfileBuilder
from ..profiling.implicit_profile import VectorCloud
from ..profiling.explicit_profile import UserExplicitProfile, ProfileExtractor
from ..utils.embeddings import BaseEmbedder


class DefaultProfileBuilder(BaseProfileBuilder):
    """默认画像构建器 - 封装现有的向量云 + LLM 提取逻辑"""

    def __init__(self, embedder: BaseEmbedder, embedding_dim: int = 1024):
        self.embedder = embedder
        self.embedding_dim = embedding_dim

    def build_implicit(self, collection_items: List[Dict],
                       max_items: int = 50) -> VectorCloud:
        """构建隐式画像 - 向量云"""
        vector_cloud = VectorCloud(embedding_dim=self.embedding_dim)

        texts = []
        metadatas = []

        for item in collection_items[:max_items]:
            title = item.get("title", "")
            content = item.get("content", "")[:1000]
            text = f"{title}\n{content}".strip()

            if text:
                texts.append(text)
                metadatas.append({
                    "title": title,
                    "url": item.get("url", ""),
                    "source": item.get("source", "")
                })

        if not texts:
            return vector_cloud

        embeddings = self.embedder.embed_batch(texts)
        vector_cloud.add_from_collection(embeddings, metadatas)

        print(f"Built implicit profile: {len(vector_cloud.vectors)} vectors")
        return vector_cloud

    def build_explicit(self, collection_items: List[Dict],
                       llm_client=None,
                       max_items: int = 50) -> Optional[UserExplicitProfile]:
        """构建显式画像 - LLM 标签"""
        if llm_client is None:
            return None

        extractor = ProfileExtractor(llm_client=llm_client)
        try:
            profile = extractor.extract(
                collection_items,
                max_items=min(30, len(collection_items[:max_items]))
            )
            print(f"Built explicit profile: {len(profile.core_topics)} core topics")
            return profile
        except Exception as e:
            print(f"Failed to build explicit profile: {e}")
            return None

    def summarize(self, vector_cloud, explicit_profile) -> Dict:
        """生成画像摘要"""
        summary = {
            "has_implicit_profile": vector_cloud is not None and len(vector_cloud.vectors) > 0,
            "has_explicit_profile": explicit_profile is not None,
        }

        if vector_cloud:
            summary["vector_count"] = len(vector_cloud.vectors)

        if explicit_profile:
            summary["core_topics"] = explicit_profile.core_topics[:10]
            summary["writing_style"] = explicit_profile.writing_style[:5]
            summary["negative_tags"] = explicit_profile.negative_tags[:5]

        return summary
