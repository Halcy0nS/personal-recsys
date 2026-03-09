"""
配置文件
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


@dataclass
class CrawlConfig:
    """爬虫配置"""
    # 基础配置
    headless: bool = False  # 是否无头模式
    data_dir: str = "./data"
    cookies_file: str = "./data/cookies.json"

    # 爬取限制
    max_pages: int = 10  # 每个任务最大爬取页数
    delay_between_requests: float = 2.0  # 请求间隔（秒）
    max_retries: int = 3  # 最大重试次数
    debug_logging: bool = os.getenv("ZHIHU_DEBUG_LOGS", "0").strip().lower() in {"1", "true", "yes", "on"}

    # 选择器配置（当知乎页面结构变化时需要更新）
    selectors: dict = field(default_factory=lambda: {
        "content_item": ".ContentItem, .AnswerItem, .ArticleItem",
        "title": "h2.ContentItem-title, .ContentItem-title a, .ContentItem-title span",
        "content": ".RichContent-inner, .RichContent",
        "author": ".AuthorInfo-name",
        "vote_count": ".VoteButton--up",
        "comment_count": ".ContentItem-action button",
        "next_button": ".PaginationButton-next",
        "avatar": "[data-za-detail-view-path-module='UserAvatar']"
    })


@dataclass
class ZhihuAuthConfig:
    """知乎认证配置"""
    username: Optional[str] = None
    password: Optional[str] = None

    def __post_init__(self):
        # 从环境变量读取
        self.username = self.username or os.getenv("ZHIHU_USERNAME")
        self.password = self.password or os.getenv("ZHIHU_PASSWORD")


# 全局配置实例
crawl_config = CrawlConfig()
auth_config = ZhihuAuthConfig()
