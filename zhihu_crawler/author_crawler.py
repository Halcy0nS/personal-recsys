"""
作者内容爬虫模块
爬取特定作者的回答、文章、想法等内容
"""
import time
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin

from playwright.sync_api import Page
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from models import ZhihuContent, ZhihuAuthor, CrawlResult
from crawler import ZhihuCrawler


class AuthorCrawler(ZhihuCrawler):
    """作者内容爬虫"""

    HARD_PAGE_CAP = 5000
    INCREMENTAL_TAIL_WINDOW = 120
    INCREMENTAL_OVERLAP = 10

    def _get_incremental_start_index(self, current_count: int, previous_count: int) -> int:
        """根据当前/上轮列表长度计算增量抽取起始位。"""
        if previous_count <= 0:
            return 0
        if current_count > previous_count:
            return max(0, previous_count - self.INCREMENTAL_OVERLAP)
        return max(0, current_count - self.INCREMENTAL_TAIL_WINDOW)

    def crawl_author_answers(
        self,
        author_id: str,
        max_pages: int = 10,
        target_count: int = 0
    ) -> CrawlResult:
        """
        爬取作者的所有回答

        Args:
            author_id: 作者ID（如 'cjm926' 或数字ID）
            max_pages: 最大爬取页数
            target_count: 目标条数，>0 时达到后停止

        Returns:
            CrawlResult: 爬取结果
        """
        result = CrawlResult()

        # 构建URL
        url = f"https://www.zhihu.com/people/{author_id}/answers"
        console = self._get_console()
        console.print(f"[blue]开始爬取作者 {author_id} 的回答...[/blue]")
        console.print(f"[dim]{url}[/dim]")

        if not self._safe_goto(url, wait_until="domcontentloaded", retries=3):
            result.message = "作者回答页访问失败（网络或风控拦截）"
            return result
        time.sleep(3)

        # 检查是否有内容
        if self.page.locator(".EmptyState, .EmptyAnswers").count() > 0:
            result.message = "该作者没有回答"
            return result

        all_contents = []
        seen_keys: set[str] = set()
        duplicates_total = 0
        no_new_rounds = 0
        stop_reason = "unknown"
        start_time = time.time()

        unlimited_mode = max_pages <= 0
        page_limit = self.HARD_PAGE_CAP if unlimited_mode else max_pages

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:

            task = progress.add_task(f"[cyan]爬取回答中...", total=page_limit)
            page_num = 0
            previous_raw_count = 0

            while True:
                page_num += 1
                page_hint = "ALL" if unlimited_mode else str(max_pages)
                progress.update(task, description=f"[cyan]正在爬取第 {page_num}/{page_hint} 页...")
                unique_added = 0

                try:
                    # 等待内容加载
                    self.page.wait_for_selector(
                        ".ContentItem, .AnswerItem",
                        timeout=10000
                    )

                    raw_count = self.page.locator(".ContentItem, .AnswerItem").count()
                    start_index = self._get_incremental_start_index(raw_count, previous_raw_count)
                    contents = self._extract_page_contents(
                        ".ContentItem, .AnswerItem",
                        start_index=start_index
                    )
                    previous_raw_count = raw_count
                    unique_contents: List[ZhihuContent] = []
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

                    type_counter = {"answer": 0, "article": 0, "pin": 0}
                    for content in unique_contents:
                        if content.content_type in type_counter:
                            type_counter[content.content_type] += 1

                    progress.console.print(
                        f"[dim]第 {page_num} 页: 列表 {raw_count} 条，窗口提取 {len(contents)} 条（start={start_index}），新增 {unique_added} 条，重复 {duplicate_count} 条[/dim]"
                    )
                    progress.console.print(
                        "[dim]第 {} 页类型统计: answers={}, articles={}, pins={} url={}[/dim]".format(
                            page_num,
                            type_counter["answer"],
                            type_counter["article"],
                            type_counter["pin"],
                            self.page.url,
                        )
                    )

                except Exception as e:
                    progress.console.print(f"[yellow]第 {page_num} 页出错: {e}[/yellow]")
                    unique_added = 0

                if unique_added == 0:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0

                if target_count > 0:
                    remaining = target_count - len(all_contents)
                    if remaining < 0:
                        all_contents = all_contents[:target_count]
                    if len(all_contents) >= target_count:
                        stop_reason = "target_count"
                        progress.console.print(f"[dim]达到目标条数 {target_count}，结束爬取[/dim]")
                        break

                # 翻页
                if not unlimited_mode and page_num >= max_pages:
                    stop_reason = "max_pages"
                    progress.console.print("[dim]达到最大页数，结束爬取[/dim]")
                    break

                if no_new_rounds >= 2:
                    stop_reason = "no_new_rounds"
                    progress.console.print("[yellow]连续 2 轮无新增，结束爬取[/yellow]")
                    break

                if page_num >= self.HARD_PAGE_CAP:
                    stop_reason = "hard_cap"
                    progress.console.print(f"[yellow]达到安全上限 {self.HARD_PAGE_CAP} 轮，结束爬取[/yellow]")
                    break

                progress.console.print(
                    f"[dim]第 {page_num} 页准备翻页，marker={self._get_page_marker()[:120]}[/dim]"
                )
                has_next = self._goto_next_page()
                if not has_next and unique_added == 0:
                    stop_reason = "no_next_and_no_new"
                    progress.console.print("[yellow]已到达最后一页（且本轮无新增）[/yellow]")
                    break
                if not has_next and unique_added > 0:
                    progress.console.print("[yellow]未检测到下一页，但本轮有新增，将继续尝试[/yellow]")

                if has_next:
                    progress.update(task, advance=1)
                else:
                    progress.update(task, advance=0)

        elapsed_sec = time.time() - start_time
        console.print(
            "[dim]结束原因: stop={} pages_visited={} unique_total={} duplicates_total={} elapsed_sec={:.1f}[/dim]".format(
                stop_reason,
                page_num,
                len(all_contents),
                duplicates_total,
                elapsed_sec,
            )
        )

        # 保存数据
        if all_contents:
            files = self._save_contents(all_contents, f"author_{author_id}_answers")
            result.success = True
            result.total_count = len(all_contents)
            result.contents = all_contents
            result.saved_files = files
            result.message = f"成功爬取 {len(all_contents)} 条回答"
        else:
            result.message = "未获取到任何回答"

        return result

    def crawl_author_articles(
        self,
        author_id: str,
        max_pages: int = 10,
        target_count: int = 0
    ) -> CrawlResult:
        """
        爬取作者的所有文章

        Args:
            author_id: 作者ID
            max_pages: 最大爬取页数
            target_count: 目标条数，>0 时达到后停止

        Returns:
            CrawlResult: 爬取结果
        """
        result = CrawlResult()

        url = f"https://www.zhihu.com/people/{author_id}/posts"
        console = self._get_console()
        console.print(f"[blue]开始爬取作者 {author_id} 的文章...[/blue]")
        console.print(f"[dim]{url}[/dim]")

        if not self._safe_goto(url, wait_until="domcontentloaded", retries=3):
            result.message = "作者文章页访问失败（网络或风控拦截）"
            return result
        time.sleep(3)

        # 作者页头诊断信息（仅观测）
        page_title = self.page.title()
        posts_tab_text = ""
        posts_tab_selectors = [
            "a[href$='/posts']",
            "a[href*='/posts']",
            "a:has-text('文章')",
        ]
        for selector in posts_tab_selectors:
            tab = self.page.query_selector(selector)
            if tab:
                posts_tab_text = tab.inner_text().strip()
                if posts_tab_text:
                    break

        initial_items = self.page.locator(".ArticleItem, .ContentItem").count()
        console.print(
            "[dim]作者页头: title='{}' posts_tab='{}' initial_items={} current_url={}[/dim]".format(
                page_title,
                posts_tab_text,
                initial_items,
                self.page.url,
            )
        )

        # 检查是否有内容
        if self.page.locator(".EmptyState").count() > 0:
            result.message = "该作者没有文章"
            return result

        all_contents = []
        seen_keys: set[str] = set()
        duplicates_total = 0
        no_new_rounds = 0
        stop_reason = "unknown"
        start_time = time.time()

        unlimited_mode = max_pages <= 0
        page_limit = self.HARD_PAGE_CAP if unlimited_mode else max_pages

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:

            task = progress.add_task(f"[cyan]爬取文章中...", total=page_limit)
            page_num = 0
            previous_raw_count = 0

            while True:
                page_num += 1
                page_hint = "ALL" if unlimited_mode else str(max_pages)
                progress.update(task, description=f"[cyan]正在爬取第 {page_num}/{page_hint} 页...")
                unique_added = 0

                try:
                    self.page.wait_for_selector(
                        ".ArticleItem, .ContentItem",
                        timeout=10000
                    )

                    raw_count = self.page.locator(".ArticleItem, .ContentItem").count()
                    start_index = self._get_incremental_start_index(raw_count, previous_raw_count)
                    contents = self._extract_page_contents(
                        ".ArticleItem, .ContentItem",
                        start_index=start_index
                    )
                    previous_raw_count = raw_count
                    unique_contents: List[ZhihuContent] = []
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

                    type_counter = {"answer": 0, "article": 0, "pin": 0}
                    for content in unique_contents:
                        if content.content_type in type_counter:
                            type_counter[content.content_type] += 1

                    progress.console.print(
                        f"[dim]第 {page_num} 页: 列表 {raw_count} 条，窗口提取 {len(contents)} 条（start={start_index}），新增 {unique_added} 篇，重复 {duplicate_count} 篇[/dim]"
                    )
                    progress.console.print(
                        "[dim]第 {} 页类型统计: answers={}, articles={}, pins={} url={}[/dim]".format(
                            page_num,
                            type_counter["answer"],
                            type_counter["article"],
                            type_counter["pin"],
                            self.page.url,
                        )
                    )

                except Exception as e:
                    progress.console.print(f"[yellow]第 {page_num} 页出错: {e}[/yellow]")
                    unique_added = 0

                if unique_added == 0:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0

                if target_count > 0:
                    remaining = target_count - len(all_contents)
                    if remaining < 0:
                        all_contents = all_contents[:target_count]
                    if len(all_contents) >= target_count:
                        stop_reason = "target_count"
                        progress.console.print(f"[dim]达到目标条数 {target_count}，结束爬取[/dim]")
                        break

                if not unlimited_mode and page_num >= max_pages:
                    stop_reason = "max_pages"
                    progress.console.print("[dim]达到最大页数，结束爬取[/dim]")
                    break

                if no_new_rounds >= 2:
                    stop_reason = "no_new_rounds"
                    progress.console.print("[yellow]连续 2 轮无新增，结束爬取[/yellow]")
                    break

                if page_num >= self.HARD_PAGE_CAP:
                    stop_reason = "hard_cap"
                    progress.console.print(f"[yellow]达到安全上限 {self.HARD_PAGE_CAP} 轮，结束爬取[/yellow]")
                    break

                progress.console.print(
                    f"[dim]第 {page_num} 页准备翻页，marker={self._get_page_marker()[:120]}[/dim]"
                )
                has_next = self._goto_next_page()
                if not has_next and unique_added == 0:
                    stop_reason = "no_next_and_no_new"
                    current_items = self.page.locator(".ArticleItem, .ContentItem").count()
                    progress.console.print(
                        "[yellow]退出摘要: page={} has_next={} url={} marker={} current_items={}[/yellow]".format(
                            page_num,
                            has_next,
                            self.page.url,
                            self._get_page_marker()[:120],
                            current_items,
                        )
                    )
                    progress.console.print("[yellow]已到达最后一页（且本轮无新增）[/yellow]")
                    break
                if not has_next and unique_added > 0:
                    progress.console.print("[yellow]未检测到下一页，但本轮有新增，将继续尝试[/yellow]")

                if has_next:
                    progress.update(task, advance=1)
                else:
                    progress.update(task, advance=0)

        elapsed_sec = time.time() - start_time
        console.print(
            "[dim]结束原因: stop={} pages_visited={} unique_total={} duplicates_total={} elapsed_sec={:.1f}[/dim]".format(
                stop_reason,
                page_num,
                len(all_contents),
                duplicates_total,
                elapsed_sec,
            )
        )

        # 保存数据
        if all_contents:
            files = self._save_contents(all_contents, f"author_{author_id}_articles")
            result.success = True
            result.total_count = len(all_contents)
            result.contents = all_contents
            result.saved_files = files
            result.message = f"成功爬取 {len(all_contents)} 篇文章"
        else:
            result.message = "未获取到任何文章"

        return result

    def crawl_author_all_content(
        self,
        author_id: str,
        max_pages: int = 10,
        target_count: int = 0
    ) -> Dict[str, CrawlResult]:
        """
        爬取作者的所有类型内容（回答 + 文章）

        Args:
            author_id: 作者ID
            max_pages: 每种类型的最大页数
            target_count: 每种类型目标条数，>0 时达到后停止

        Returns:
            Dict[str, CrawlResult]: 各类型的爬取结果
        """
        results = {}

        console = self._get_console()
        console.print(f"\n[bold blue]开始爬取作者 {author_id} 的所有内容...[/bold blue]\n")

        # 1. 爬取回答
        console.print("[cyan]▶ 正在爬取回答...[/cyan]")
        results["answers"] = self.crawl_author_answers(author_id, max_pages, target_count=target_count)

        # 2. 爬取文章
        console.print("[cyan]▶ 正在爬取文章...[/cyan]")
        results["articles"] = self.crawl_author_articles(author_id, max_pages, target_count=target_count)

        # 汇总
        total = sum(r.total_count for r in results.values())
        console.print(f"\n[bold green]✓ 总计爬取 {total} 条内容[/bold green]")

        return results
