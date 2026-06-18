"""
DefaultRanker - 封装现有精排逻辑
"""

import logging
from typing import Dict, List, Optional

from ..contracts.interfaces import BaseRanker
from ..contracts.types import ScoreMap
from ..ranking.scorer import (
    ConfigurableScorer, WeightedScorer, ScoreComponent, RankedItem
)

logger = logging.getLogger(__name__)


class DefaultRanker(BaseRanker):
    """默认精排器 - 封装 ConfigurableScorer + WeightedScorer"""

    def __init__(self, preset: str = "balanced",
                 custom_weights: Optional[Dict] = None):
        self.preset = preset
        self.custom_weights = self._normalize_weights(custom_weights)

    def _normalize_weights(self, custom_weights: Optional[Dict]) -> Optional[Dict]:
        """允许调用方使用字符串或 ScoreComponent 作为权重 key。"""
        if custom_weights is None:
            return None

        normalized = {}
        for component, weight in custom_weights.items():
            if isinstance(component, ScoreComponent):
                normalized[component] = weight
                continue

            try:
                normalized[ScoreComponent(component)] = weight
            except ValueError:
                raise ValueError(f"Unknown score component in custom_weights: {component}")

        return normalized

    def rank(self, score_map: ScoreMap,
             top_k: int = 20,
             min_score: Optional[float] = None,
             candidates: Optional[Dict] = None,
             mmr_lambda: float = 0.85) -> List[RankedItem]:
        """精排融合并支持 MMR 多样性打散"""
        import numpy as np

        # 将字符串 key 转换回 ScoreComponent enum
        item_scores = {}
        for item_id, component_scores in score_map.items():
            enum_scores = {}
            for comp_name, score in component_scores.items():
                try:
                    comp = ScoreComponent(comp_name)
                    enum_scores[comp] = score
                except ValueError:
                    logger.debug("Unknown score component in score_map: %s", comp_name)
            item_scores[item_id] = enum_scores

        # 使用 ConfigurableScorer
        config_scorer = ConfigurableScorer(
            preset=self.preset,
            custom_weights=self.custom_weights
        )
        scorer = config_scorer.get_scorer()

        ranked_items = scorer.calculate(item_scores)

        # 应用最低分数阈值
        if min_score is not None:
            ranked_items = [item for item in ranked_items if item.final_score >= min_score]

        # 如果未提供候选集或 MMR 被禁用，退化为普通截断
        if not candidates or mmr_lambda >= 1.0 or not ranked_items:
            return ranked_items[:top_k]

        # ========== MMR 多样性打散逻辑 ==========
        # 提取候选 embedding，如果没有 embedding，使用全零向量
        item_embeddings = {}
        for item in ranked_items:
            cand = candidates.get(item.item_id)
            emb = None
            if cand:
                if getattr(cand, "embedding_fine", None) is not None:
                    emb = cand.embedding_fine / (np.linalg.norm(cand.embedding_fine) + 1e-8)
                elif cand.embedding is not None:
                    emb = cand.embedding / (np.linalg.norm(cand.embedding) + 1e-8)
            item_embeddings[item.item_id] = emb


        selected = []
        unselected = list(ranked_items)
        
        while len(selected) < top_k and unselected:
            if not selected:
                # 选出第一名
                best_idx = 0
                selected.append(unselected.pop(best_idx))
                continue

            # 为 unselected 计算 MMR 分数
            best_mmr_score = -float('inf')
            best_idx = -1
            
            # 把 selected 里的 embedding 拿出来
            sel_embs = [item_embeddings[sel.item_id] for sel in selected if item_embeddings[sel.item_id] is not None]
            
            for i, cand in enumerate(unselected):
                cand_emb = item_embeddings[cand.item_id]
                max_sim = 0.0
                if cand_emb is not None and sel_embs:
                    # cand_emb 和所有已选择的内容做相似度，取最大
                    sims = [float(np.dot(cand_emb, sel_emb)) for sel_emb in sel_embs]
                    max_sim = max(sims)
                    
                # MMR formula: lambda * Relevance - (1 - lambda) * Max_Similarity
                mmr_score = mmr_lambda * cand.final_score - (1.0 - mmr_lambda) * max_sim
                
                if mmr_score > best_mmr_score:
                    best_mmr_score = mmr_score
                    best_idx = i
                    
            if best_idx >= 0:
                selected.append(unselected.pop(best_idx))
            else:
                break
                
        # 重新赋予 rank
        for i, item in enumerate(selected, 1):
            item.rank = i

        return selected
