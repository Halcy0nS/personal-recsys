import logging
from typing import List

from ..ranking.scorer import RankedItem
from ..utils.lm_studio_client import LMStudioLLMClient

logger = logging.getLogger(__name__)


class LLMCurator:
    """生成式 RSS 策展器：基于排序后的文章和用户的知识锚点，生成每日导读。"""

    def __init__(self, llm_client: LMStudioLLMClient):
        self.llm_client = llm_client

    def generate_daily_curation(self, ranked_items: List[RankedItem], anchor_text: str) -> str:
        """根据选出的文章和锚点，生成 Markdown 格式的导读。"""

        if not ranked_items:
            return "今日无新文章推荐。"

        articles_context = ""
        for item in ranked_items:
            title = item.metadata.get('title', 'Unknown Title')
            url = item.metadata.get('url', '#')
            # RankedItem 不含全文；content_snippet 需由调用方通过 metadata 传入
            content_snippet = item.metadata.get('content_snippet', '')

            articles_context += f"## 标题：{title}\nURL: {url}\n摘要/正文片段：\n{content_snippet}\n\n"

        prompt = (
            f"你是一名顶级的私人信息编辑与策展人。你的任务是根据我最近的思考（知识锚点）和我精心筛选出的几篇文章，为我写一份 500 字左右的《每日私人导读》。\n\n"
            f"【我的近期思考（知识锚点）】\n"
            f"{anchor_text}\n\n"
            f"【今日入选的 Top 文章】\n"
            f"{articles_context}\n\n"
            f"要求：\n"
            f"1. 采用专业但口语化的博客风格，直接称呼我为「你」。\n"
            f"2. 明确指出这几篇文章中哪些观点能够【补充】或【挑战】我近期的思考。\n"
            f"3. 返回纯 Markdown 格式。引用文章时请使用 [[文章标题]] 的双向链接形式（如果在 Obsidian 中使用）。"
        )

        messages = [
            {"role": "system", "content": "你是一个智能、犀利的 RSS 策展系统助理。"},
            {"role": "user", "content": prompt}
        ]

        try:
            logger.info("正在调用 LLM 生成每日导读...")
            response = self.llm_client.chat(messages)
            return response.choices[0].message.content
        except Exception as e:
            logger.error("生成导读失败: %s", e)
            return f"生成导读失败，请检查 LLM 服务是否可用。错误信息: {e}"
