"""
PipelineOrchestrator - 组合 ProfileBuilder → RetrievalManager → Reranker → Ranker
"""

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from ..contracts.config import PipelineConfig
from ..contracts.types import ProfileContext, ScoreMap
from ..services.profile_builder import DefaultProfileBuilder
from ..services.retrieval_manager import RetrievalManager, I2IRetriever, TagRetriever, FeedbackRetriever
from ..services.ranker_adapter import DefaultRanker
from ..services.reranker import LLMReranker, CrossEncoderReranker
from ..ranking.scorer import ConfigurableScorer, ScoreComponent
from ..utils.embeddings import BaseEmbedder
from ..utils.deepseek_client import DeepSeekClient


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
        self.fine_embedder = None

        # 组装子组件
        self.profile_builder = DefaultProfileBuilder(
            embedder=embedder,
            embedding_dim=config.embedding_dim
        )

        from ..services.retrieval_manager import ExplicitSemanticRetriever
        self.retrieval_manager = RetrievalManager([
            I2IRetriever(
                top_k=config.i2i_top_k,
                metric=config.i2i_metric,
                time_decay_rate=config.i2i_time_decay_rate
            ),
            TagRetriever(
                positive_weight=config.tag_positive_weight,
                negative_weight=config.tag_negative_weight,
                hard_filter_negative=config.tag_hard_filter_negative
            ),
            ExplicitSemanticRetriever(
                embedder=embedder
            ),
            FeedbackRetriever()
        ])

        self.ranker = DefaultRanker(
            preset=config.preset,
            custom_weights=config.custom_weights
        )

        # DeepSeek Client
        self.deepseek_client = None
        if self.config.enable_knowledge_capsule and self.config.deepseek_api_key:
            self.deepseek_client = DeepSeekClient(
                api_key=self.config.deepseek_api_key,
                base_url=self.config.deepseek_base_url,
                model=self.config.deepseek_model
            )

        # Reranker (可选)
        self._reranker = None
        if self.config.enable_reranker:
            self._reranker = self._build_reranker()

    def _build_reranker(self):
        """按配置创建 reranker。"""
        if self.config.rerank_strategy == "cross_encoder":
            return CrossEncoderReranker(
                base_url=self.config.reranker_base_url,
                model=self.config.reranker_model,
                rerank_top_n=self.config.rerank_top_n
            )
        elif self.config.rerank_strategy == "pointwise":
            return LLMReranker(
                model=self.config.reranker_model,
                base_url=self.config.reranker_base_url,
                api_key=getattr(self.config, 'reranker_api_key', ''),
                rerank_top_n=self.config.rerank_top_n,
                strategy=self.config.rerank_strategy,
            )
        else:
            raise ValueError(f"Unsupported rerank strategy: {self.config.rerank_strategy}")

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

        vector_cloud_fine = None
        if getattr(self.config, 'enable_dual_embedder', False) and hasattr(self, 'fine_embedder') and self.fine_embedder:
            from ..services.profile_builder import DefaultProfileBuilder
            fine_profile_builder = DefaultProfileBuilder(
                embedder=self.fine_embedder,
                embedding_dim=self.config.fine_embedding_dim
            )
            vector_cloud_fine = fine_profile_builder.build_implicit(
                collection_items, max_items=max_items
            )

        explicit_profile = None
        if self.config.enable_knowledge_capsule:
            # 如果启用了胶囊模式，优先使用 deepseek client
            actual_llm_client = self.deepseek_client or llm_client
            explicit_profile = self.profile_builder.build_explicit(
                collection_items, llm_client=actual_llm_client, max_items=max_items
            )

        summary = self.profile_builder.summarize(vector_cloud, explicit_profile)

        return ProfileContext(
            vector_cloud=vector_cloud,
            explicit_profile=explicit_profile,
            summary=summary,
            vector_cloud_fine=vector_cloud_fine
        )


    def recommend(self, candidates: Dict,
                  profile_ctx: ProfileContext,
                  top_k: int = None,
                  preset: str = None,
                  custom_weights: Optional[Dict] = None,
                  min_score: Optional[float] = None,
                  collection_items: List[Dict] = None,
                  recsys_instance: Optional[object] = None) -> Dict:
        """
        执行完整推荐流程

        Args:
            collection_items: 用户收藏列表 (为 reranker 提供 few-shot 示例)
            recsys_instance: 父引擎实例，用于生成/缓存 fine embeddings

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
            top_k=min(len(candidates), self.config.rerank_top_n * 2),  # 仅排序 reranker 所需数量
            min_score=None
        )
        timing["coarse_ranking"] = time.time() - t0

        coarse_ranked_ids = [item.item_id for item in coarse_ranked]

        # Step 2.5: Dual-Model Gemini Vector Fine Match
        if self.config.enable_dual_embedder and getattr(profile_ctx, 'vector_cloud_fine', None) and hasattr(self, 'fine_embedder') and self.fine_embedder:
            if recsys_instance and hasattr(recsys_instance, 'embed_candidates_fine'):
                recsys_instance.embed_candidates_fine(coarse_ranked_ids)
            self._update_scores_with_fine_embeddings(coarse_ranked_ids, candidates, score_map, profile_ctx)

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
                logger.warning("Rerank stage failed, fallback to baseline ranking: %s", e)
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

        # 如果有 rerank 分数，将 RERANK 权重合并到用户选择的权重中
        if rerank_results:
            # 获取用户的基础权重（优先级：per-call custom_weights > config.custom_weights > preset）
            base_weights = dict(custom_weights) if custom_weights else None
            if base_weights is None:
                base_weights = dict(self.config.custom_weights) if self.config.custom_weights else None
            if base_weights is None:
                base_weights = dict(ConfigurableScorer.PRESETS[preset]["weights"])

            # 将 RERANK 以配置权重插入，其余权重按比例缩放
            rerank_w = self.config.rerank_weight
            merged_weights = {}
            scale = 1.0 - rerank_w
            for comp, w in base_weights.items():
                merged_weights[comp] = w * scale
            merged_weights[ScoreComponent.RERANK] = rerank_w

            final_ranker = DefaultRanker(
                preset=preset,
                custom_weights=merged_weights
            )
        else:
            final_ranker = DefaultRanker(
                preset=preset,
                custom_weights=custom_weights or self.config.custom_weights
            )

        ranked_items = final_ranker.rank(
            score_map,
            top_k=top_k,
            min_score=min_score,
            candidates=candidates,
            mmr_lambda=self.config.mmr_lambda
        )
        
        # 将 Reranker 的理由等信息注入 RankedItem (如果原有点对点 reranker 存在的话)
        if rerank_results and self.config.rerank_strategy == "pointwise":
            rr_map = {rr.item_id: rr for rr in rerank_results}
            for item in ranked_items:
                if item.item_id in rr_map:
                    item.reasoning = rr_map[item.item_id].reasoning

        # 如果是知识胶囊模式，则单独调用 DeepSeek 生成更高质量的推荐理由（覆盖原有理由）
        if self.config.enable_knowledge_capsule and self.deepseek_client:
            t_reason = time.time()
            top_items = [
                {
                    "item_id": it.item_id,
                    "title": candidates[it.item_id].title,
                    "content": candidates[it.item_id].content
                }
                for it in ranked_items[:top_k]
            ]
            reasons = self.deepseek_client.generate_reasons_batch(profile_ctx.summary, top_items)
            for it in ranked_items:
                if it.item_id in reasons:
                    it.reasoning = reasons[it.item_id]
            timing["reason_generation"] = time.time() - t_reason
                    
        timing["final_ranking"] = time.time() - t0

        # 统计 tag 分数为 0 的 item（可能原因：hard-filter by negative tags，或完全无标签匹配）
        # 注意：当无显式画像时 tag 统一回退为 0.5，此时 filter_count 始终为 0
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

    def _update_scores_with_fine_embeddings(self, 
                                            item_ids: List[str], 
                                            candidates: Dict, 
                                            score_map: ScoreMap, 
                                            profile_ctx: ProfileContext):
        """在精排阶段利用高精细的 fine embeddings 重新计算 I2I 相似度和 Explicit Semantic 相似度"""
        import numpy as np
        from ..retrieval.i2i_matcher import I2IMatcher
        from ..ranking.scorer import ScoreComponent

        fine_matcher = I2IMatcher(
            top_k=self.config.i2i_top_k,
            metric=self.config.i2i_metric,
            time_decay_rate=self.config.i2i_time_decay_rate
        )

        fml = profile_ctx.feedback_memory
        neg_mat = np.empty((0, self.config.fine_embedding_dim), dtype=np.float32)
        dup_mat = np.empty((0, self.config.fine_embedding_dim), dtype=np.float32)
        if fml:
            neg_mat = fml.get_negative_vectors_matrix(self.config.fine_embedding_dim)
            dup_mat = fml.get_duplicate_vectors_matrix(self.config.fine_embedding_dim)

        for item_id in item_ids:
            candidate = candidates.get(item_id)
            if not candidate or candidate.embedding_fine is None:
                continue

            # 1. 重新计算 I2I 相似度 (配合 feedback 负反馈及重复过滤)
            avg_score, top_indices = profile_ctx.vector_cloud_fine.find_closest_in_cloud(
                candidate.embedding_fine,
                top_k=self.config.i2i_top_k
            )

            if top_indices:
                time_weights = profile_ctx.vector_cloud_fine.get_time_weights(self.config.i2i_time_decay_rate)
                weighted_sum = sum(
                    float(np.dot(
                        candidate.embedding_fine / (np.linalg.norm(candidate.embedding_fine) + 1e-8),
                        profile_ctx.vector_cloud_fine.vectors[idx]
                    )) * time_weights[idx]
                    for idx in top_indices
                )
                weight_total = sum(time_weights[idx] for idx in top_indices)
                avg_score = weighted_sum / weight_total if weight_total > 0 else 0.0

            s_neg = 0.0
            s_dup = 0.0
            cand_norm = candidate.embedding_fine / (np.linalg.norm(candidate.embedding_fine) + 1e-8)

            if neg_mat.shape[0] > 0:
                neg_mat_norm = neg_mat / (np.linalg.norm(neg_mat, axis=1, keepdims=True) + 1e-8)
                sim_neg = np.dot(cand_norm, neg_mat_norm.T)
                s_neg = float(np.mean(np.partition(sim_neg, -min(self.config.i2i_top_k, len(sim_neg)))[-min(self.config.i2i_top_k, len(sim_neg)):]))

            if dup_mat.shape[0] > 0:
                dup_mat_norm = dup_mat / (np.linalg.norm(dup_mat, axis=1, keepdims=True) + 1e-8)
                sim_dup = np.dot(cand_norm, dup_mat_norm.T)
                s_dup = float(np.max(sim_dup))

            if s_dup > 0.95:  # duplicate threshold
                i2i_score = -999.0
            else:
                if s_neg > 0.80:  # negative soft threshold
                    penalty = min(1.5 * s_neg, 0.5)  # gamma * s_neg, max_penalty
                    i2i_score = avg_score - penalty
                else:
                    i2i_score = avg_score

            score_map[item_id]["i2i"] = i2i_score

            # 2. 重新计算 Explicit Semantic 相似度
            explicit = profile_ctx.explicit_profile
            if explicit and explicit.core_topics:
                intent_text = ", ".join(explicit.core_topics)
                try:
                    intent_vector = self.fine_embedder.embed_batch([intent_text])[0]
                    intent_norm = np.linalg.norm(intent_vector)
                    if intent_norm > 0:
                        intent_vector = intent_vector / intent_norm
                        sim = float(np.dot(cand_norm, intent_vector))
                        score_map[item_id]["semantic"] = max(0.0, sim)
                except Exception:
                    pass

