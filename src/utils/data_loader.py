"""
知乎数据加载器 - 将爬虫 JSON 转换为引擎可用格式
"""

import json
from typing import List, Dict, Tuple


def load_zhihu_items(path: str) -> List[Dict]:
    """
    加载知乎爬虫 JSON 文件

    Args:
        path: JSON 文件路径

    Returns:
        标准化后的项目列表
    """
    with open(path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    items = []
    for raw in raw_items:
        item = {
            "id": raw.get("id", ""),
            "title": raw.get("title", ""),
            "content": raw.get("content", "") or raw.get("excerpt", ""),
            "url": raw.get("url", ""),
            "source": "zhihu",
            "content_type": raw.get("content_type", ""),
            "voteup_count": raw.get("voteup_count", 0),
            "comment_count": raw.get("comment_count", 0),
            "author_name": raw.get("author", {}).get("name", ""),
            "author_id": raw.get("author", {}).get("id", ""),
            "metadata": raw.get("metadata", {}),
        }
        items.append(item)

    return items


def split_collection_candidates(
    favorites: List[Dict],
    author_data: List[Dict]
) -> Tuple[List[Dict], List[Dict]]:
    """
    分割收藏夹和候选池，去除重叠项

    Args:
        favorites: 收藏夹数据 (用户画像来源)
        author_data: 作者回答数据 (候选池来源)

    Returns:
        (collection_items, candidate_items)
        collection = favorites
        candidates = author_data 中不在 favorites 里的项目
    """
    fav_ids = set(item["id"] for item in favorites)
    candidates = [item for item in author_data if item["id"] not in fav_ids]

    print(f"Collection: {len(favorites)} items")
    print(f"Candidates: {len(candidates)} items (removed {len(author_data) - len(candidates)} overlapping)")

    return favorites, candidates


def compute_popularity(item: Dict) -> float:
    """
    根据知乎指标计算归一化流行度分数

    使用对数归一化: log(1 + voteup + comment*2) 的相对值
    """
    import math
    voteup = item.get("voteup_count", 0)
    comment = item.get("comment_count", 0)
    return math.log1p(voteup + comment * 2)
