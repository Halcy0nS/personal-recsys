"""
PipelineOrchestrator - 组合 ProfileBuilder → RetrievalManager → Reranker → Ranker
"""

import time
from typing import Dict, List, Optional

from ..contracts.config import PipelineConfig
from ..contracts.types import ProfileContext, ScoreMap
from ..services.profile_builder import DefaultProfileBuilder
from ..services.retrieval_manager import RetrievalManager, I2IRetriever, TagRetriever
from ..services.ranker_adapter import DefaultRanker
from ..services.reranker import LLMReranker
from ..ranking.scorer import ScoreComponent
from ..utils.embeddings import BaseEmbedder


class PipelineOrchestrator:
    """
    管线编排器 - 执行完整的推荐流程

    流水线:
      ProfileBuilder → RetrievalManager(粗排) → LLMReranker(精排) → Ranker(融合)

    职责:
      - 组装 ProfileBuilder / Retrievers / Reranker / Ranker
      - 执行阶段顺序和计时收集
      - 不持有业务状态（状态由 PersonalRecSys 持有）
    """

    def __init__(self, config: PipelineConfig, embedder: BaseEmbedder):
        self.config = config
        self.embedder = embedder

        # 组装子组件
        self.profile_builder = DefaultProfileBuilder(
            embedder=embedder,
            embedding_dim=config.embedding_dim
        )

        self.retrieval_manager = RetrievalManager([
            I2IRetriever(
                top_k=config.i2i_top_k,
                metric=config.i2i_metric
            ),
            TagRetriever(
                positive_weight=config.tag_positive_weight,
                negative_weight=config.tag_negative_weight,
                hard_filter_negative=config.tag_hard_filter_negative
            ),
        ])

        self.ranker = DefaultRanker(
            preset=config.preset,
            custom_weights=config.custom_weights
        )

        # Reranker (可选)
        self._reranker: Optional[LLMReranker] = None
        if self.config.enable_reranker:
            self._reranker = self._build_reranker()

    def _build_reranker(self) -> LLMReranker:
        """按配置创建 reranker。"""
        if self.config.rerank_strategy != "pointwise":
            raise ValueError(f"Unsupported rerank strategy: {self.config.rerank_strategy}")

        return LLMReranker(
            model=self.config.reranker_model,
            base_url=self.config.lm_studio_base_url,
            rerank_top_n=self.config.rerank_top_n,
            strategy=self.config.rerank_strategy,
        )

    def set_reranker(self, reranker: LLMReranker):
        """设置 LLM 重排器"""
        self._reranker = reranker

    def build_profile(self, collection_items: List[Dict],
                      llm_client=None,
                      max_items: int = None) -> ProfileContext:
        """构建画像上下文"""
        max_items = max_items or self.config.max_profile_items

        vector_cloud = self.profile_builder.build_implicit(
            collection_items, max_items=max_items
        )

        explicit_profile = self.profile_builder.build_explicit(
            collection_items, llm_client=llm_client, max_items=max_items
        )

        summary = self.profile_builder.summarize(vector_cloud, explicit_profile)

        return ProfileContext(
            vector_cloud=vector_cloud,
            explicit_profile=explicit_profile,
            summary=summary
        )

    def recommend(self, candidates: Dict,
                  profile_ctx: ProfileContext,
                  top_k: int = None,
                  preset: str = None,
                  custom_weights: Optional[Dict] = None,
                  min_score: Optional[float] = None,
                  collection_items: List[Dict] = None) -> Dict:
        """
        执行完整推荐流程

        Args:
            collection_items: 用户收藏列表 (为 reranker 提供 few-shot 示例)

        Returns:
            Dict with ranked_items, total_candidates, filter_count, profile_summary, timing
        """
        timing = {}
        top_k = top_k or self.config.top_k
        preset = preset or self.config.preset

        # Step 1: 粗召回
        t0 = time.time()
        score_map = self.retrieval_manager.retrieve_all(
            candidates, profile_ctx
        )
        timing["retrieval"] = time.time() - t0

        # Step 2: 粗排 (按预设权重融合初排，确定送入 rerank 的候选顺序)
        t0 = time.time()
        coarse_ranker = DefaultRanker(
            preset=preset,
            custom_weights=custom_weights or self.config.custom_weights
        )
        coarse_ranked = coarse_ranker.rank(
            score_map,
            top_k=len(candidates),  # 全量排序以确定 rerank 顺序
            min_score=None
        )
        timing["coarse_ranking"] = time.time() - t0

        coarse_ranked_ids = [item.item_id for item in coarse_ranked]

        # Step 3: LLM Rerank (可选)
        rerank_results = None
        if self._reranker and profile_ctx.explicit_profile:
            t0 = time.time()
            ep = profile_ctx.explicit_profile
            exemplar_titles = []
            if collection_items:
                exemplar_titles = [
                    item.get("title", "") for item in collection_items[:10]
                    if item.get("title")
                ]

            try:
                rerank_results = self._reranker.rerank(
                    candidates=candidates,
                    profile_topics=getattr(ep, 'core_topics', []),
                    profile_styles=getattr(ep, 'writing_style', []),
                    profile_negatives=getattr(ep, 'negative_tags', []),
                    exemplar_titles=exemplar_titles,
                    coarse_ranked_ids=coarse_ranked_ids
                )
            except Exception as e:
                print(f"  Rerank stage failed, fallback to baseline ranking: {e}")
                rerank_results = None
            finally:
                timing["rerank"] = time.time() - t0

            # 将 rerank 分数注入 score_map
            if rerank_results:
                for rr in rerank_results:
                    if rr.item_id in score_map:
                        # 归一化到 0-1 (原始分数 0-10)
                        score_map[rr.item_id]["rerank"] = rr.relevance_score / 10.0

        # Step 4: 最终精排 (融合所有分数)
        t0 = time.time()

        # 如果有 rerank 分数，调整权重分配
        if rerank_results:
            rerank_weights = {
                ScoreComponent.I2I: 0.25,
                ScoreComponent.TAG: 0.15,
                ScoreComponent.POPULARITY: 0.10,
                ScoreComponent.RERANK: 0.50  # rerank 分数占主导
            }
            final_ranker = DefaultRanker(
                preset=preset,
                custom_weights=rerank_weights
            )
        else:
            final_ranker = DefaultRanker(
                preset=preset,
                custom_weights=custom_weights or self.config.custom_weights
            )

        ranked_items = final_ranker.rank(
            score_map,
            top_k=top_k,
            min_score=min_score
        )
        timing["final_ranking"] = time.time() - t0

        # 计算被过滤的数量
        filter_count = sum(
            1 for scores in score_map.values()
            if scores.get("tag", 0.0) == 0.0
        )

        return {
            "ranked_items": ranked_items,
            "total_candidates": len(candidates),
            "filter_count": filter_count,
            "profile_summary": profile_ctx.summary,
            "timing": timing,
            "rerank_details": rerank_results,
        }
