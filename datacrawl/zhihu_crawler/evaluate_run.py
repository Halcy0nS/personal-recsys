#!/usr/bin/env python3
"""
评估抓取输出质量指标：
- detail_completeness_rate
- valid_url_rate
- resumability
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _is_valid_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith("https://www.zhihu.com/")


def evaluate_file(data_file: Path, min_content_len: int) -> dict[str, Any]:
    items = _load_items(data_file)
    total = len(items)
    if total == 0:
        return {
            "file": str(data_file),
            "total": 0,
            "detail_completeness_rate": 0.0,
            "valid_url_rate": 0.0,
            "id_coverage_rate": 0.0,
        }

    valid_url = 0
    complete_content = 0
    has_id = 0
    for item in items:
        url = item.get("url", "")
        if _is_valid_url(url):
            valid_url += 1
        content_text = item.get("content_text") or item.get("content") or ""
        if isinstance(content_text, str) and len(content_text.strip()) >= min_content_len:
            complete_content += 1
        if str(item.get("id", "")).strip():
            has_id += 1

    return {
        "file": str(data_file),
        "total": total,
        "detail_completeness_rate": round(complete_content / total, 4),
        "valid_url_rate": round(valid_url / total, 4),
        "id_coverage_rate": round(has_id / total, 4),
    }


def evaluate_resumability(data_dir: Path, author_id: str) -> dict[str, Any]:
    aggregate_file = data_dir / f"author_{author_id}_answers_aggregate.json"
    state_file = data_dir / f"author_{author_id}_answers_aggregate_state.json"
    index_checkpoint = data_dir / f"author_{author_id}_answers_index_checkpoint.json"
    detail_checkpoint = data_dir / f"author_{author_id}_answers_detail_checkpoint.json"

    aggregate_items = _load_items(aggregate_file) if aggregate_file.exists() else []
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    aggregate_total = len(aggregate_items)
    state_total = int(state.get("aggregate_total") or 0)
    checkpoints_exist = index_checkpoint.exists() and detail_checkpoint.exists()
    aligned = aggregate_total > 0 and state_total in {0, aggregate_total}

    return {
        "aggregate_file_exists": aggregate_file.exists(),
        "state_file_exists": state_file.exists(),
        "index_checkpoint_exists": index_checkpoint.exists(),
        "detail_checkpoint_exists": detail_checkpoint.exists(),
        "checkpoints_exist": checkpoints_exist,
        "aggregate_total": aggregate_total,
        "state_total": state_total,
        "resumability_ok": bool(checkpoints_exist and aligned),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评估知乎抓取输出质量")
    parser.add_argument("--data-file", type=str, required=True, help="输出 JSON 文件路径")
    parser.add_argument("--author-id", type=str, default="", help="作者ID（用于可恢复性检查）")
    parser.add_argument("--data-dir", type=str, default="./data", help="状态文件目录")
    parser.add_argument("--min-content-len", type=int, default=200, help="详情完整最小长度阈值")
    args = parser.parse_args()

    data_file = Path(args.data_file)
    summary = evaluate_file(data_file, max(1, args.min_content_len))
    if args.author_id:
        summary["resumability"] = evaluate_resumability(Path(args.data_dir), args.author_id)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
