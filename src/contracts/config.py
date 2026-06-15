"""
PipelineConfig - 集中式运行时配置
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class PipelineConfig:
    """
    推荐管线运行时配置

    优先级:
      1. recommend() 中的 per-call 显式参数
      2. PipelineConfig 中的值
      3. 模块内部默认值
    """

    # Embedding
    embedding_dim: int = 1024
    embedder_type: str = "mock"
    embedder_kwargs: Dict = field(default_factory=dict)

    # LM Studio
    lm_studio_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen/qwen3.5-9b"
    embedding_model: str = "text-embedding-bge-large-zh-v1.5"
    reranker_model: str = "Qwen/Qwen2.5-7B-Instruct"

    # Profile
    max_profile_items: int = 50

    # Retrieval
    i2i_top_k: int = 3
    i2i_metric: str = "cosine"
    tag_positive_weight: float = 1.0
    tag_negative_weight: float = -2.0
    tag_hard_filter_negative: bool = True
    i2i_time_decay_rate: float = 0.05

    # Ranking
    top_k: int = 20
    mmr_lambda: float = 0.85
    preset: str = "balanced"
    custom_weights: Optional[Dict] = None
    min_score: Optional[float] = None

    # Reranker
    enable_reranker: bool = False
    rerank_strategy: str = "pointwise"
    rerank_top_n: int = 50
    rerank_weight: float = 0.50  # RERANK 在最终融合中的权重占比（启用 rerank 时生效）
    reranker_base_url: str = "https://api.siliconflow.cn/v1"
    reranker_api_key: str = field(default_factory=lambda: os.getenv("SILICONFLOW_API_KEY", ""))

    # Processing
    batch_size: int = 32
    cache_dir: Optional[str] = None
