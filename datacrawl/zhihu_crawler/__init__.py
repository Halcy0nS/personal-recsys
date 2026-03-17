"""
知乎爬虫工具

一个基于 Playwright 的知乎内容爬取工具。
"""

__version__ = "1.0.0"
__author__ = "Claude Code"

from crawler import ZhihuCrawler
from favorites_crawler import FavoritesCrawler
from author_crawler import AuthorCrawler
from models import ZhihuContent, ZhihuAuthor, CrawlResult

__all__ = [
    "ZhihuCrawler",
    "FavoritesCrawler",
    "AuthorCrawler",
    "ZhihuContent",
    "ZhihuAuthor",
    "CrawlResult",
]
