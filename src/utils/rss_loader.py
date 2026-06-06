import feedparser
import urllib.request
import urllib.error
import hashlib
import logging
from typing import List, Optional
import time

from ..engine import CandidateItem
from .lm_studio_client import LMStudioLLMClient

logger = logging.getLogger(__name__)


def fetch_jina_markdown(url: str, max_retries: int = 2) -> str:
    """使用 Jina Reader API 获取干净的 Markdown 全文（可能包含渲染后的评论）"""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for attempt in range(max_retries):
        req = urllib.request.Request(jina_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            if attempt == max_retries - 1:
                logger.warning("Jina fetch failed after %d retries for %s: %s", max_retries, url, e)
                return ""
            time.sleep(1)

def compress_article(llm_client: LMStudioLLMClient, title: str, raw_text: str) -> str:
    """使用大模型对长文本进行高密度压缩（降噪与核心提取）"""
    if not raw_text or len(raw_text) < 200:
        return raw_text

    # 简单截断防止极端超长（一般 Jina 抓下来的文本在几万 token 内，但仍需保护）
    # DeepSeek 允许长上下文，但为节约成本和提速，我们截断前 30000 字符。
    raw_text = raw_text[:30000] 
    
    prompt = (
        f"你是一个信息降噪与提纯的智能编译器。\n"
        f"以下是一篇抓取自网络的文章（标题：{title}），文本中可能混杂了广告、导航栏或低价值的口水战。\n"
        f"请将其压缩提炼为一段 200-300 字的高密度精华，必须包含：\n"
        f"1. 核心主张 (Core Claims)。\n"
        f"2. 最有价值的论据或数据。\n"
        f"3. （如果文本中含有评论）提取出最具启发性的反驳视角或补充。\n"
        f"【原文内容】:\n{raw_text}\n"
    )

    messages = [
        {"role": "system", "content": "你负责将冗余的信息降噪压缩为高密度的知识块。"},
        {"role": "user", "content": prompt}
    ]
    
    try:
        print(f"  [Compile] 正在使用 LLM 压缩: {title[:30]}...")
        response = llm_client.chat(messages)
        return response.choices[0].message.content
    except Exception as e:
        print(f"  [Compile Error] 压缩失败: {e}")
        return raw_text[:500] + "\n...(压缩失败，展示截断原文)"

def fetch_and_compile_rss(feed_urls: List[str], llm_client: LMStudioLLMClient, max_per_feed: int = 3) -> List[CandidateItem]:
    """拉取 RSS，使用 Jina 获取全文，并通过大模型逐篇压缩。"""
    candidates = []
    
    for url in feed_urls:
        try:
            print(f"[RSS] 解析 Feed: {url}")
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = getattr(entry, "title", "No Title")
                link = getattr(entry, "link", url)
                
                # 1. 采集 (Collect) - Jina Reader
                raw_md = fetch_jina_markdown(link)
                if not raw_md:
                    # 如果抓取失败，退回使用 rss 里的 summary
                    raw_md = getattr(entry, "description", getattr(entry, "summary", ""))
                
                # 2. 压缩 (Compile)
                compressed_md = compress_article(llm_client, title, raw_md)
                
                # 3. 封装为 CandidateItem
                item_id_str = f"rss_{hashlib.md5(link.encode()).hexdigest()[:10]}"
                tags = [tag.term for tag in getattr(entry, "tags", [])]
                
                metadata = {
                    "url": link,
                    "source": url,
                    "published": getattr(entry, "published", ""),
                    "popularity": 0
                }
                
                candidates.append(CandidateItem(
                    item_id=item_id_str,
                    title=title,
                    content=compressed_md,
                    tags=tags,
                    metadata=metadata
                ))
                time.sleep(1) # 避免请求过快
        except Exception as e:
            print(f"[Warning] 处理 Feed {url} 失败: {e}")
            continue
            
    return candidates
