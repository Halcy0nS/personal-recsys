"""
Reranker Prompt 模板库 v2 - 针对 Embedding + Reranker 架构
利用正样本（收藏夹）进行 Few-Shot Learning
"""

from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class Article:
    """文章数据结构"""
    id: str
    title: str
    summary: str
    tags: List[str]
    author: str
    likes: int = 0


@dataclass
class UserProfile:
    """用户画像（从收藏夹构建）"""
    collected_articles: List[Article]
    core_topics: List[str]
    writing_style: List[str]
    negative_tags: List[str]


class RerankerPrompts:
    """
    Reranker Prompt 模板库
    提供多种评分策略：Pointwise, Pairwise, Listwise
    """

    # ==================== Pointwise Scoring (单篇评分) ====================

    @staticmethod
    def pointwise_fewshot_v1(
        user_profile: UserProfile,
        candidate: Article,
        score_criteria: Optional[str] = None
    ) -> str:
        """
        Pointwise Few-Shot 评分模板
        用收藏夹作为正样本示例，让模型学习评分标准

        适用场景: 需要精细评分，候选数量较少 (<50篇)
        """

        # 选择最具代表性的收藏文章作为 few-shot 示例
        exemplars = user_profile.collected_articles[:5]

        prompt = f"""你是一个专业的内容推荐助手。请根据用户的收藏偏好，评估候选文章的相关度。

=== 用户的收藏偏好（示例 - 这些文章用户已收藏，代表其兴趣）===

"""

        for i, article in enumerate(exemplars, 1):
            prompt += f"""
[{i}] 《{article.title}》
    标签: {', '.join(article.tags)}
    摘要: {article.summary[:100]}...
    [用户已收藏 - 高兴趣度]
"""

        prompt += f"""

=== 用户兴趣画像总结 ===
核心关注主题: {', '.join(user_profile.core_topics[:8])}
偏好内容风格: {', '.join(user_profile.writing_style[:5])}
不喜欢: {', '.join(user_profile.negative_tags[:5]) if user_profile.negative_tags else '无明确负面偏好'}

=== 候选文章评估 ===

文章标题: 《{candidate.title}》
作者: {candidate.author}
标签: {', '.join(candidate.tags)}
摘要: {candidate.summary[:200]}...

{score_criteria if score_criteria else ''}

请对这篇文章与用户兴趣的匹配度进行评分：

评分标准:
- 10分: 完美匹配，用户极可能收藏
- 7-9分: 高度相关，符合核心兴趣
- 4-6分: 中度相关，部分匹配
- 1-3分: 低相关，兴趣外内容
- 0分: 完全不相关或包含负面标签

请以JSON格式输出:
{{
  "relevance_score": <0-10的整数>,
  "confidence": <0-1之间，你对这个评分的置信度>,
  "reasoning": "<详细的评分理由，说明这篇文章与用户收藏偏好的匹配点或不匹配点>",
  "matched_topics": ["<匹配的主题1>", "<匹配的主题2>"],
  "concerns": ["<可能的问题，如包含负面标签等，没有则留空>"]
}}
"""
        return prompt

    # ==================== Pairwise Comparison (两两对比) ====================

    @staticmethod
    def pairwise_preference_v1(
        user_profile: UserProfile,
        article_a: Article,
        article_b: Article
    ) -> str:
        """
        Pairwise 偏好比较模板
        直接比较两篇文章，判断哪篇更符合用户偏好

        适用场景: 只需要排序，不需要绝对分数，候选数量中等 (50-200篇)
        优势: 比Pointwise更稳定的相对排序
        """

        exemplars = user_profile.collected_articles[:3]

        prompt = f"""你是一个内容推荐助手。请根据用户的收藏偏好，判断两篇文章中哪篇更符合用户兴趣。

=== 用户收藏偏好示例 ===
"""

        for i, article in enumerate(exemplars, 1):
            prompt += f"""
[{i}] 《{article.title}》 - 标签: {', '.join(article.tags[:3])}
"""

        prompt += f"""
用户核心兴趣: {', '.join(user_profile.core_topics[:5])}

=== 待比较的两篇文章 ===

【文章A】
标题: 《{article_a.title}》
作者: {article_a.author}
标签: {', '.join(article_a.tags)}
摘要: {article_a.summary[:150]}...

【文章B】
标题: 《{article_b.title}》
作者: {article_b.author}
标签: {', '.join(article_b.tags)}
摘要: {article_b.summary[:150]}...

=== 判断任务 ===
哪篇文章更符合上述用户的收藏偏好？请考虑：
1. 主题匹配度（是否涉及用户感兴趣的核心主题）
2. 内容质量信号（作者专业度、内容深度等）
3. 与用户收藏历史中的文章的相似度

请以JSON格式输出：
{{
  "preferred": "A" | "B" | "tie",
  "confidence": <0-1之间>,
  "reasoning": "<为什么选这篇的理由>",
  "article_a_strengths": ["<文章A的优势1>", "<优势2>"],
  "article_b_strengths": ["<文章B的优势1>", "<优势2>"]
}}
"""
        return prompt

    # ==================== Listwise Reranking (列表重排) ====================

    @staticmethod
    def listwise_rerank_v1(
        user_profile: UserProfile,
        candidates: List[Article],
        top_k: int = 10
    ) -> str:
        """
        Listwise 重排序模板
        一次性对整批候选文章进行排序，选出Top-K

        适用场景: 最终精排阶段，候选数量较少 (<30篇)
        优势: 可以考虑候选之间的多样性、互补性
        """

        # 限制候选数量，避免Prompt过长
        candidates = candidates[:30]

        exemplars = user_profile.collected_articles[:3]

        prompt = f"""你是一个专业的内容策展人。请根据用户的收藏偏好，从候选文章中选出最值得推荐的{top_k}篇，并进行排序。

=== 用户收藏偏好（示例）===
"""

        for i, article in enumerate(exemplars, 1):
            prompt += f"""
[{i}] 《{article.title}》
    标签: {', '.join(article.tags[:3])}
"""

        prompt += f"""
用户核心兴趣: {', '.join(user_profile.core_topics[:6])}
偏好风格: {', '.join(user_profile.writing_style[:3])}

=== 候选文章列表（共{len(candidates)}篇）===
"""

        for i, article in enumerate(candidates, 1):
            prompt += f"""
[{i}] ID: {article.id}
    标题: 《{article.title}》
    作者: {article.author}
    标签: {', '.join(article.tags[:5])}
    摘要: {article.summary[:100]}...
"""

        prompt += f"""
=== 任务要求 ===

请从上述{len(candidates)}篇文章中，选出最值得推荐给这位用户的{top_k}篇，并按推荐优先级排序（第1名是最推荐的）。

选择时请考虑：
1. **主题相关性**：文章主题是否与用户的核心兴趣匹配
2. **内容质量**：作者专业度、内容深度、信息密度
3. **时效性**：如果是技术类内容，是否反映较新的发展
4. **多样性**：推荐列表应该覆盖用户的多个兴趣点，而不是全部集中在单一主题

=== 输出格式 ===
请以JSON格式输出，只包含选出的{top_k}篇文章：
{{
  "recommendations": [
    {{
      "rank": 1,
      "article_id": "<文章ID>",
      "title": "<文章标题>",
      "relevance_score": <1-10的相关度评分>,
      "reason": "符合用户对深度技术内容的偏好，与其收藏的《Transformer架构详解》主题相关"
    }},
    ...
  ]
}}
"""
        return prompt


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 构造示例数据
    user = UserProfile(
        collected_articles=[
            Article(id="c1", title="Transformer架构详解", summary="Attention机制...", tags=["AI", "深度学习"], author="李博"),
            Article(id="c2", title="FIRE运动实践", summary="财务独立...", tags=["理财", "FIRE"], author="张财"),
        ],
        core_topics=["AI", "深度学习", "理财"],
        writing_style=["深度长文", "技术细节"],
        negative_tags=["标题党"]
    )

    candidate = Article(
        id="new1",
        title="PyTorch入门指南",
        summary="介绍PyTorch深度学习框架的基础用法...",
        tags=["AI", "Python", "框架"],
        author="王码",
        likes=1200
    )

    # 生成 Pointwise Prompt
    prompt = RerankerPrompts.pointwise_fewshot_v1(user, candidate)
    print("=== Pointwise Prompt (前1500字符) ===")
    print(prompt[:1500])
    print("...")
    print(f"\n总长度: {len(prompt)} 字符")
