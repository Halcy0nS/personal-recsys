"""
LLM Reranker 服务 - 基于 Pointwise 评分的精排重排
使用 reranker_prompts_v2.py 中定义的模板

在管线中的位置:
  粗召回 (I2I+Tag) → Top-N → **LLM Rerank** → 最终 Top-K
"""

import json
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

from ..utils.lm_studio_client import LMStudioLLMClient


@dataclass
class RerankerResult:
    """单个候选的 rerank 评分结果"""
    item_id: str
    relevance_score: float  # 0-10
    confidence: float  # 0-1
    reasoning: str
    matched_topics: List[str]
    concerns: List[str]


class LLMReranker:
    """
    LLM Pointwise Reranker

    使用 LLM 对粗排的 Top-N 候选逐一评分，
    基于用户画像和收藏偏好进行精细匹配判断。

    适用场景: 粗排后的 Top-30~50 候选精排
    """

    def __init__(self,
                 llm_client: Optional[LMStudioLLMClient] = None,
                 model: str = "qwen3-reranker-8b",
                 base_url: str = "http://localhost:1234/v1",
                 rerank_top_n: int = 50,
                 strategy: str = "pointwise"):
        """
        Args:
            llm_client: LLM 客户端 (可复用已有实例)
            model: LLM 模型 ID
            base_url: LM Studio API 地址
            rerank_top_n: 从粗排结果取多少条送入 rerank
            strategy: 当前仅支持 pointwise
        """
        if strategy != "pointwise":
            raise ValueError(f"Unsupported rerank strategy: {strategy}")

        self.llm_client = llm_client or LMStudioLLMClient(
            base_url=base_url,
            model=model,
            temperature=0.1,
            max_tokens=500
        )
        self.rerank_top_n = rerank_top_n
        self.strategy = strategy

    def _build_pointwise_prompt(self,
                                candidate_title: str,
                                candidate_content: str,
                                candidate_metadata: Dict,
                                profile_topics: List[str],
                                profile_styles: List[str],
                                profile_negatives: List[str],
                                exemplar_titles: List[str]) -> str:
        """
        构建 Pointwise 评分 prompt
        基于 reranker_prompts_v2.py 的 pointwise_fewshot_v1 模板
        """
        # Few-shot 正样本
        exemplar_section = ""
        for i, title in enumerate(exemplar_titles[:5], 1):
            exemplar_section += f"\n[{i}] 《{title}》 [用户已收藏 - 高兴趣度]"

        neg_text = ', '.join(profile_negatives[:5]) if profile_negatives else '无明确负面偏好'

        prompt = f"""你是一个专业的内容推荐助手。请根据用户的收藏偏好，评估候选文章的相关度。

=== 用户的收藏偏好（示例 - 这些文章用户已收藏，代表其兴趣）===
{exemplar_section}

=== 用户兴趣画像总结 ===
核心关注主题: {', '.join(profile_topics[:8])}
偏好内容风格: {', '.join(profile_styles[:5])}
不喜欢: {neg_text}

=== 候选文章评估 ===

文章标题: 《{candidate_title}》
作者: {candidate_metadata.get('author_name', '未知')}
摘要: {candidate_content[:200]}...

请对这篇文章与用户兴趣的匹配度进行评分：

评分标准:
- 10分: 完美匹配，用户极可能收藏
- 7-9分: 高度相关，符合核心兴趣
- 4-6分: 中度相关，部分匹配
- 1-3分: 低相关，兴趣外内容
- 0分: 完全不相关或包含负面标签

请直接以JSON格式输出（不要输出思考过程）:
{{"relevance_score": <0-10的整数>, "confidence": <0-1之间>, "reasoning": "<简短评分理由>", "matched_topics": ["<匹配的主题>"], "concerns": ["<可能的问题>"]}}"""

        return prompt

    def _parse_response(self, response_text: str, item_id: str) -> RerankerResult:
        """解析 LLM 返回的 JSON 评分"""
        # 清理可能的思考标签和多余内容
        text = response_text.strip()

        # 移除 <think>...</think> 标签
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        # 尝试提取 JSON
        json_match = re.search(r'\{[^{}]*\}', text)
        if json_match:
            text = json_match.group()

        try:
            data = json.loads(text)
            return RerankerResult(
                item_id=item_id,
                relevance_score=float(data.get("relevance_score", 5)),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
                matched_topics=data.get("matched_topics", []),
                concerns=data.get("concerns", [])
            )
        except (json.JSONDecodeError, ValueError):
            # 解析失败，返回中性分数
            return RerankerResult(
                item_id=item_id,
                relevance_score=5.0,
                confidence=0.1,
                reasoning=f"JSON parse failed: {text[:100]}",
                matched_topics=[],
                concerns=["parse_error"]
            )

    def rerank(self,
               candidates: Dict,
               profile_topics: List[str],
               profile_styles: List[str],
               profile_negatives: List[str],
               exemplar_titles: List[str],
               coarse_ranked_ids: List[str] = None) -> List[RerankerResult]:
        """
        对候选进行 LLM Pointwise 重排序

        Args:
            candidates: {item_id: CandidateItem}
            profile_topics: 用户核心兴趣主题
            profile_styles: 用户偏好风格
            profile_negatives: 用户负面标签
            exemplar_titles: 用户收藏文章标题 (few-shot 示例)
            coarse_ranked_ids: 粗排后的 item_id 排序列表 (仅对 top-N 进行 rerank)

        Returns:
            按 relevance_score 降序排列的 RerankerResult 列表
        """
        # 确定要 rerank 的候选
        if coarse_ranked_ids:
            ids_to_rerank = coarse_ranked_ids[:self.rerank_top_n]
        else:
            ids_to_rerank = list(candidates.keys())[:self.rerank_top_n]

        if not ids_to_rerank:
            return []

        results = []
        total = len(ids_to_rerank)
        print(f"  LLM Reranking {total} candidates...")

        for i, item_id in enumerate(ids_to_rerank):
            candidate = candidates.get(item_id)
            if not candidate:
                continue

            prompt = self._build_pointwise_prompt(
                candidate_title=candidate.title,
                candidate_content=candidate.content,
                candidate_metadata=candidate.metadata,
                profile_topics=profile_topics,
                profile_styles=profile_styles,
                profile_negatives=profile_negatives,
                exemplar_titles=exemplar_titles
            )

            try:
                response = self.llm_client.chat([
                    {"role": "user", "content": prompt}
                ])
                response_text = response.choices[0].message.content
                result = self._parse_response(response_text, item_id)
            except Exception as e:
                # API 调用失败，保留中性分数
                result = RerankerResult(
                    item_id=item_id,
                    relevance_score=5.0,
                    confidence=0.1,
                    reasoning=f"API error: {str(e)[:80]}",
                    matched_topics=[],
                    concerns=["api_error"]
                )

            results.append(result)

            if (i + 1) % 5 == 0:
                print(f"    Progress: {i+1}/{total}")

        # 按 relevance_score 降序排序
        results.sort(key=lambda r: r.relevance_score, reverse=True)

        print(f"  Reranking complete. Top score: {results[0].relevance_score if results else 'N/A'}")
        return results
