"""
Author-specific crawling flows.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from crawler import ZhihuCrawler
from models import CrawlResult, ZhihuAuthor, ZhihuContent


class AuthorCrawler(ZhihuCrawler):
    HARD_PAGE_CAP = 5000
    INCREMENTAL_OVERLAP = 30
    INCREMENTAL_TAIL_WINDOW = 300
    MAX_STAGNANT_ROUNDS = 4
    MAX_NO_NEXT_ROUNDS = 3
    MAX_RELOAD_RECOVERIES = 2
    INDEX_CHECKPOINT_INTERVAL = 100
    DETAIL_CHECKPOINT_INTERVAL = 100
    DETAIL_LOG_INTERVAL = 100
    DEFAULT_BATCH_SIZE = 200
    DEFAULT_DETAIL_WORKERS = 4
    DEFAULT_DETAIL_MIN_WORKERS = 4
    DEFAULT_DETAIL_MAX_WORKERS = 10
    DEFAULT_MAX_EMPTY_BATCHES = 5
    DEFAULT_EMPTY_BATCH_RETRY_DELAY_SEC = 5
    DETAIL_SOURCE_PRIORITY = {
        "js-initialData": 3,
        "dom_fallback": 2,
        "blocked_or_summary_fallback": 1,
    }

    def _wait_for_answer_listing_ready(self, item_selector: str) -> None:
        assert self.page is not None

        count = self._wait_for_item_count(item_selector, min_count=1, timeout_ms=4000)
        if count > 0:
            return

        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

    def _wait_for_answer_detail_ready(self) -> None:
        assert self.page is not None

        selectors = [
            "#js-initialData",
            ".RichContent-inner",
            ".RichText",
            ".QuestionAnswer-content",
        ]
        for selector in selectors:
            try:
                self.page.wait_for_selector(selector, state="attached", timeout=1200)
                return
            except Exception:
                continue

        self.page.wait_for_timeout(100)

    def _save_answer_index_checkpoint(
        self,
        author_id: str,
        summaries: list[ZhihuContent],
        expected_total: int | None,
        stats: dict[str, int | str | None],
        *,
        reason: str,
        index_complete: bool = False,
        last_anchor_answer_id: str = "",
        preserve_richer: bool = True,
    ) -> str:
        checkpoint_path = self.data_dir / f"author_{author_id}_answers_index_checkpoint.json"
        payload = {
            "author_id": author_id,
            "expected_total": expected_total,
            "current_count": len(summaries),
            "gap": (
                max(expected_total - len(summaries), 0)
                if expected_total is not None
                else None
            ),
            "reason": reason,
            "index_complete": bool(index_complete),
            "last_anchor_answer_id": last_anchor_answer_id or "",
            "pages_visited": int(stats.get("pages_visited") or 0),
            "stop_reason": str(stats.get("stop_reason") or ""),
            "stats": stats,
            "items": [item.to_dict() for item in summaries],
        }
        if preserve_richer and checkpoint_path.exists():
            try:
                existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                existing_count = int(existing.get("current_count") or 0)
                if existing_count > payload["current_count"]:
                    self._get_console().print(
                        "[yellow]"
                        f"Kept richer index checkpoint: {checkpoint_path} "
                        f"(existing={existing_count}, new={payload['current_count']})"
                        "[/yellow]"
                    )
                    return str(checkpoint_path)
            except Exception:
                pass
        checkpoint_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._get_console().print(f"[green]Saved index checkpoint:[/green] {checkpoint_path}")
        return str(checkpoint_path)

    def _save_answer_detail_checkpoint(
        self,
        prefix: str,
        detailed_contents: list[ZhihuContent],
        expected_total: int | None,
        detail_success_total: int,
        *,
        reason: str,
        preserve_richer: bool = True,
    ) -> str:
        checkpoint_path = self.data_dir / f"{prefix}_detail_checkpoint.json"
        payload = {
            "prefix": prefix,
            "expected_total": expected_total,
            "current_count": len(detailed_contents),
            "gap": (
                max(expected_total - len(detailed_contents), 0)
                if expected_total is not None
                else None
            ),
            "detail_json_success": detail_success_total,
            "reason": reason,
            "items": [item.to_dict() for item in detailed_contents],
        }
        if preserve_richer and checkpoint_path.exists():
            try:
                existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                existing_count = int(existing.get("current_count") or 0)
                if existing_count > payload["current_count"]:
                    self._get_console().print(
                        "[yellow]"
                        f"Kept richer detail checkpoint: {checkpoint_path} "
                        f"(existing={existing_count}, new={payload['current_count']})"
                        "[/yellow]"
                    )
                    return str(checkpoint_path)
            except Exception:
                pass
        checkpoint_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._get_console().print(f"[green]Saved detail checkpoint:[/green] {checkpoint_path}")
        return str(checkpoint_path)

    def _aggregate_paths(self, author_id: str) -> tuple[Path, Path]:
        aggregate_path = self.data_dir / f"author_{author_id}_answers_aggregate.json"
        state_path = self.data_dir / f"author_{author_id}_answers_aggregate_state.json"
        return aggregate_path, state_path

    def _content_from_dict(self, item: dict[str, Any]) -> ZhihuContent:
        author_raw = item.get("author") or {}
        return ZhihuContent(
            id=str(item.get("id") or ""),
            content_type=item.get("content_type") or "",
            title=item.get("title"),
            content=item.get("content") or "",
            content_html=item.get("content_html") or "",
            content_text=item.get("content_text") or "",
            excerpt=item.get("excerpt") or "",
            author=ZhihuAuthor(
                id=author_raw.get("id") or "",
                name=author_raw.get("name") or "",
                url=author_raw.get("url") or "",
                headline=author_raw.get("headline") or "",
                avatar_url=author_raw.get("avatar_url") or "",
                follower_count=int(author_raw.get("follower_count") or 0),
            ),
            created_time=str(item.get("created_time") or ""),
            updated_time=str(item.get("updated_time") or ""),
            voteup_count=int(item.get("voteup_count") or 0),
            comment_count=int(item.get("comment_count") or 0),
            url=item.get("url") or "",
            metadata=item.get("metadata") or {},
        )

    def _content_key(self, content: ZhihuContent) -> str:
        if content.id:
            return f"id:{content.id}"
        return f"url:{content.url}"

    def _is_index_checkpoint_complete(self, stop_reason: str, expected_total: int | None, current_count: int) -> bool:
        stop_reason = (stop_reason or "").strip()
        if stop_reason == "expected_total_reached":
            return True
        if stop_reason == "no_next":
            return expected_total is None or current_count >= expected_total
        return False

    def _detail_source_priority(self, content: ZhihuContent) -> int:
        source = content.metadata.get("detail_source", "")
        return self.DETAIL_SOURCE_PRIORITY.get(str(source), 0)

    def _timestamp_score(self, content: ZhihuContent) -> int:
        for candidate in (content.updated_time, content.created_time):
            if not candidate:
                continue
            digits = re.findall(r"\d+", str(candidate))
            if digits:
                try:
                    return int("".join(digits))
                except Exception:
                    continue
        return 0

    def _should_upgrade_content(self, existing: ZhihuContent, candidate: ZhihuContent) -> bool:
        existing_priority = self._detail_source_priority(existing)
        candidate_priority = self._detail_source_priority(candidate)
        if candidate_priority > existing_priority:
            return True
        if candidate_priority < existing_priority:
            return False

        existing_len = len(existing.content_text or existing.content or "")
        candidate_len = len(candidate.content_text or candidate.content or "")
        if candidate_len > existing_len:
            return True
        if candidate_len < existing_len:
            return False

        return self._timestamp_score(candidate) >= self._timestamp_score(existing)

    def _load_answer_aggregate(
        self,
        author_id: str,
    ) -> tuple[dict[str, ZhihuContent], dict[str, Any]]:
        aggregate_path, state_path = self._aggregate_paths(author_id)
        aggregate_map: dict[str, ZhihuContent] = {}
        state: dict[str, Any] = {}

        if aggregate_path.exists():
            try:
                payload = json.loads(aggregate_path.read_text(encoding="utf-8"))
                items = payload if isinstance(payload, list) else payload.get("items", [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    content = self._content_from_dict(item)
                    key = self._content_key(content)
                    aggregate_map[key] = content
            except Exception:
                pass

        if state_path.exists():
            try:
                loaded_state = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(loaded_state, dict):
                    state = loaded_state
            except Exception:
                state = {}

        return aggregate_map, state

    def _load_contents_from_payload(self, payload: Any) -> list[ZhihuContent]:
        items: list[Any]
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            maybe_items = payload.get("items", [])
            items = maybe_items if isinstance(maybe_items, list) else []
        else:
            items = []

        contents: list[ZhihuContent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            contents.append(self._content_from_dict(item))
        return contents

    def _seed_aggregate_from_checkpoints(
        self,
        author_id: str,
        aggregate_map: dict[str, ZhihuContent],
    ) -> int:
        detail_path = self.data_dir / f"author_{author_id}_answers_detail_checkpoint.json"
        index_path = self.data_dir / f"author_{author_id}_answers_index_checkpoint.json"
        seeded_before = len(aggregate_map)

        for checkpoint_path in (detail_path, index_path):
            if not checkpoint_path.exists():
                continue
            try:
                payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            contents = self._load_contents_from_payload(payload)
            self._merge_batch_into_aggregate(aggregate_map, contents)

        seeded_after = len(aggregate_map)
        seeded_count = max(seeded_after - seeded_before, 0)
        if seeded_count > 0:
            self._get_console().print(
                "[yellow]"
                f"Seeded aggregate from checkpoints: +{seeded_count} (total={seeded_after})"
                "[/yellow]"
            )
        return seeded_count

    def _save_answer_aggregate(
        self,
        author_id: str,
        aggregate_map: dict[str, ZhihuContent],
        state: dict[str, Any],
        *,
        preserve_richer: bool = True,
    ) -> tuple[str, str]:
        aggregate_path, state_path = self._aggregate_paths(author_id)
        aggregate_items = [asdict(item) for item in aggregate_map.values()]
        if preserve_richer and aggregate_path.exists():
            try:
                existing_payload = json.loads(aggregate_path.read_text(encoding="utf-8"))
                existing_contents = self._load_contents_from_payload(existing_payload)
                existing_count = len(existing_contents)
                if existing_count > len(aggregate_items):
                    self._get_console().print(
                        "[yellow]"
                        f"Kept richer aggregate: {aggregate_path} "
                        f"(existing={existing_count}, new={len(aggregate_items)})"
                        "[/yellow]"
                    )
                    keep_state = dict(state)
                    keep_state["aggregate_total"] = existing_count
                    keep_state["updated_at"] = int(time.time())
                    state_path.write_text(
                        json.dumps(keep_state, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    return str(aggregate_path), str(state_path)
            except Exception:
                pass
        aggregate_path.write_text(
            json.dumps(aggregate_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._get_console().print(f"[green]Saved aggregate:[/green] {aggregate_path}")
        self._get_console().print(f"[green]Saved aggregate state:[/green] {state_path}")
        return str(aggregate_path), str(state_path)

    def _merge_batch_into_aggregate(
        self,
        aggregate_map: dict[str, ZhihuContent],
        batch_contents: list[ZhihuContent],
    ) -> tuple[int, int]:
        added = 0
        upgraded = 0
        for content in batch_contents:
            key = self._content_key(content)
            existing = aggregate_map.get(key)
            if existing is None:
                aggregate_map[key] = content
                added += 1
                continue
            if self._should_upgrade_content(existing, content):
                aggregate_map[key] = content
                upgraded += 1
        return added, upgraded

    def _count_detail_json_success(self, contents: list[ZhihuContent]) -> int:
        return sum(1 for item in contents if item.metadata.get("detail_source") == "js-initialData")

    def _is_detail_page_blocked(self) -> bool:
        assert self.page is not None

        blocked_markers = (
            "安全验证",
            "进入知乎",
            "开始验证",
            "网络环境存在异常",
            "登录知乎",
            "扫码登录",
        )
        try:
            title = self.page.title()
        except Exception:
            title = ""
        if any(marker in title for marker in blocked_markers):
            return True

        try:
            body_text = self.page.locator("body").inner_text(timeout=1500)
        except Exception:
            body_text = ""
        return any(marker in body_text for marker in blocked_markers)

    def _get_incremental_start_index(self, current_count: int, previous_count: int) -> int:
        if previous_count <= 0:
            return 0
        if current_count > previous_count:
            return max(0, previous_count - self.INCREMENTAL_OVERLAP)
        return max(0, current_count - self.INCREMENTAL_TAIL_WINDOW)

    def _extract_expected_total(self, path_suffix: str, content_label: str) -> int | None:
        assert self.page is not None

        patterns = [
            re.compile(rf"{content_label}\s*(\d+)"),
            re.compile(rf"(\d+)\s*{content_label}"),
        ]
        selector_candidates = [
            f"a[href$='{path_suffix}']",
            f"a[href*='{path_suffix}']",
            "[role='tab']",
            "button",
            "a",
        ]

        texts: list[str] = []
        for selector in selector_candidates:
            try:
                locator = self.page.locator(selector)
                count = min(locator.count(), 20)
                for index in range(count):
                    text = locator.nth(index).inner_text(timeout=300).strip()
                    if text and text not in texts:
                        texts.append(text)
            except Exception:
                continue

        try:
            body_lines = self.page.locator("body").inner_text(timeout=1000).splitlines()
            for line in body_lines[:80]:
                line = line.strip()
                if content_label in line and 0 < len(line) <= 80 and line not in texts:
                    texts.append(line)
        except Exception:
            pass

        candidates: list[int] = []
        for text in texts:
            normalized = text.replace(",", "")
            for pattern in patterns:
                match = pattern.search(normalized)
                if match:
                    candidates.append(int(match.group(1)))

        if not candidates:
            return None
        return max(candidates)

    def _reload_listing_for_tail_recovery(
        self,
        listing_url: str,
        item_selector: str,
    ) -> bool:
        if not self._safe_goto(listing_url, wait_until="domcontentloaded", retries=2):
            return False
        assert self.page is not None
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        count = self._wait_for_item_count(item_selector, min_count=1, timeout_ms=15000)
        return count > 0

    def _fast_forward_listing_to_anchor(
        self,
        item_selector: str,
        anchor_answer_id: str,
        recent_seen_ids: set[str],
        seen_count: int,
    ) -> bool:
        assert self.page is not None

        target_loaded_count = max(1, seen_count - self.INCREMENTAL_TAIL_WINDOW)
        previous_raw_count = 0
        stagnant_rounds = 0

        for attempt in range(1, 41):
            raw_count = self._wait_for_item_count(item_selector, min_count=1, timeout_ms=4000)
            if raw_count <= 0:
                raw_count = self._recover_empty_viewport(item_selector)

            if raw_count <= 0:
                stagnant_rounds += 1
            else:
                start_index = max(0, raw_count - max(self.INCREMENTAL_TAIL_WINDOW, 120))
                contents = self._extract_page_contents(item_selector, start_index=start_index)
                visible_ids = {content.id for content in contents if content.id}
                if anchor_answer_id and anchor_answer_id in visible_ids:
                    return True
                if raw_count >= target_loaded_count and visible_ids & recent_seen_ids:
                    return True

                if raw_count == previous_raw_count:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                previous_raw_count = raw_count

                if attempt % 5 == 0:
                    self._get_console().print(
                        "[dim]"
                        f"reload_catchup attempt={attempt} raw={raw_count} target_loaded={target_loaded_count}"
                        "[/dim]"
                    )

            if stagnant_rounds >= 4:
                break

            self._try_infinite_scroll_load(item_selector=item_selector)
            self.page.wait_for_timeout(80)

        return False

    def _extract_answer_index_entries(
        self,
        author_id: str,
        max_pages: int,
        target_count: int,
        on_new_answers: Callable[[list[ZhihuContent], int | None, int], None] | None = None,
        existing_answer_ids: set[str] | None = None,
        initial_summaries: list[ZhihuContent] | None = None,
        resume_anchor_answer_id: str = "",
        preserve_checkpoint: bool = True,
    ) -> tuple[list[ZhihuContent], int | None, dict[str, int | str | None]]:
        url = f"https://www.zhihu.com/people/{author_id}/answers"
        item_selector = ".ContentItem, .AnswerItem"
        console = self._get_console()

        if not self._safe_goto(url, wait_until="domcontentloaded", retries=3):
            raise RuntimeError("Failed to open author answers page")

        assert self.page is not None
        if self._is_login_or_challenge_page():
            console.print("[yellow]Author answers listing hit login/challenge page; re-auth and retry[/yellow]")
            self.ensure_login()
            if not self._safe_goto(url, wait_until="domcontentloaded", retries=3):
                raise RuntimeError("Failed to reopen author answers page after re-auth")
        self._wait_for_answer_listing_ready(item_selector)

        try:
            if self.page.locator(".EmptyState, .EmptyAnswers").count() > 0:
                return [], None, {
                    "duplicates_total": 0,
                    "empty_viewport_recoveries": 0,
                    "listing_reload_recoveries": 0,
                    "pages_visited": 0,
                    "stop_reason": "empty",
                }
        except Exception:
            pass

        expected_total = self._extract_expected_total("/answers", "回答")
        if expected_total is not None:
            console.print(f"[dim]Detected expected total for 回答: {expected_total}[/dim]")

        all_answers: list[ZhihuContent] = list(initial_summaries or [])
        seen_answer_ids: set[str] = {item.id for item in all_answers if item.id}
        seen_answer_keys: set[str] = {
            self._content_key(item) for item in all_answers if item.id or item.url
        }
        known_answer_ids = set(existing_answer_ids or set()) - seen_answer_ids
        known_start_count = len(known_answer_ids)
        duplicates_total = 0
        known_duplicates_total = 0
        stagnant_rounds = 0
        no_next_rounds = 0
        empty_viewport_recoveries = 0
        listing_reload_recoveries = 0
        stop_reason: str = "unknown"

        unlimited_mode = max_pages <= 0
        page_limit = self.HARD_PAGE_CAP if unlimited_mode else max_pages
        previous_raw_count = 0
        previous_marker = ""
        previous_tail = ""
        page_num = 0
        next_checkpoint_at = self.INDEX_CHECKPOINT_INTERVAL

        if all_answers:
            anchor_answer_id = resume_anchor_answer_id or all_answers[-1].id
            recent_seen_ids = {
                item.id for item in all_answers[-max(self.INCREMENTAL_TAIL_WINDOW, 50) :] if item.id
            }
            console.print(
                "[dim]"
                f"Resuming index with existing_summaries={len(all_answers)} anchor={anchor_answer_id or 'none'}"
                "[/dim]"
            )
            if anchor_answer_id and recent_seen_ids:
                caught_up = self._fast_forward_listing_to_anchor(
                    item_selector,
                    anchor_answer_id,
                    recent_seen_ids,
                    len(all_answers),
                )
                console.print(
                    "[yellow]"
                    f"Resume catch-up status: {'ok' if caught_up else 'failed'} "
                    f"(anchor={anchor_answer_id}, seen={len(all_answers)})."
                    "[/yellow]"
                )

        while page_num < page_limit:
            try:
                self.page.wait_for_selector(item_selector, timeout=10000)
            except Exception:
                self.page.wait_for_timeout(300)

            raw_count = self._wait_for_item_count(item_selector, min_count=1, timeout_ms=15000)
            if raw_count <= 0:
                raw_count = self._recover_empty_viewport(item_selector)
                if raw_count > 0:
                    empty_viewport_recoveries += 1

            if raw_count <= 0:
                if self._is_login_or_challenge_page():
                    console.print(
                        "[yellow]"
                        "Listing became login/challenge page during index stage; re-auth and reload."
                        "[/yellow]"
                    )
                    self.ensure_login()
                    if self._safe_goto(url, wait_until="domcontentloaded", retries=3):
                        self._wait_for_answer_listing_ready(item_selector)
                        previous_raw_count = 0
                        previous_marker = ""
                        previous_tail = ""
                        continue
                if (
                    expected_total is not None
                    and len(all_answers) < expected_total
                    and listing_reload_recoveries < self.MAX_RELOAD_RECOVERIES
                ):
                    listing_reload_recoveries += 1
                    console.print(
                        "[yellow]"
                        f"Empty viewport with remaining gap; reloading listing (recovery={listing_reload_recoveries})."
                        "[/yellow]"
                    )
                    if self._reload_listing_for_tail_recovery(url, item_selector):
                        anchor_answer_id = all_answers[-1].id if all_answers else ""
                        recent_seen_ids = {
                            item.id for item in all_answers[-max(self.INCREMENTAL_TAIL_WINDOW, 50) :] if item.id
                        }
                        if anchor_answer_id and recent_seen_ids:
                            caught_up = self._fast_forward_listing_to_anchor(
                                item_selector,
                                anchor_answer_id,
                                recent_seen_ids,
                                len(all_answers),
                            )
                            console.print(
                                "[yellow]"
                                f"Reload catch-up status: {'ok' if caught_up else 'failed'} "
                                f"(anchor={anchor_answer_id}, seen={len(all_answers)})."
                                "[/yellow]"
                            )
                        previous_raw_count = 0
                        previous_marker = ""
                        previous_tail = ""
                        no_next_rounds = 0
                        continue

                stagnant_rounds += 1
                console.print(
                    "[yellow]"
                    f"No items visible yet for 回答; retrying (stagnant={stagnant_rounds})."
                    "[/yellow]"
                )
                if stagnant_rounds >= self.MAX_STAGNANT_ROUNDS:
                    stop_reason = "no_items"
                    break
                self._try_infinite_scroll_load(item_selector=item_selector)
                continue

            page_num += 1
            marker = self._get_page_marker()
            tail = self._get_item_tail_signature(item_selector)
            start_index = self._get_incremental_start_index(raw_count, previous_raw_count)
            contents = self._extract_page_contents(item_selector, start_index=start_index)

            unique_answers: list[ZhihuContent] = []
            duplicate_count = 0
            for content in contents:
                if content.content_type != "answer" or not (content.id or content.url):
                    continue
                question_match = re.search(r"/question/(\d+)", content.url)
                author_token = content.author.id or ""
                content.metadata.update(
                    {
                        "source_stage": "list",
                        "question_id": question_match.group(1) if question_match else "",
                        "author_url_token": author_token,
                        "expected_total_at_run": expected_total,
                    }
                )
                content_key = self._content_key(content)
                if content_key in seen_answer_keys:
                    duplicate_count += 1
                    continue
                seen_answer_keys.add(content_key)
                if content.id:
                    seen_answer_ids.add(content.id)
                if content.id and content.id in known_answer_ids:
                    known_duplicates_total += 1
                    continue
                unique_answers.append(content)

            if target_count > 0:
                remaining_slots = max(target_count - len(all_answers), 0)
                if remaining_slots == 0:
                    unique_answers = []
                elif len(unique_answers) > remaining_slots:
                    unique_answers = unique_answers[:remaining_slots]

            all_answers.extend(unique_answers)
            duplicates_total += duplicate_count
            if unique_answers and on_new_answers is not None:
                on_new_answers(unique_answers, expected_total, page_num)

            counter = Counter(item.content_type for item in unique_answers)
            remaining_hint = (
                max(expected_total - (known_start_count + len(all_answers)), 0)
                if expected_total is not None
                else None
            )
            console.print(
                "[dim]"
                f"page={page_num} raw={raw_count} window={len(contents)} start={start_index} "
                f"added={len(unique_answers)} dup={duplicate_count} answers={counter.get('answer', 0)} "
                f"unique_answers={len(all_answers)}"
                f"{'' if remaining_hint is None else f' remaining_hint={remaining_hint}'}"
                "[/dim]"
            )

            if len(all_answers) >= next_checkpoint_at:
                checkpoint_stats = {
                    "duplicates_total": duplicates_total,
                    "empty_viewport_recoveries": empty_viewport_recoveries,
                    "listing_reload_recoveries": listing_reload_recoveries,
                    "pages_visited": page_num,
                    "stop_reason": f"in_progress_page_{page_num}",
                }
                self._save_answer_index_checkpoint(
                    author_id,
                    all_answers,
                    expected_total,
                    checkpoint_stats,
                    reason=f"progress_{len(all_answers)}",
                    index_complete=False,
                    last_anchor_answer_id=all_answers[-1].id if all_answers else "",
                    preserve_richer=preserve_checkpoint,
                )
                next_checkpoint_at += self.INDEX_CHECKPOINT_INTERVAL

            structural_progress = (
                raw_count != previous_raw_count
                or marker != previous_marker
                or tail != previous_tail
                or len(unique_answers) > 0
            )
            if len(unique_answers) == 0 and not structural_progress:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            previous_raw_count = raw_count
            previous_marker = marker
            previous_tail = tail

            if target_count > 0 and len(all_answers) >= target_count:
                all_answers = all_answers[:target_count]
                stop_reason = "target_count"
                break

            if expected_total is not None and (known_start_count + len(all_answers)) >= expected_total:
                stop_reason = "expected_total_reached"
                break

            if not unlimited_mode and page_num >= max_pages:
                stop_reason = "max_pages"
                break

            has_next = self._goto_next_page(item_selector=item_selector)
            if has_next:
                no_next_rounds = 0
                continue

            no_next_rounds += 1
            should_drain = (
                no_next_rounds < self.MAX_NO_NEXT_ROUNDS
                and (
                    len(unique_answers) > 0
                    or structural_progress
                    or (
                        expected_total is not None
                        and len(all_answers) < expected_total
                    )
                )
            )
            if should_drain:
                remaining_hint = (
                    max(expected_total - len(all_answers), 0)
                    if expected_total is not None
                    else "unknown"
                )
                console.print(
                    "[yellow]"
                    f"No next page detected, draining again (round={no_next_rounds}, remaining_hint={remaining_hint})."
                    "[/yellow]"
                )
                self.page.wait_for_timeout(300)
                continue

            if (
                expected_total is not None
                and (known_start_count + len(all_answers)) < expected_total
                and listing_reload_recoveries < self.MAX_RELOAD_RECOVERIES
            ):
                listing_reload_recoveries += 1
                console.print(
                    "[yellow]"
                    f"No next page before expected total; reloading listing (recovery={listing_reload_recoveries})."
                    "[/yellow]"
                )
                if self._reload_listing_for_tail_recovery(url, item_selector):
                    anchor_answer_id = all_answers[-1].id if all_answers else ""
                    recent_seen_ids = {
                        item.id for item in all_answers[-max(self.INCREMENTAL_TAIL_WINDOW, 50) :] if item.id
                    }
                    if anchor_answer_id and recent_seen_ids:
                        caught_up = self._fast_forward_listing_to_anchor(
                            item_selector,
                            anchor_answer_id,
                            recent_seen_ids,
                            len(all_answers),
                        )
                        console.print(
                            "[yellow]"
                            f"Reload catch-up status: {'ok' if caught_up else 'failed'} "
                            f"(anchor={anchor_answer_id}, seen={len(all_answers)})."
                            "[/yellow]"
                        )
                    previous_raw_count = 0
                    previous_marker = ""
                    previous_tail = ""
                    no_next_rounds = 0
                    continue

            if stagnant_rounds >= self.MAX_STAGNANT_ROUNDS:
                stop_reason = "stagnant_rounds"
            elif expected_total is not None and (known_start_count + len(all_answers)) < expected_total:
                stop_reason = "expected_total_gap"
            else:
                stop_reason = "no_next"
            break

        stats: dict[str, int | str | None] = {
            "duplicates_total": duplicates_total,
            "known_duplicates_total": known_duplicates_total,
            "known_start_count": known_start_count,
            "empty_viewport_recoveries": empty_viewport_recoveries,
            "listing_reload_recoveries": listing_reload_recoveries,
            "pages_visited": page_num,
            "stop_reason": stop_reason,
        }
        index_complete = self._is_index_checkpoint_complete(
            stop_reason,
            expected_total,
            known_start_count + len(all_answers),
        )
        self._save_answer_index_checkpoint(
            author_id,
            all_answers,
            expected_total,
            stats,
            reason="index_stage_complete",
            index_complete=index_complete,
            last_anchor_answer_id=all_answers[-1].id if all_answers else "",
            preserve_richer=preserve_checkpoint or len(all_answers) == 0,
        )
        return all_answers, expected_total, stats

    def _extract_answer_detail_from_initial_state(
        self,
        initial_data: dict[str, Any],
        answer_id: str,
        summary: ZhihuContent,
        expected_total: int | None,
    ) -> ZhihuContent | None:
        state = initial_data.get("initialState", {})
        entities = state.get("entities", {})
        answer = entities.get("answers", {}).get(answer_id)
        if not answer:
            return None

        question = answer.get("question", {}) or {}
        author = answer.get("author", {}) or {}

        content_html = answer.get("content") or answer.get("editableContent") or ""
        content_text = self._html_to_text(content_html) if content_html else ""
        if not content_text:
            content_text = summary.content_text or summary.content or summary.excerpt

        author_token = author.get("urlToken") or summary.metadata.get("author_url_token", "")
        author_url = (
            f"https://www.zhihu.com/people/{author_token}"
            if author_token
            else summary.author.url
        )

        metadata = dict(summary.metadata)
        metadata.update(
            {
                "source_stage": "list/detail_json",
                "question_id": str(question.get("id") or metadata.get("question_id", "")),
                "author_url_token": author_token,
                "expected_total_at_run": expected_total,
                "content_need_truncated": bool(answer.get("contentNeedTruncated")),
                "is_collapsed": bool(answer.get("isCollapsed")),
                "detail_source": "js-initialData",
            }
        )

        return ZhihuContent(
            id=str(answer.get("id") or summary.id),
            content_type="answer",
            title=question.get("title") or summary.title,
            content=content_text,
            content_html=content_html,
            content_text=content_text,
            excerpt=answer.get("excerpt") or summary.excerpt,
            author=ZhihuAuthor(
                id=author_token or summary.author.id,
                name=author.get("name") or summary.author.name,
                url=author_url,
                headline=author.get("headline") or summary.author.headline,
                avatar_url=author.get("avatarUrl") or summary.author.avatar_url,
                follower_count=summary.author.follower_count,
            ),
            created_time=str(answer.get("createdTime") or summary.created_time),
            updated_time=str(answer.get("updatedTime") or summary.updated_time),
            voteup_count=int(answer.get("voteupCount") or summary.voteup_count),
            comment_count=int(answer.get("commentCount") or summary.comment_count),
            url=summary.url,
            metadata=metadata,
        )

    def _extract_answer_detail_from_dom(
        self,
        summary: ZhihuContent,
        expected_total: int | None,
    ) -> ZhihuContent:
        assert self.page is not None

        blocked_page = self._is_detail_page_blocked()
        content_html = ""
        content_text = summary.content_text or summary.content or summary.excerpt
        if not blocked_page:
            try:
                body = self.page.locator(".RichContent, .RichText, .AnswerCard").first
                content_html = body.inner_html(timeout=2000)
                content_text = body.inner_text(timeout=2000).strip() or content_text
            except Exception:
                pass

        title = summary.title
        if not blocked_page:
            try:
                page_title = self.page.locator("h1").first.inner_text(timeout=1000).strip()
                title = page_title or title
            except Exception:
                pass

        metadata = dict(summary.metadata)
        metadata.update(
            {
                "source_stage": "list/detail_dom_fallback" if not blocked_page else "list/detail_blocked_fallback",
                "expected_total_at_run": expected_total,
                "detail_source": "dom_fallback" if not blocked_page else "blocked_or_summary_fallback",
                "detail_blocked": blocked_page,
            }
        )
        if blocked_page:
            try:
                metadata["blocked_page_title"] = self.page.title()
            except Exception:
                metadata["blocked_page_title"] = ""

        return ZhihuContent(
            id=summary.id,
            content_type="answer",
            title=title,
            content=content_text,
            content_html=content_html,
            content_text=content_text,
            excerpt=summary.excerpt,
            author=summary.author,
            created_time=summary.created_time,
            updated_time=summary.updated_time,
            voteup_count=summary.voteup_count,
            comment_count=summary.comment_count,
            url=summary.url,
            metadata=metadata,
        )

    def _supplement_answer_details(
        self,
        summaries: list[ZhihuContent],
        expected_total: int | None,
        checkpoint_prefix: str | None = None,
        detail_workers: int = DEFAULT_DETAIL_WORKERS,
        detail_min_workers: int = DEFAULT_DETAIL_MIN_WORKERS,
        detail_max_workers: int = DEFAULT_DETAIL_MAX_WORKERS,
        detail_checkpoint_interval: int = DETAIL_CHECKPOINT_INTERVAL,
        detail_log_interval: int = DETAIL_LOG_INTERVAL,
        preserve_checkpoint: bool = True,
    ) -> tuple[list[ZhihuContent], int]:
        console = self._get_console()
        if not summaries:
            return [], 0

        # 详情阶段前再确认一次登录态，减少批处理中途失效。
        self.ensure_login()
        initial_workers = max(1, int(detail_workers))
        min_workers = max(1, int(detail_min_workers))
        if initial_workers < min_workers:
            min_workers = initial_workers
        max_workers = max(min_workers, int(detail_max_workers))
        checkpoint_interval = max(20, int(detail_checkpoint_interval))
        log_interval = max(20, int(detail_log_interval))
        worker_count = min(max(initial_workers, min_workers), max_workers)
        cookie_header = self._build_cookie_header()
        results: list[ZhihuContent | None] = [None] * len(summaries)
        detail_success_total = 0
        completed = 0
        next_checkpoint_at = checkpoint_interval
        next_log_at = log_interval

        console.print(
            "[dim]"
            f"detail_stage_config workers={worker_count} "
            f"adaptive_range=[{min_workers},{max_workers}] "
            f"checkpoint_every={checkpoint_interval} log_every={log_interval}"
            "[/dim]"
        )

        def _fetch_one(index: int, summary: ZhihuContent) -> tuple[int, ZhihuContent, bool, float]:
            started_at = time.perf_counter()
            answer_id = summary.id
            if not answer_id and summary.url:
                match = re.search(r"/answer/(\d+)", summary.url)
                if match:
                    answer_id = match.group(1)

            html = self._fetch_html_via_http(summary.url, cookie_header, retries=3, timeout_sec=22)
            if html:
                initial_data = self._extract_initial_data(html)
                if initial_data and answer_id:
                    detail = self._extract_answer_detail_from_initial_state(
                        initial_data,
                        answer_id,
                        summary,
                        expected_total,
                    )
                    if detail is not None:
                        return index, detail, True, time.perf_counter() - started_at

                blocked_markers = (
                    "安全验证",
                    "进入知乎",
                    "开始验证",
                    "网络环境存在异常",
                    "登录知乎",
                    "扫码登录",
                )
                blocked = any(marker in html for marker in blocked_markers)
                return (
                    index,
                    self._build_summary_fallback_detail(
                        summary,
                        expected_total,
                        source_stage="list/detail_http_blocked" if blocked else "list/detail_http_fallback",
                        detail_source="blocked_or_summary_fallback",
                        detail_blocked=blocked,
                    ),
                    False,
                    time.perf_counter() - started_at,
                )

            return (
                index,
                self._build_summary_fallback_detail(
                    summary,
                    expected_total,
                    source_stage="list/detail_http_failed",
                    detail_source="blocked_or_summary_fallback",
                    detail_error="empty_http_response",
                ),
                False,
                time.perf_counter() - started_at,
            )

        total_items = len(summaries)
        cursor = 0

        while cursor < total_items:
            chunk_end = min(total_items, cursor + max(worker_count * 3, 24))
            chunk_indices = list(range(cursor, chunk_end))
            chunk_total = len(chunk_indices)
            chunk_failed = 0
            chunk_elapsed_sum = 0.0

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {
                    executor.submit(_fetch_one, idx, summaries[idx]): idx
                    for idx in chunk_indices
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    try:
                        _, detail, success, elapsed = future.result()
                    except Exception as e:
                        detail = self._build_summary_fallback_detail(
                            summaries[idx],
                            expected_total,
                            source_stage="list/detail_http_exception",
                            detail_source="blocked_or_summary_fallback",
                            detail_error=str(e)[:200],
                        )
                        success = False
                        elapsed = 0.0
                    results[idx] = detail
                    completed += 1
                    chunk_elapsed_sum += elapsed
                    if success:
                        detail_success_total += 1
                    else:
                        chunk_failed += 1

                    if completed >= next_log_at or completed == total_items:
                        console.print(
                            "[dim]"
                            f"detail_progress={completed}/{total_items} "
                            f"detail_json_success={detail_success_total} workers={worker_count}"
                            "[/dim]"
                        )
                        while next_log_at <= completed:
                            next_log_at += log_interval

                    if checkpoint_prefix and completed >= next_checkpoint_at:
                        partial = [item for item in results if item is not None]
                        self._save_answer_detail_checkpoint(
                            checkpoint_prefix,
                            partial,
                            expected_total,
                            detail_success_total,
                            reason=f"progress_{completed}",
                            preserve_richer=preserve_checkpoint,
                        )
                        while next_checkpoint_at <= completed:
                            next_checkpoint_at += checkpoint_interval

            chunk_error_rate = (chunk_failed / chunk_total) if chunk_total > 0 else 0.0
            chunk_avg_elapsed = (chunk_elapsed_sum / chunk_total) if chunk_total > 0 else 0.0
            previous_workers = worker_count
            if chunk_error_rate >= 0.30:
                worker_count = max(min_workers, worker_count - 2)
            elif chunk_error_rate >= 0.18:
                worker_count = max(min_workers, worker_count - 1)
            elif chunk_error_rate <= 0.06 and chunk_avg_elapsed <= 1.6:
                worker_count = min(max_workers, worker_count + 1)
            elif chunk_error_rate <= 0.10 and chunk_avg_elapsed <= 2.2 and worker_count < max_workers:
                worker_count = min(max_workers, worker_count + 1)

            if worker_count != previous_workers:
                console.print(
                    "[yellow]"
                    f"Adaptive workers tuned: {previous_workers} -> {worker_count} "
                    f"(error_rate={chunk_error_rate:.2f}, avg_elapsed={chunk_avg_elapsed:.2f}s, chunk={chunk_total})"
                    "[/yellow]"
                )

            cursor = chunk_end

        detailed_contents = []
        for idx, item in enumerate(results):
            if item is not None:
                detailed_contents.append(item)
            else:
                detailed_contents.append(
                    self._build_summary_fallback_detail(
                        summaries[idx],
                        expected_total,
                        source_stage="list/detail_http_missing",
                        detail_source="blocked_or_summary_fallback",
                    )
                )

        if checkpoint_prefix:
            self._save_answer_detail_checkpoint(
                checkpoint_prefix,
                detailed_contents,
                expected_total,
                detail_success_total,
                reason="detail_stage_complete",
                preserve_richer=preserve_checkpoint,
            )

        return detailed_contents, detail_success_total

    def _build_cookie_header(self) -> str:
        if not self.context:
            return ""
        try:
            cookies = self.context.cookies()
        except Exception:
            cookies = []
        parts = []
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    def _fetch_html_via_http(
        self,
        url: str,
        cookie_header: str,
        retries: int = 2,
        timeout_sec: int = 20,
    ) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.zhihu.com/",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        for attempt in range(1, retries + 1):
            try:
                req = Request(url, headers=headers, method="GET")
                with urlopen(req, timeout=timeout_sec) as resp:
                    raw = resp.read()
                    charset = "utf-8"
                    try:
                        maybe_charset = resp.headers.get_content_charset()
                        if maybe_charset:
                            charset = maybe_charset
                    except Exception:
                        pass
                    return raw.decode(charset, errors="ignore")
            except (HTTPError, URLError, TimeoutError, ValueError):
                if attempt < retries:
                    time.sleep(0.35 * attempt)
                continue
            except Exception:
                if attempt < retries:
                    time.sleep(0.35 * attempt)
                continue
        return ""

    def _build_summary_fallback_detail(
        self,
        summary: ZhihuContent,
        expected_total: int | None,
        *,
        source_stage: str,
        detail_source: str,
        detail_blocked: bool = False,
        detail_error: str = "",
    ) -> ZhihuContent:
        metadata = dict(summary.metadata)
        metadata.update(
            {
                "source_stage": source_stage,
                "expected_total_at_run": expected_total,
                "detail_source": detail_source,
                "detail_blocked": bool(detail_blocked),
            }
        )
        if detail_error:
            metadata["detail_error"] = detail_error

        content_text = summary.content_text or summary.content or summary.excerpt
        return ZhihuContent(
            id=summary.id,
            content_type="answer",
            title=summary.title,
            content=content_text,
            content_html=summary.content_html,
            content_text=content_text,
            excerpt=summary.excerpt,
            author=summary.author,
            created_time=summary.created_time,
            updated_time=summary.updated_time,
            voteup_count=summary.voteup_count,
            comment_count=summary.comment_count,
            url=summary.url,
            metadata=metadata,
        )

    def _crawl_author_answer_pipeline(
        self,
        author_id: str,
        max_pages: int = 10,
        target_count: int = 0,
        existing_answer_ids: set[str] | None = None,
        output_prefix: str | None = None,
        detail_checkpoint_prefix: str | None = None,
        detail_workers: int = DEFAULT_DETAIL_WORKERS,
        detail_min_workers: int = DEFAULT_DETAIL_MIN_WORKERS,
        detail_max_workers: int = DEFAULT_DETAIL_MAX_WORKERS,
        detail_checkpoint_interval: int = DETAIL_CHECKPOINT_INTERVAL,
        detail_log_interval: int = DETAIL_LOG_INTERVAL,
    ) -> CrawlResult:
        console = self._get_console()
        result = CrawlResult()
        started_at = time.time()
        prefix = output_prefix or f"author_{author_id}_answers"
        checkpoint_prefix = detail_checkpoint_prefix or f"author_{author_id}_answers"
        worker_count = max(1, int(detail_workers))

        console.print(f"[blue]Starting crawl:[/blue] https://www.zhihu.com/people/{author_id}/answers")
        summaries, expected_total, stats = self._extract_answer_index_entries(
            author_id,
            max_pages=max_pages,
            target_count=target_count,
            on_new_answers=None,
            existing_answer_ids=existing_answer_ids,
        )

        console.print(
            "[dim]"
            f"index_summary expected_total={expected_total} "
            f"unique_answers={len(summaries)} duplicates_total={stats['duplicates_total']} "
            f"known_duplicates_total={stats.get('known_duplicates_total', 0)} "
            f"empty_viewport_recoveries={stats['empty_viewport_recoveries']} "
            f"listing_reload_recoveries={stats['listing_reload_recoveries']} "
            f"pages_visited={stats['pages_visited']} stop={stats['stop_reason']}"
            "[/dim]"
        )

        if not summaries:
            result.message = "No answers fetched"
            return result

        detailed_contents, detail_success_total = self._supplement_answer_details(
            summaries,
            expected_total,
            checkpoint_prefix=checkpoint_prefix,
            detail_workers=worker_count,
            detail_min_workers=detail_min_workers,
            detail_max_workers=detail_max_workers,
            detail_checkpoint_interval=detail_checkpoint_interval,
            detail_log_interval=detail_log_interval,
        )
        files = self._save_contents(detailed_contents, prefix)
        elapsed_sec = time.time() - started_at
        final_gap = (
            max(expected_total - len(detailed_contents), 0)
            if expected_total is not None
            else None
        )

        console.print(
            "[dim]"
            f"final_summary expected_total={expected_total} "
            f"final_answers={len(detailed_contents)} gap={final_gap} "
            f"detail_json_success={detail_success_total} elapsed_sec={elapsed_sec:.1f}"
            "[/dim]"
        )

        result.success = True
        result.total_count = len(detailed_contents)
        result.contents = detailed_contents
        result.saved_files = files
        result.message = (
            f"Fetched {len(detailed_contents)} answers "
            f"(expected {expected_total}, gap {final_gap}, detail_json_success {detail_success_total})"
        )
        return result

    def _crawl_author_answers_index_only(
        self,
        author_id: str,
        max_pages: int,
        target_count: int,
        output_prefix: str | None = None,
    ) -> CrawlResult:
        result = CrawlResult()
        prefix = output_prefix or f"author_{author_id}_answers_index"
        summaries, expected_total, stats = self._extract_answer_index_entries(
            author_id,
            max_pages=max_pages,
            target_count=target_count,
            on_new_answers=None,
            existing_answer_ids=None,
        )
        if not summaries:
            result.message = "No answers fetched in index mode"
            return result

        files = self._save_contents(summaries, prefix)
        gap = (
            max(expected_total - len(summaries), 0)
            if expected_total is not None
            else None
        )
        result.success = True
        result.total_count = len(summaries)
        result.contents = summaries
        result.saved_files = files
        result.message = (
            f"Index mode complete: total={len(summaries)} expected={expected_total} "
            f"gap={gap} stop={stats.get('stop_reason')}"
        )
        return result

    def _crawl_author_answers_detail_only(
        self,
        author_id: str,
        batch_size: int,
        max_batches: int,
        detail_workers: int,
        detail_min_workers: int,
        detail_max_workers: int,
        detail_checkpoint_interval: int,
        detail_log_interval: int,
        resume: bool,
    ) -> CrawlResult:
        result = CrawlResult()
        checkpoint_payload = self._load_index_checkpoint_payload(author_id)
        summaries = self._load_contents_from_payload(checkpoint_payload)
        expected_total = checkpoint_payload.get("expected_total") if isinstance(checkpoint_payload, dict) else None

        # detail-only 模式可从 aggregate 回填，避免仅依赖 index checkpoint。
        if resume and not summaries:
            aggregate_map, state = self._load_answer_aggregate(author_id)
            if aggregate_map:
                ordered_summaries = self._load_contents_from_payload(checkpoint_payload)
                summaries = ordered_summaries or list(aggregate_map.values())
            if state.get("expected_total") is not None:
                expected_total = state.get("expected_total")

        if not summaries:
            result.message = "No index checkpoint data found for detail mode"
            return result

        batch_result = self._run_answer_detail_batches(
            author_id,
            summaries,
            expected_total=expected_total,
            batch_size=max(1, int(batch_size)),
            max_batches=max_batches,
            resume=resume,
            detail_workers=max(1, int(detail_workers)),
            detail_min_workers=detail_min_workers,
            detail_max_workers=detail_max_workers,
            detail_checkpoint_interval=detail_checkpoint_interval,
            detail_log_interval=detail_log_interval,
        )
        batch_result.message = f"Detail mode complete: {batch_result.message}"
        return batch_result

    def _load_index_checkpoint_payload(self, author_id: str) -> dict[str, Any]:
        checkpoint_path = self.data_dir / f"author_{author_id}_answers_index_checkpoint.json"
        if not checkpoint_path.exists():
            return {}
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}
        return {}

    def _infer_detail_next_offset(
        self,
        summaries: list[ZhihuContent],
        aggregate_map: dict[str, ZhihuContent],
        explicit_offset: Any = None,
    ) -> int:
        try:
            candidate = int(explicit_offset or 0)
        except Exception:
            candidate = 0
        if 0 < candidate <= len(summaries):
            return candidate

        offset = 0
        for idx, summary in enumerate(summaries):
            if self._content_key(summary) not in aggregate_map:
                break
            offset = idx + 1
        return offset

    def _ensure_full_answer_index(
        self,
        author_id: str,
        *,
        target_count: int,
        resume: bool,
    ) -> tuple[list[ZhihuContent], int | None, dict[str, int | str | None], dict[str, Any]]:
        checkpoint_payload = self._load_index_checkpoint_payload(author_id) if resume else {}
        summaries = self._load_contents_from_payload(checkpoint_payload)
        expected_total = checkpoint_payload.get("expected_total") if isinstance(checkpoint_payload, dict) else None
        index_complete = bool(checkpoint_payload.get("index_complete")) if isinstance(checkpoint_payload, dict) else False
        stats = checkpoint_payload.get("stats", {}) if isinstance(checkpoint_payload, dict) else {}
        stop_reason = str(checkpoint_payload.get("stop_reason") or stats.get("stop_reason") or "")

        reusable_complete = index_complete and bool(summaries)
        if reusable_complete and target_count > 0:
            reusable_complete = len(summaries) >= target_count
        elif reusable_complete and (
            stop_reason in {"target_count", "max_pages"}
            or not self._is_index_checkpoint_complete(stop_reason, expected_total, len(summaries))
        ):
            reusable_complete = False

        if reusable_complete:
            self._get_console().print(
                "[dim]"
                f"Reusing completed index checkpoint: total={len(summaries)} expected_total={expected_total}"
                "[/dim]"
            )
            return summaries, expected_total, stats, checkpoint_payload

        summaries, expected_total, stats = self._extract_answer_index_entries(
            author_id,
            max_pages=0,
            target_count=target_count,
            on_new_answers=None,
            existing_answer_ids=None,
            initial_summaries=summaries if resume else None,
            resume_anchor_answer_id=str(checkpoint_payload.get("last_anchor_answer_id") or ""),
            preserve_checkpoint=resume,
        )
        checkpoint_payload = self._load_index_checkpoint_payload(author_id)
        return summaries, expected_total, stats, checkpoint_payload

    def _run_answer_detail_batches(
        self,
        author_id: str,
        summaries: list[ZhihuContent],
        *,
        expected_total: int | None,
        batch_size: int,
        max_batches: int,
        resume: bool,
        detail_workers: int,
        detail_min_workers: int,
        detail_max_workers: int,
        detail_checkpoint_interval: int,
        detail_log_interval: int,
    ) -> CrawlResult:
        console = self._get_console()
        result = CrawlResult()
        aggregate_map, previous_state = self._load_answer_aggregate(author_id) if resume else ({}, {})
        if resume and not aggregate_map:
            self._seed_aggregate_from_checkpoints(author_id, aggregate_map)

        started_at = time.time()
        saved_files: list[str] = []
        batch_no = int(previous_state.get("batch_no") or 0) if resume else 0
        expected_total = expected_total if expected_total is not None else previous_state.get("expected_total")
        detail_next_offset = self._infer_detail_next_offset(
            summaries,
            aggregate_map,
            previous_state.get("detail_next_offset") if resume else None,
        )
        max_batches_limit = max_batches if max_batches > 0 else self.HARD_PAGE_CAP
        batches_ran = 0
        preserve_existing = resume

        if detail_next_offset >= len(summaries):
            console.print(
                "[dim]"
                f"Detail stage already complete at offset={detail_next_offset}/{len(summaries)}"
                "[/dim]"
            )

        while detail_next_offset < len(summaries) and batches_ran < max_batches_limit:
            current_batch_no = batch_no + 1
            batch_start = detail_next_offset
            batch_end = min(len(summaries), batch_start + max(1, int(batch_size)))
            batch_summaries = summaries[batch_start:batch_end]
            checkpoint_prefix = f"author_{author_id}_answers_batch{current_batch_no}"

            detailed_contents, _ = self._supplement_answer_details(
                batch_summaries,
                expected_total,
                checkpoint_prefix=checkpoint_prefix,
                detail_workers=detail_workers,
                detail_min_workers=detail_min_workers,
                detail_max_workers=detail_max_workers,
                detail_checkpoint_interval=detail_checkpoint_interval,
                detail_log_interval=detail_log_interval,
                preserve_checkpoint=preserve_existing,
            )
            batch_added, batch_upgraded = self._merge_batch_into_aggregate(aggregate_map, detailed_contents)
            detail_next_offset = batch_end
            detail_success_total = self._count_detail_json_success(list(aggregate_map.values()))
            stop_reason = "detail_complete" if detail_next_offset >= len(summaries) else "detail_batch_complete"

            global_detail_checkpoint = self._save_answer_detail_checkpoint(
                f"author_{author_id}_answers",
                list(aggregate_map.values()),
                expected_total,
                detail_success_total,
                reason=f"aggregate_batch_{current_batch_no}",
                preserve_richer=preserve_existing,
            )
            state = {
                "author_id": author_id,
                "batch_no": current_batch_no,
                "batch_size": max(1, int(batch_size)),
                "batch_added": batch_added,
                "batch_upgraded": batch_upgraded,
                "aggregate_total": len(aggregate_map),
                "detail_json_success_total": detail_success_total,
                "expected_total": expected_total,
                "index_complete": True,
                "detail_completed_count": detail_next_offset,
                "detail_next_offset": detail_next_offset,
                "detail_total_target": len(summaries),
                "last_stop_reason": stop_reason,
                "updated_at": int(time.time()),
            }
            aggregate_file, state_file = self._save_answer_aggregate(
                author_id,
                aggregate_map,
                state,
                preserve_richer=preserve_existing,
            )
            batch_files = self._save_contents(detailed_contents, checkpoint_prefix)
            saved_files.extend([aggregate_file, state_file, global_detail_checkpoint, *batch_files])

            console.print(
                "[dim]"
                f"detail_batch={current_batch_no} range={batch_start}:{batch_end} "
                f"batch_added={batch_added} batch_upgraded={batch_upgraded} "
                f"aggregate_total={len(aggregate_map)} detail_json_success_total={detail_success_total}"
                "[/dim]"
            )

            batch_no = current_batch_no
            batches_ran += 1

        dedup_saved_files = list(dict.fromkeys(saved_files))
        aggregate_contents = list(aggregate_map.values())
        detail_success_total = self._count_detail_json_success(aggregate_contents)
        final_gap = (
            max(int(expected_total) - len(aggregate_contents), 0)
            if expected_total is not None
            else None
        )
        elapsed_sec = time.time() - started_at
        remaining_detail = max(len(summaries) - detail_next_offset, 0)

        result.success = True
        result.contents = aggregate_contents
        result.total_count = len(aggregate_contents)
        result.saved_files = dedup_saved_files
        result.message = (
            f"Detail batching complete: total={len(aggregate_contents)} "
            f"(index_total={len(summaries)}, remaining_detail={remaining_detail}, "
            f"expected={expected_total}, gap={final_gap}, batches={batch_no}, "
            f"detail_json_success={detail_success_total}, elapsed_sec={elapsed_sec:.1f})"
        )
        return result

    def _crawl_author_answers_batched(
        self,
        author_id: str,
        *,
        target_count: int,
        batch_size: int,
        max_batches: int,
        resume: bool,
        detail_workers: int,
        detail_min_workers: int,
        detail_max_workers: int,
        detail_checkpoint_interval: int,
        detail_log_interval: int,
        max_empty_batches: int,
        empty_batch_retry_delay_sec: int,
    ) -> CrawlResult:
        console = self._get_console()
        if max_empty_batches or empty_batch_retry_delay_sec:
            console.print(
                "[dim]"
                "Full mode now runs a single index stage; empty-batch retry knobs only affect legacy progress state."
                "[/dim]"
            )

        summaries, expected_total, stats, checkpoint_payload = self._ensure_full_answer_index(
            author_id,
            target_count=target_count,
            resume=resume,
        )
        if checkpoint_payload.get("expected_total") is not None:
            expected_total = checkpoint_payload.get("expected_total")
        if not summaries:
            result = CrawlResult()
            result.message = "No index data available for full mode"
            return result

        console.print(
            "[dim]"
            f"full_index_summary total={len(summaries)} expected_total={expected_total} "
            f"stop={checkpoint_payload.get('stop_reason') or stats.get('stop_reason')}"
            "[/dim]"
        )
        return self._run_answer_detail_batches(
            author_id,
            summaries,
            expected_total=expected_total,
            batch_size=batch_size,
            max_batches=max_batches,
            resume=resume,
            detail_workers=detail_workers,
            detail_min_workers=detail_min_workers,
            detail_max_workers=detail_max_workers,
            detail_checkpoint_interval=detail_checkpoint_interval,
            detail_log_interval=detail_log_interval,
        )

    def _crawl_author_listing(
        self,
        *,
        author_id: str,
        path_suffix: str,
        item_selector: str,
        empty_selector: str,
        save_prefix: str,
        target_count: int = 0,
        max_pages: int = 10,
    ) -> CrawlResult:
        result = CrawlResult()
        url = f"https://www.zhihu.com/people/{author_id}{path_suffix}"
        console = self._get_console()
        content_label = "回答" if path_suffix == "/answers" else "文章"

        console.print(f"[blue]Starting crawl:[/blue] {url}")
        if not self._safe_goto(url, wait_until="domcontentloaded", retries=3):
            result.message = "Failed to open author page"
            return result

        assert self.page is not None
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        self.page.wait_for_timeout(250)

        try:
            if empty_selector and self.page.locator(empty_selector).count() > 0:
                result.message = "No content found for this author"
                return result
        except Exception:
            pass

        expected_total = self._extract_expected_total(path_suffix, content_label)
        if expected_total is not None:
            console.print(f"[dim]Detected expected total for {content_label}: {expected_total}[/dim]")

        all_contents: list[ZhihuContent] = []
        seen_keys: set[str] = set()
        duplicates_total = 0
        stagnant_rounds = 0
        no_next_rounds = 0
        stop_reason = "unknown"
        start_time = time.time()

        unlimited_mode = max_pages <= 0
        page_limit = self.HARD_PAGE_CAP if unlimited_mode else max_pages
        previous_raw_count = 0
        previous_marker = ""
        previous_tail = ""
        page_num = 0

        while page_num < page_limit:
            unique_added = 0

            try:
                self.page.wait_for_selector(item_selector, timeout=10000)
            except Exception:
                self.page.wait_for_timeout(300)

            raw_count = self._wait_for_item_count(item_selector, min_count=1, timeout_ms=15000)
            if raw_count <= 0:
                raw_count = self._recover_empty_viewport(item_selector)
            if raw_count <= 0:
                stagnant_rounds += 1
                console.print(
                    "[yellow]"
                    f"No items visible yet for {content_label}; retrying (stagnant={stagnant_rounds})."
                    "[/yellow]"
                )
                if stagnant_rounds >= self.MAX_STAGNANT_ROUNDS:
                    stop_reason = "no_items"
                    break
                self._try_infinite_scroll_load(item_selector=item_selector)
                continue

            page_num += 1
            marker = self._get_page_marker()
            tail = self._get_item_tail_signature(item_selector)
            start_index = self._get_incremental_start_index(raw_count, previous_raw_count)
            contents = self._extract_page_contents(item_selector, start_index=start_index)

            unique_contents: list[ZhihuContent] = []
            duplicate_count = 0
            for content in contents:
                dedup_key = self._build_dedup_key(content)
                if dedup_key in seen_keys:
                    duplicate_count += 1
                    continue
                seen_keys.add(dedup_key)
                unique_contents.append(content)

            all_contents.extend(unique_contents)
            unique_added = len(unique_contents)
            duplicates_total += duplicate_count

            type_counter = Counter(content.content_type for content in unique_contents)
            remaining_hint = (
                max(expected_total - len(all_contents), 0) if expected_total is not None else None
            )
            console.print(
                "[dim]"
                f"page={page_num} raw={raw_count} window={len(contents)} start={start_index} "
                f"added={unique_added} dup={duplicate_count} "
                f"answers={type_counter.get('answer', 0)} "
                f"articles={type_counter.get('article', 0)} "
                f"pins={type_counter.get('pin', 0)}"
                f"{'' if remaining_hint is None else f' remaining_hint={remaining_hint}'}"
                "[/dim]"
            )

            structural_progress = (
                raw_count != previous_raw_count
                or marker != previous_marker
                or tail != previous_tail
            )
            if unique_added == 0 and not structural_progress:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            previous_raw_count = raw_count
            previous_marker = marker
            previous_tail = tail

            if target_count > 0 and len(all_contents) >= target_count:
                all_contents = all_contents[:target_count]
                stop_reason = "target_count"
                break

            if not unlimited_mode and page_num >= max_pages:
                stop_reason = "max_pages"
                break

            has_next = self._goto_next_page(item_selector=item_selector)
            if has_next:
                no_next_rounds = 0
                continue

            no_next_rounds += 1
            should_drain = (
                no_next_rounds < self.MAX_NO_NEXT_ROUNDS
                and (
                    unique_added > 0
                    or structural_progress
                    or (
                        expected_total is not None
                        and len(all_contents) < expected_total
                    )
                )
            )
            if should_drain:
                remaining_hint = max(expected_total - len(all_contents), 0) if expected_total is not None else "unknown"
                console.print(
                    "[yellow]"
                    f"No next page detected, draining again (round={no_next_rounds}, remaining_hint={remaining_hint})."
                    "[/yellow]"
                )
                self.page.wait_for_timeout(300)
                continue

            if stagnant_rounds >= self.MAX_STAGNANT_ROUNDS:
                stop_reason = "stagnant_rounds"
            elif expected_total is not None and len(all_contents) < expected_total:
                stop_reason = "expected_total_gap"
            else:
                stop_reason = "no_next"
            break

        elapsed_sec = time.time() - start_time
        console.print(
            "[dim]"
            f"stop={stop_reason} pages={page_num} unique_total={len(all_contents)} "
            f"duplicates_total={duplicates_total} elapsed_sec={elapsed_sec:.1f}"
            "[/dim]"
        )

        if not all_contents:
            result.message = "No content fetched"
            return result

        files = self._save_contents(all_contents, f"author_{author_id}_{save_prefix}")
        gap = max(expected_total - len(all_contents), 0) if expected_total is not None else None
        result.success = True
        result.total_count = len(all_contents)
        result.contents = all_contents
        result.saved_files = files
        if expected_total is None:
            result.message = f"Fetched {len(all_contents)} items"
        else:
            result.message = (
                f"Fetched {len(all_contents)} items "
                f"(expected {expected_total}, gap {gap})"
            )
        return result

    def crawl_author_answers(
        self,
        author_id: str,
        max_pages: int = 10,
        target_count: int = 0,
        mode: str = "full",
        detail_workers: int = DEFAULT_DETAIL_WORKERS,
        detail_min_workers: int = DEFAULT_DETAIL_MIN_WORKERS,
        detail_max_workers: int = DEFAULT_DETAIL_MAX_WORKERS,
        detail_checkpoint_interval: int = DETAIL_CHECKPOINT_INTERVAL,
        detail_log_interval: int = DETAIL_LOG_INTERVAL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_batches: int = 0,
        resume: bool = True,
        max_empty_batches: int = DEFAULT_MAX_EMPTY_BATCHES,
        empty_batch_retry_delay_sec: int = DEFAULT_EMPTY_BATCH_RETRY_DELAY_SEC,
    ) -> CrawlResult:
        mode = (mode or "full").strip().lower()
        if mode not in {"index", "detail", "full"}:
            mode = "full"

        if mode == "index":
            return self._crawl_author_answers_index_only(
                author_id,
                max_pages=max_pages,
                target_count=target_count,
            )

        if mode == "detail":
            return self._crawl_author_answers_detail_only(
                author_id,
                batch_size=max(1, batch_size),
                max_batches=max_batches,
                detail_workers=max(1, detail_workers),
                detail_min_workers=max(1, detail_min_workers),
                detail_max_workers=max(1, detail_max_workers),
                detail_checkpoint_interval=max(20, detail_checkpoint_interval),
                detail_log_interval=max(20, detail_log_interval),
                resume=resume,
            )

        if max_pages <= 0:
            return self._crawl_author_answers_batched(
                author_id,
                target_count=target_count,
                batch_size=max(1, batch_size),
                max_batches=max_batches,
                resume=resume,
                detail_workers=max(1, detail_workers),
                detail_min_workers=max(1, detail_min_workers),
                detail_max_workers=max(1, detail_max_workers),
                detail_checkpoint_interval=max(20, detail_checkpoint_interval),
                detail_log_interval=max(20, detail_log_interval),
                max_empty_batches=max_empty_batches,
                empty_batch_retry_delay_sec=empty_batch_retry_delay_sec,
            )
        return self._crawl_author_answer_pipeline(
            author_id,
            max_pages=max_pages,
            target_count=target_count,
            detail_workers=max(1, detail_workers),
            detail_min_workers=max(1, detail_min_workers),
            detail_max_workers=max(1, detail_max_workers),
            detail_checkpoint_interval=max(20, detail_checkpoint_interval),
            detail_log_interval=max(20, detail_log_interval),
        )

    def crawl_author_articles(
        self,
        author_id: str,
        max_pages: int = 10,
        target_count: int = 0,
    ) -> CrawlResult:
        return self._crawl_author_listing(
            author_id=author_id,
            path_suffix="/posts",
            item_selector=".ArticleItem, .ContentItem",
            empty_selector=".EmptyState",
            save_prefix="articles",
            target_count=target_count,
            max_pages=max_pages,
        )

    def crawl_author_all_content(
        self,
        author_id: str,
        max_pages: int = 10,
        target_count: int = 0,
        mode: str = "full",
        detail_workers: int = DEFAULT_DETAIL_WORKERS,
        detail_min_workers: int = DEFAULT_DETAIL_MIN_WORKERS,
        detail_max_workers: int = DEFAULT_DETAIL_MAX_WORKERS,
        detail_checkpoint_interval: int = DETAIL_CHECKPOINT_INTERVAL,
        detail_log_interval: int = DETAIL_LOG_INTERVAL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_batches: int = 0,
        resume: bool = True,
        max_empty_batches: int = DEFAULT_MAX_EMPTY_BATCHES,
        empty_batch_retry_delay_sec: int = DEFAULT_EMPTY_BATCH_RETRY_DELAY_SEC,
    ) -> dict[str, CrawlResult]:
        console = self._get_console()
        console.print(f"\n[bold blue]Crawling all content for {author_id}[/bold blue]\n")

        results = {
            "answers": self.crawl_author_answers(
                author_id,
                max_pages=max_pages,
                target_count=target_count,
                mode=mode,
                detail_workers=detail_workers,
                detail_min_workers=detail_min_workers,
                detail_max_workers=detail_max_workers,
                detail_checkpoint_interval=detail_checkpoint_interval,
                detail_log_interval=detail_log_interval,
                batch_size=batch_size,
                max_batches=max_batches,
                resume=resume,
                max_empty_batches=max_empty_batches,
                empty_batch_retry_delay_sec=empty_batch_retry_delay_sec,
            ),
            "articles": self.crawl_author_articles(
                author_id,
                max_pages=max_pages,
                target_count=target_count,
            ),
        }
        total = sum(item.total_count for item in results.values())
        console.print(f"\n[bold green]Total fetched: {total}[/bold green]")
        return results
