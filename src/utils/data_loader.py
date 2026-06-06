"""
数据加载器 - 将输入 JSON 转换为引擎可用格式
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


SUPPORTED_ITEM_FORMATS = ("zhihu", "generic")


def _load_json_array(path: str) -> List[Dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    try:
        with file_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array in {path}")

    return payload


def _ensure_non_empty_string(value: Any, field_name: str, index: int, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Item #{index} in {path} has invalid {field_name!r}; expected non-empty string")
    return value.strip()


def _ensure_string_list(value: Any, field_name: str, index: int, path: str) -> List[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Item #{index} in {path} has invalid {field_name!r}; expected string array")
    return [item.strip() for item in value if item.strip()]


def _ensure_object(value: Any, field_name: str, index: int, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Item #{index} in {path} has invalid {field_name!r}; expected object")
    return dict(value)


def load_generic_items(path: str) -> List[Dict]:
    """
    加载通用 JSON 文件并校验 schema。

    schema:
      - id: string
      - title: string
      - content: string
      - tags: string[]
      - metadata: object
    """
    raw_items = _load_json_array(path)
    items = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"Item #{index} in {path} must be an object")

        missing_fields = [field for field in ("id", "title", "content", "tags", "metadata") if field not in raw]
        if missing_fields:
            raise ValueError(f"Item #{index} in {path} is missing required fields: {missing_fields}")

        metadata = _ensure_object(raw["metadata"], "metadata", index, path)
        metadata.setdefault("source", "generic")
        items.append(
            {
                "id": _ensure_non_empty_string(raw["id"], "id", index, path),
                "title": _ensure_non_empty_string(raw["title"], "title", index, path),
                "content": _ensure_non_empty_string(raw["content"], "content", index, path),
                "tags": _ensure_string_list(raw["tags"], "tags", index, path),
                "metadata": metadata,
                "source": "generic",
            }
        )

    return items


def load_zhihu_items(path: str) -> List[Dict]:
    """
    加载知乎爬虫 JSON 文件

    Args:
        path: JSON 文件路径

    Returns:
        标准化后的项目列表
    """
    raw_items = _load_json_array(path)

    items = []
    for raw in raw_items:
        metadata = dict(raw.get("metadata", {}))
        metadata.setdefault("source", "zhihu")
        metadata.setdefault("url", raw.get("url", ""))
        metadata.setdefault("content_type", raw.get("content_type", ""))
        metadata.setdefault("voteup_count", raw.get("voteup_count", 0))
        metadata.setdefault("comment_count", raw.get("comment_count", 0))
        metadata.setdefault("author_name", raw.get("author", {}).get("name", ""))
        metadata.setdefault("author_id", raw.get("author", {}).get("id", ""))
        item = {
            "id": raw.get("id", ""),
            "title": raw.get("title", ""),
            "content": raw.get("content", "") or raw.get("excerpt", ""),
            "tags": [tag.strip() for tag in raw.get("tags", []) if isinstance(tag, str) and tag.strip()],
            "url": raw.get("url", ""),
            "source": "zhihu",
            "content_type": raw.get("content_type", ""),
            "voteup_count": raw.get("voteup_count", 0),
            "comment_count": raw.get("comment_count", 0),
            "author_name": raw.get("author", {}).get("name", ""),
            "author_id": raw.get("author", {}).get("id", ""),
            "metadata": metadata,
        }
        items.append(item)

    return items


def load_items(path: str, item_format: str) -> List[Dict]:
    """
    统一加载入口，按 format 选择适配逻辑。
    """
    if item_format not in SUPPORTED_ITEM_FORMATS:
        raise ValueError(f"Unsupported item format: {item_format}. Expected one of {SUPPORTED_ITEM_FORMATS}")
    if item_format == "zhihu":
        return load_zhihu_items(path)
    return load_generic_items(path)


def dedupe_items_by_id(items: List[Dict]) -> Tuple[List[Dict], int]:
    """
    按 id 去重，保留首次出现项。
    """
    deduped = []
    seen_ids = set()
    duplicate_count = 0
    for item in items:
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            duplicate_count += 1
            continue
        if item_id in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(item_id)
        deduped.append(item)
    return deduped, duplicate_count


def prepare_collection_candidates(
    collection_items: List[Dict],
    candidate_items: List[Dict],
) -> Tuple[List[Dict], List[Dict], Dict[str, int]]:
    """
    去重并移除与收藏集重叠的候选项。
    """
    unique_collection, collection_duplicate_count = dedupe_items_by_id(collection_items)
    unique_candidates, candidate_duplicate_count = dedupe_items_by_id(candidate_items)
    collection_ids = {item["id"] for item in unique_collection}
    filtered_candidates = [item for item in unique_candidates if item["id"] not in collection_ids]
    overlap_removed_count = len(unique_candidates) - len(filtered_candidates)

    summary = {
        "collection_input_count": len(collection_items),
        "collection_unique_count": len(unique_collection),
        "collection_duplicate_count": collection_duplicate_count,
        "candidate_input_count": len(candidate_items),
        "candidate_unique_count": len(unique_candidates),
        "candidate_duplicate_count": candidate_duplicate_count,
        "candidate_overlap_removed_count": overlap_removed_count,
        "candidate_final_count": len(filtered_candidates),
    }
    return unique_collection, filtered_candidates, summary


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
    collection_items, candidates, summary = prepare_collection_candidates(favorites, author_data)

    print(f"Collection: {summary['collection_unique_count']} items")
    print(
        "Candidates: "
        f"{summary['candidate_final_count']} items "
        f"(removed {summary['candidate_overlap_removed_count']} overlapping, "
        f"{summary['candidate_duplicate_count']} duplicates)"
    )

    return collection_items, candidates


def compute_popularity(item: Dict) -> float:
    """
    根据知乎指标计算归一化流行度分数

    使用对数归一化: log(1 + voteup + comment*2) 的相对值
    """
    import math
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {}
    voteup = metadata.get("voteup_count", item.get("voteup_count", 0))
    comment = metadata.get("comment_count", item.get("comment_count", 0))
    return math.log1p(voteup + comment * 2)
