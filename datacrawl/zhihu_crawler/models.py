"""
数据模型定义
"""
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import json


@dataclass
class ZhihuAuthor:
    """作者信息"""
    id: str = ""
    name: str = ""
    url: str = ""
    headline: str = ""  # 个人简介
    avatar_url: str = ""
    follower_count: int = 0


@dataclass
class ZhihuContent:
    """知乎内容基类"""
    id: str = ""
    content_type: str = ""  # 'answer', 'article', 'pin', 'question'
    title: Optional[str] = None
    content: str = ""
    content_html: str = ""
    content_text: str = ""
    excerpt: str = ""  # 摘要
    author: ZhihuAuthor = field(default_factory=ZhihuAuthor)
    created_time: str = ""
    updated_time: str = ""

    # 互动数据
    voteup_count: int = 0
    comment_count: int = 0

    # 链接
    url: str = ""

    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典"""
        data = asdict(self)
        # 处理嵌套dataclass
        if isinstance(data.get('author'), dict):
            data['author'] = data['author']
        return data

    def to_json(self, indent: int = 2) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


@dataclass
class ZhihuCollection:
    """收藏夹信息"""
    id: str = ""
    title: str = ""
    description: str = ""
    url: str = ""
    author: ZhihuAuthor = field(default_factory=ZhihuAuthor)
    item_count: int = 0
    contents: List[ZhihuContent] = field(default_factory=list)


@dataclass
class CrawlResult:
    """爬取结果"""
    success: bool = True
    message: str = ""
    contents: List[ZhihuContent] = field(default_factory=list)
    total_count: int = 0
    saved_files: List[str] = field(default_factory=list)
