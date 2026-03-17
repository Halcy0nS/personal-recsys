"""
抽象接口定义 - ProfileBuilder / Retriever / Ranker
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .types import ProfileContext, ScoreMap


class BaseProfileBuilder(ABC):
    """画像构建器接口"""

    @abstractmethod
    def build_implicit(self, collection_items: List[Dict],
                       max_items: int = 50) -> object:
        """构建隐式画像 (VectorCloud)"""
        ...

    @abstractmethod
    def build_explicit(self, collection_items: List[Dict],
                       llm_client=None,
                       max_items: int = 50) -> Optional[object]:
        """构建显式画像 (UserExplicitProfile | None)"""
        ...

    @abstractmethod
    def summarize(self, vector_cloud, explicit_profile) -> Dict:
        """生成画像摘要"""
        ...


class BaseRetriever(ABC):
    """召回器接口"""

    @abstractmethod
    def name(self) -> str:
        """召回器名称 (用作 ScoreMap 中的 component key)"""
        ...

    @abstractmethod
    def score(self, candidates: Dict, profile_ctx: ProfileContext) -> Dict[str, float]:
        """
        计算候选分数

        Args:
            candidates: {item_id: CandidateItem}
            profile_ctx: 画像上下文

        Returns:
            {item_id: score}
        """
        ...


class BaseRanker(ABC):
    """精排器接口"""

    @abstractmethod
    def rank(self, score_map: ScoreMap,
             item_metadata: Optional[Dict] = None,
             top_k: int = 20,
             min_score: Optional[float] = None) -> list:
        """
        精排融合

        Args:
            score_map: {item_id: {component -> score}}
            item_metadata: 额外元数据
            top_k: 返回数量
            min_score: 最低分阈值

        Returns:
            List[RankedItem]
        """
        ...
