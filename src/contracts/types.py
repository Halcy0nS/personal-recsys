"""
契约类型定义 - 阶段间传递的规范化数据结构
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field

# 阶段间统一分数容器
# item_id -> {component_name -> score}
ScoreMap = Dict[str, Dict[str, float]]


@dataclass
class ProfileContext:
    """画像上下文 - 在阶段间传递的统一画像表示"""
    vector_cloud: object = None  # VectorCloud, 避免强耦合
    explicit_profile: object = None  # UserExplicitProfile
    feedback_memory: object = None # FeedbackMemory
    summary: Dict = field(default_factory=dict)
    vector_cloud_fine: Optional[object] = None  # 高精细向量云



@dataclass
class RecommendRequest:
    """推荐请求契约（预定义类型，供未来 API / 远程调用使用）"""
    top_k: int = 20
    preset: str = "balanced"
    custom_weights: Optional[Dict] = None
    min_score: Optional[float] = None


@dataclass
class RecommendResponse:
    """推荐响应契约（预定义类型，供未来 API / 远程调用使用）"""
    ranked_items: list = field(default_factory=list)  # List[RankedItem]
    total_candidates: int = 0
    filter_count: int = 0
    profile_summary: Dict = field(default_factory=dict)
    timing: Dict = field(default_factory=dict)
