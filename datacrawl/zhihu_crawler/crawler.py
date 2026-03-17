"""
知乎爬虫核心类
"""
import json
import time
import re
import random
from html import unescape
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Locator
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from models import ZhihuContent, ZhihuAuthor, CrawlResult
from utils.saver import DataSaver
from config import crawl_config

console = Console()


class ZhihuCrawler:
    """知乎爬虫主类"""

    AUTH_RESOURCE_MARKERS = (
        "/signin",
        "captcha",
        "verify",
        "verification",
        "login",
        "qr",
        "qrcode",
    )

    def __init__(self, headless: bool = False, data_dir: str = "./data"):
        self.headless = headless
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cookies_file = self.data_dir / "cookies.json"

        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.current_delay = float(crawl_config.delay_between_requests)
        self.request_ok_streak = 0
        self.request_fail_streak = 0

        self.saver = DataSaver(data_dir)

    def start(self):
        """启动浏览器"""
        if self.page is not None:
            return

        self.playwright = sync_playwright().start()

        # 启动浏览器（使用 Chromium）
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
            ]
        )

        # 创建上下文（类似无痕窗口）
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        # 注入反检测脚本
        self._inject_anti_detection()
        self._install_network_optimizations()
        self.page = self.context.new_page()

        # 加载已保存的 cookies
        if self.cookies_file.exists():
            self._load_cookies()

    def _inject_anti_detection(self):
        """注入反检测脚本，隐藏自动化特征"""
        if not self.context:
            return
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {name: 'Chrome PDF Plugin'},
                    {name: 'Native Client'},
                    {name: 'Widevine Content Decryption Module'}
                ]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en']
            });
            window.chrome = { runtime: {} };
        """)

    def _install_network_optimizations(self):
        """屏蔽非必要资源，降低详情页加载开销。"""
        if not self.context:
            return
        blocked = set(crawl_config.block_resource_types)
        if not blocked:
            return

        def _route_filter(route):
            try:
                resource_type = route.request.resource_type
                request_url = route.request.url or ""
                current_url = self.page.url if self.page else ""
                allow_for_auth = self._is_auth_related_url(request_url) or self._is_auth_related_url(current_url)
                if resource_type in blocked and not allow_for_auth:
                    route.abort()
                    return
            except Exception:
                pass
            route.continue_()

        try:
            self.context.route("**/*", _route_filter)
        except Exception as e:
            self._debug_log(f"_install_network_optimizations failed: {e}")

    def _is_auth_related_url(self, url: str) -> bool:
        normalized = (url or "").strip().lower()
        return any(marker in normalized for marker in self.AUTH_RESOURCE_MARKERS)

    def _record_request_outcome(self, success: bool):
        """根据最近请求结果动态调节节流间隔。"""
        if success:
            self.request_ok_streak += 1
            self.request_fail_streak = 0
            if self.request_ok_streak >= 3:
                self.current_delay = max(
                    float(crawl_config.min_delay_between_requests),
                    self.current_delay * 0.92,
                )
        else:
            self.request_ok_streak = 0
            self.request_fail_streak += 1
            factor = 1.25 + min(self.request_fail_streak, 4) * 0.1
            self.current_delay = min(
                float(crawl_config.max_delay_between_requests),
                max(float(crawl_config.delay_between_requests), self.current_delay) * factor,
            )

    def _sleep_with_throttle(self):
        """节流等待（含抖动），用于翻页/详情抓取之间降压。"""
        base_delay = max(
            float(crawl_config.min_delay_between_requests),
            min(float(crawl_config.max_delay_between_requests), self.current_delay),
        )
        jitter_ratio = max(0.0, float(crawl_config.throttle_jitter_ratio))
        jitter = base_delay * jitter_ratio
        sleep_sec = max(0.0, base_delay + random.uniform(-jitter, jitter))
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    def _load_cookies(self):
        """加载 Cookie 恢复登录态"""
        try:
            with open(self.cookies_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
                self.context.add_cookies(cookies)
            console.print("[green]✓ 已加载登录态[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ 加载Cookie失败: {e}[/yellow]")

    def _save_cookies(self):
        """保存 Cookie"""
        try:
            cookies = self.context.cookies()
            with open(self.cookies_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            console.print("[green]✓ 登录态已保存[/green]")
        except Exception as e:
            console.print(f"[red]✗ 保存Cookie失败: {e}[/red]")

    def _safe_goto(
        self,
        url: str,
        timeout: int = 45000,
        wait_until: str = "domcontentloaded",
        retries: int = 3,
        base_delay: float = 1.5,
    ) -> bool:
        """带重试的导航，避免临时网络错误直接中断流程。"""
        last_error = ""
        for attempt in range(1, retries + 1):
            try:
                self.page.goto(url, timeout=timeout, wait_until=wait_until)
                self._record_request_outcome(True)
                return True
            except Exception as e:
                last_error = str(e)
                self._record_request_outcome(False)
                console.print(
                    "[yellow]⚠ 页面打开失败 ({}/{}): {} -> {}[/yellow]".format(
                        attempt,
                        retries,
                        url,
                        last_error[:160],
                    )
                )
                if attempt < retries:
                    time.sleep(base_delay * attempt + min(self.current_delay, 1.2))

        console.print(f"[red]✗ 页面打开失败，已重试 {retries} 次: {url}[/red]")
        return False

    def login(self):
        """手动登录流程"""
        console.print("\n[blue]请在浏览器中完成登录...[/blue]")
        console.print("[dim]支持方式：扫码 / 手机号 / 密码[/dim]\n")

        if not self._safe_goto("https://www.zhihu.com/signin", wait_until="domcontentloaded", retries=3):
            return False

        # 等待登录成功（URL 变化）
        try:
            self.page.wait_for_url(lambda url: "/signin" not in url, timeout=300000)
            console.print("[green]✓ 登录成功！[/green]")
            self._save_cookies()
            return True
        except Exception as e:
            console.print(f"[red]✗ 登录超时或失败: {e}[/red]")
            return False

    def _is_login_or_challenge_page(self) -> bool:
        """检测是否跳转到登录/验证页面。"""
        if not self.page:
            return True
        challenge_markers = (
            "安全验证",
            "进入知乎",
            "开始验证",
            "网络环境存在异常",
            "扫码登录",
            "登录知乎",
        )
        if "/signin" in (self.page.url or ""):
            return True
        try:
            title = self.page.title()
        except Exception:
            title = ""
        if any(marker in title for marker in challenge_markers):
            return True
        try:
            body_text = self.page.locator("body").inner_text(timeout=800)
        except Exception:
            body_text = ""
        return any(marker in body_text for marker in challenge_markers)

    def ensure_login(self):
        """确保已登录"""
        if not self._safe_goto("https://www.zhihu.com", wait_until="domcontentloaded", retries=3):
            console.print("[yellow]⚠ 主页访问失败，尝试直接进入登录页[/yellow]")
            if not self._safe_goto("https://www.zhihu.com/signin", wait_until="domcontentloaded", retries=2):
                return False

        time.sleep(2)

        # 检查是否已登录（查找头像元素）
        try:
            if self._is_login_or_challenge_page():
                console.print("[yellow]⚠ 当前处于登录页，开始登录流程[/yellow]")
                return self.login()

            # Cookie 启发式：有核心登录 cookie 且未跳转 signin，视为已登录。
            # 用于应对头像选择器变更导致的误判。
            try:
                cookies = self.context.cookies()
            except Exception:
                cookies = []
            cookie_names = {cookie.get("name", "") for cookie in cookies}
            if {"z_c0", "d_c0"} & cookie_names:
                console.print("[green]✓ 当前已登录 (cookie 检测)[/green]")
                return True

            # 多个可能的选择器
            selectors = [
                "[data-za-detail-view-path-module='UserAvatar']",
                ".AppHeader-profile",
                "button[aria-label='个人中心']",
                ".ProfileHeader-avatar"
            ]

            for selector in selectors:
                if self.page.locator(selector).count() > 0:
                    console.print("[green]✓ 当前已登录[/green]")
                    return True

            # 没找到登录元素，需要登录
            console.print("[yellow]⚠ 未登录，开始登录流程[/yellow]")
            return self.login()

        except Exception as e:
            console.print(f"[yellow]⚠ 检查登录状态出错: {e}[/yellow]")
            return self.login()

    def _parse_content_item(self, item) -> Optional[ZhihuContent]:
        """
        解析内容项（回答/文章/想法）- 从列表页提取信息
        注意：这只是从列表页提取的摘要信息，不是完整内容
        如需完整内容，需要点击详情页

        Args:
            item: Playwright 元素句柄

        Returns:
            ZhihuContent: 解析后的内容对象，解析失败返回 None
        """
        try:
            content = ZhihuContent()

            # 1. 确定内容类型
            content_type = "answer"
            item_html = item.inner_html()
            if "ArticleItem" in item_html or "/p/" in item_html:
                content_type = "article"
            elif "PinItem" in item_html or "想法" in item_html:
                content_type = "pin"
            content.content_type = content_type

            # 2. 提取标题
            title_selectors = [
                ".ContentItem-title",
                ".AnswerItem-title",
                ".ArticleItem-title",
                "h2.ContentItem-title",
                ".Title",
                "h2",
                "h3"
            ]

            for selector in title_selectors:
                title_elem = item.query_selector(selector)
                if title_elem:
                    title = title_elem.inner_text().strip()
                    if title and len(title) < 500:
                        content.title = title
                        break

            # 3. 提取内容摘要（从列表页能看到的部分）
            content_selectors = [
                ".RichContent-inner",
                ".RichContent",
                ".ContentItem-content",
                ".AnswerItem-content",
                ".ArticleItem-content",
                ".ContentItem-html"
            ]

            for selector in content_selectors:
                content_elem = item.query_selector(selector)
                if content_elem:
                    text = content_elem.inner_text().strip()
                    content.excerpt = text[:500] if len(text) > 500 else text
                    content.content = text[:2000] if len(text) > 2000 else text
                    content.content_text = text
                    try:
                        content.content_html = content_elem.inner_html() or ""
                    except Exception:
                        content.content_html = ""
                    break

            # 4. 提取作者信息
            author = ZhihuAuthor()
            author_selectors = [
                ".AuthorInfo-name",
                ".UserLink-link",
                ".AuthorInfo-content .AuthorInfo-name",
                ".ContentItem-author",
                ".AuthorInfo-link"
            ]

            for selector in author_selectors:
                author_elem = item.query_selector(selector)
                if author_elem:
                    name = author_elem.inner_text().strip()
                    if name:
                        author.name = name
                        break

            # 作者链接和ID
            author_link = item.query_selector("a.AuthorInfo-avatar, a.UserLink-link, .AuthorInfo a, .AuthorInfo-avatar")
            if author_link:
                href = author_link.get_attribute("href") or ""
                author.url = self._normalize_zhihu_href(href)
                if "/people/" in href:
                    author.id = href.split("/people/")[-1].split("/")[0]

            content.author = author

            # 5. 提取互动数据
            # 点赞数
            vote_selectors = [
                ".VoteButton--up",
                ".ContentItem-actions .VoteButton",
                "[data-za-detail-view-element_name='VoteUp']",
                ".VoteButton--up--active"
            ]

            for selector in vote_selectors:
                vote_elem = item.query_selector(selector)
                if vote_elem:
                    text = vote_elem.inner_text()
                    match = re.search(r'(\d+)', text.replace(",", ""))
                    if match:
                        content.voteup_count = int(match.group(1))
                        break

            # 评论数
            comment_selectors = [
                ".ContentItem-action .CommentButton",
                "button[data-za-detail-view-element_name='Comment']",
                ".ContentItem-actions button:has-text('评论')",
                ".Comments-button"
            ]

            for selector in comment_selectors:
                comment_elem = item.query_selector(selector)
                if comment_elem:
                    text = comment_elem.inner_text()
                    match = re.search(r'(\d+)', text.replace(",", ""))
                    if match:
                        content.comment_count = int(match.group(1))
                        break

            # 6. 提取链接和ID
            link_selectors = [
                "a.ContentItem-title",
                "a.QuestionLink",
                ".ContentItem-title a",
                "a[href*='question']",
                "a[href*='answer']",
                "a[href*='/p/']",
                ".ContentItem-title-link"
            ]

            for selector in link_selectors:
                link_elem = item.query_selector(selector)
                if link_elem:
                    href = link_elem.get_attribute("href") or ""
                    if href:
                        content.url = self._normalize_zhihu_href(href)
                        if "/answer/" in href:
                            content.id = href.split("/answer/")[-1].split("/")[0].split("?")[0]
                        elif "/p/" in href:
                            content.id = href.split("/p/")[-1].split("/")[0].split("?")[0]
                        break

            # 7. 提取时间信息
            time_selectors = [
                ".ContentItem-time",
                "time",
                ".ContentItem-metadata time",
                "[data-za-detail-view-element_name='Time']",
                ".ContentItem-publishTime"
            ]

            for selector in time_selectors:
                time_elem = item.query_selector(selector)
                if time_elem:
                    time_text = time_elem.inner_text().strip()
                    if time_text:
                        content.created_time = time_text
                        break

            # 验证必要字段
            if not content.id and not content.url:
                content.id = f"unknown_{id(item)}"
            if not content.content_text:
                content.content_text = content.content or content.excerpt

            question_id = ""
            if content.url and "/question/" in content.url:
                match = re.search(r"/question/(\d+)", content.url)
                if match:
                    question_id = match.group(1)
            author_token = content.author.id if content.author else ""
            content.metadata.setdefault("source_stage", "list")
            content.metadata.setdefault("detail_source", "summary_only")
            content.metadata.setdefault("question_id", question_id)
            content.metadata.setdefault("author_url_token", author_token)
            content.metadata.setdefault("expected_total_at_run", None)

            return content

        except Exception as e:
            console.print(f"[dim red]解析内容项失败: {e}[/dim red]")
            return None

    def _build_dedup_key(self, content: ZhihuContent) -> str:
        """构建内容去重键，优先级: id > url > title+author。"""
        if content.id and not content.id.startswith("unknown_"):
            return f"id:{content.id}"
        if content.url:
            return f"url:{content.url}"

        title = (content.title or "").strip()
        author = (content.author.name or "").strip() if content.author else ""
        if title or author:
            return f"title_author:{title}::{author}"

        excerpt = (content.excerpt or "").strip()
        if excerpt:
            return f"excerpt:{excerpt[:80]}"
        return f"fallback:{id(content)}"

    def _debug_log(self, message: str):
        """统一调试日志输出。"""
        if not crawl_config.debug_logging:
            return
        console.print(f"[dim cyan][debug][/dim cyan] {message}")

    def _normalize_zhihu_href(self, href: str) -> str:
        """标准化知乎链接，避免出现双域名或协议缺失。"""
        href = (href or "").strip()
        if not href:
            return ""

        if href.startswith(("http://", "https://")):
            return href
        if href.startswith("//"):
            return f"https:{href}"
        if href.startswith("/www.zhihu.com") or href.startswith("www.zhihu.com"):
            return f"https://{href.lstrip('/')}"
        return urljoin("https://www.zhihu.com", href)

    def _describe_locator(self, locator: Locator) -> str:
        """提取定位元素的关键信息，便于诊断。"""
        try:
            text = (locator.inner_text() or "").strip().replace("\n", " ")[:40]
        except Exception:
            text = ""
        try:
            class_name = (locator.get_attribute("class") or "")[:120]
        except Exception:
            class_name = ""
        return f"text='{text}' class='{class_name}'"

    def _debug_navigation_snapshot(self, context: str):
        """输出页面导航相关快照，用于诊断分页模型。"""
        marker = self._get_page_marker()[:160]
        nav_selectors = {
            "items": ".ArticleItem, .ContentItem",
            "pagination_class": "[class*='Pagination']",
            "load_more_button": "button:has-text('加载更多')",
            "next_rel": "a[rel='next']",
            "load_more_class": "[class*='LoadMore']",
            "next_button": ".PaginationButton-next",
        }

        counts = {}
        for name, selector in nav_selectors.items():
            try:
                counts[name] = self.page.locator(selector).count()
            except Exception:
                counts[name] = -1

        try:
            metrics = self.page.evaluate(
                """() => ({
                    scrollY: window.scrollY || 0,
                    innerHeight: window.innerHeight || 0,
                    scrollHeight: (document.documentElement && document.documentElement.scrollHeight) || 0
                })"""
            )
        except Exception:
            metrics = {"scrollY": -1, "innerHeight": -1, "scrollHeight": -1}

        self._debug_log(
            "navigation_snapshot context={} url='{}' marker='{}'".format(
                context,
                self.page.url,
                marker,
            )
        )
        self._debug_log(
            "navigation_snapshot counts items={} pagination_class={} load_more_button={} next_rel={} load_more_class={} next_button={}".format(
                counts["items"],
                counts["pagination_class"],
                counts["load_more_button"],
                counts["next_rel"],
                counts["load_more_class"],
                counts["next_button"],
            )
        )
        self._debug_log(
            "navigation_snapshot scroll scrollY={} innerHeight={} scrollHeight={}".format(
                metrics.get("scrollY", -1),
                metrics.get("innerHeight", -1),
                metrics.get("scrollHeight", -1),
            )
        )

    def _extract_page_contents(
        self,
        item_selector: str = ".ContentItem, .AnswerItem, .ArticleItem, .PinItem",
        start_index: int = 0,
        max_items: Optional[int] = None,
    ) -> List[ZhihuContent]:
        """提取当前页内容并在页内去重。"""
        contents: List[ZhihuContent] = []
        dedup_keys: set = set()
        parse_failed = 0
        dedup_skipped = 0

        all_items = self.page.query_selector_all(item_selector)
        raw_total = len(all_items)
        safe_start = max(0, min(start_index, raw_total))
        safe_end = raw_total if max_items is None else min(raw_total, safe_start + max_items)
        scan_items = all_items[safe_start:safe_end]

        for item in scan_items:
            content = self._parse_content_item(item)
            if not content:
                parse_failed += 1
                continue

            dedup_key = self._build_dedup_key(content)
            if dedup_key in dedup_keys:
                dedup_skipped += 1
                continue
            dedup_keys.add(dedup_key)
            contents.append(content)

        self._debug_log(
            "_extract_page_contents selector='{}' raw_items={} scan_start={} scan_size={} parsed={} dedup_skipped={} parse_failed={}".format(
                item_selector,
                raw_total,
                safe_start,
                len(scan_items),
                len(contents),
                dedup_skipped,
                parse_failed,
            )
        )
        return contents

    def _get_page_marker(self) -> str:
        """提取页面标记，用于判断翻页后内容是否变化。"""
        base_url = self.page.url.split("#")[0]
        markers: List[str] = []

        link_selector = "a[href*='/answer/'], a[href*='/p/'], a[href*='/question/']"
        link_locator = self.page.locator(link_selector)
        sample_count = min(link_locator.count(), 5)
        for idx in range(sample_count):
            href = (link_locator.nth(idx).get_attribute("href") or "").strip()
            if not href:
                continue
            markers.append(self._normalize_zhihu_href(href))

        if not markers:
            first_item = self.page.locator(".ContentItem, .AnswerItem, .ArticleItem, .PinItem").first
            if first_item.count() > 0:
                text = first_item.inner_text().strip().replace("\n", " ")
                if text:
                    markers.append(text[:80])

        return f"{base_url}||{'|'.join(markers)}"

    def _find_next_page_button(self) -> Optional[Locator]:
        """查找可见的下一页按钮。"""
        next_selectors = [
            ".PaginationButton-next",
            "button:has-text('下一页')",
            "a:has-text('下一页')",
            "button[aria-label='下一页']",
            "button:has-text('Next')",
            "a[rel='next']",
        ]

        for selector in next_selectors:
            locator = self.page.locator(selector)
            count = locator.count()
            self._debug_log(f"_find_next_page_button selector='{selector}' count={count}")

            inspect_count = min(count, 3)
            for idx in range(inspect_count):
                candidate = locator.nth(idx)
                try:
                    visible = candidate.is_visible()
                except Exception:
                    visible = False

                try:
                    enabled = candidate.is_enabled()
                except Exception:
                    enabled = False

                try:
                    aria_disabled = candidate.get_attribute("aria-disabled")
                except Exception:
                    aria_disabled = None

                self._debug_log(
                    "_find_next_page_button candidate selector='{}' idx={} visible={} enabled={} aria-disabled={} {}".format(
                        selector,
                        idx,
                        visible,
                        enabled,
                        aria_disabled,
                        self._describe_locator(candidate),
                    )
                )

                if visible:
                    self._debug_log(
                        "_find_next_page_button picked selector='{}' idx={} {}".format(
                            selector,
                            idx,
                            self._describe_locator(candidate),
                        )
                    )
                    return candidate
        self._debug_log("_find_next_page_button no visible next button found")
        return None

    def _is_next_page_button_disabled(self, button: Locator) -> bool:
        """判断下一页按钮是否为禁用状态。"""
        try:
            if button.is_disabled():
                self._debug_log(f"_is_next_page_button_disabled via is_disabled=True {self._describe_locator(button)}")
                return True
        except Exception:
            pass

        aria_disabled = (button.get_attribute("aria-disabled") or "").lower()
        if aria_disabled == "true":
            self._debug_log(f"_is_next_page_button_disabled via aria-disabled=true {self._describe_locator(button)}")
            return True

        if button.get_attribute("disabled") is not None:
            self._debug_log(f"_is_next_page_button_disabled via disabled attr {self._describe_locator(button)}")
            return True

        class_name = (button.get_attribute("class") or "").lower()
        disabled_tokens = ["disabled", "is-disabled", "button--disabled"]
        by_class = any(token in class_name for token in disabled_tokens)
        if by_class:
            self._debug_log(f"_is_next_page_button_disabled via class token {self._describe_locator(button)}")
        return by_class

    def _wait_for_page_marker_change(self, previous_marker: str, timeout_sec: float = 8.0) -> bool:
        """等待页面标记变化，用于判断翻页成功。"""
        self._debug_log(f"_wait_for_page_marker_change start marker='{previous_marker[:120]}' timeout={timeout_sec}s")
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(0.4)
            try:
                current_marker = self._get_page_marker()
            except Exception:
                continue
            if current_marker != previous_marker:
                self._debug_log(f"_wait_for_page_marker_change changed to='{current_marker[:120]}'")
                return True
        try:
            current_marker = self._get_page_marker()
        except Exception:
            current_marker = "N/A"
        self._debug_log(f"_wait_for_page_marker_change timeout current='{str(current_marker)[:120]}'")
        return False

    def _get_item_tail_signature(self, item_selector: str, sample_size: int = 5) -> str:
        """
        获取列表尾部内容签名，用于识别“条目变了但数量不变”的虚拟列表场景。
        """
        item_locator = self.page.locator(item_selector)
        try:
            total = item_locator.count()
        except Exception:
            total = 0

        if total <= 0:
            return ""

        start_idx = max(0, total - sample_size)
        parts: List[str] = []
        link_selector = "a[href*='/answer/'], a[href*='/p/'], a[href*='/question/']"

        for idx in range(start_idx, total):
            token = ""
            item = item_locator.nth(idx)
            try:
                link = item.locator(link_selector).first
                if link.count() > 0:
                    href = (link.get_attribute("href") or "").strip()
                    if href:
                        token = self._normalize_zhihu_href(href)
            except Exception:
                pass

            if not token:
                try:
                    text = item.inner_text().strip().replace("\n", " ")
                    token = text[:80]
                except Exception:
                    token = ""

            parts.append(token)

        return "|".join(parts)

    def _try_infinite_scroll_load(
        self,
        item_selector: str = ".ContentItem, .AnswerItem, .ArticleItem, .PinItem"
    ) -> bool:
        """
        无限滚动兜底：当页面没有“下一页”按钮时，尝试滚动触发懒加载。
        仅用于观测到无分页控件的页面，不替代正常分页逻辑。
        """
        try:
            before_count = self.page.locator(item_selector).count()
        except Exception:
            before_count = 0
        before_marker = self._get_page_marker()
        before_tail_signature = self._get_item_tail_signature(item_selector)
        try:
            before_scroll_height = self.page.evaluate(
                "() => (document.documentElement && document.documentElement.scrollHeight) || 0"
            )
        except Exception:
            before_scroll_height = 0
        self._debug_log(
            "_try_infinite_scroll_load start before_count={} scroll_height={} marker='{}' tail='{}'".format(
                before_count,
                before_scroll_height,
                before_marker[:120],
                before_tail_signature[:120],
            )
        )

        # 先尝试点击“加载更多”按钮（如果存在）
        load_more_selectors = [
            "button:has-text('加载更多')",
            "button:has-text('更多')",
            "[class*='LoadMore'] button",
            "a:has-text('加载更多')",
        ]
        for selector in load_more_selectors:
            locator = self.page.locator(selector)
            count = locator.count()
            if count <= 0:
                continue
            self._debug_log(f"_try_infinite_scroll_load load_more selector='{selector}' count={count}")
            for idx in range(min(count, 2)):
                candidate = locator.nth(idx)
                try:
                    if candidate.is_visible() and candidate.is_enabled():
                        candidate.click(timeout=3000)
                        self._sleep_with_throttle()
                        try:
                            after_click_count = self.page.locator(item_selector).count()
                        except Exception:
                            after_click_count = before_count
                        after_click_marker = self._get_page_marker()
                        after_click_tail = self._get_item_tail_signature(item_selector)
                        self._debug_log(
                            "_try_infinite_scroll_load load_more clicked idx={} after_count={} marker_changed={} tail_changed={}".format(
                                idx,
                                after_click_count,
                                after_click_marker != before_marker,
                                after_click_tail != before_tail_signature,
                            )
                        )
                        if (
                            after_click_count > before_count
                            or after_click_marker != before_marker
                            or after_click_tail != before_tail_signature
                        ):
                            return True
                except Exception as e:
                    self._debug_log(
                        f"_try_infinite_scroll_load load_more click failed selector='{selector}' idx={idx} error='{str(e)[:160]}'"
                    )

        # 再尝试滚动触发懒加载
        scroll_container_selectors = [
            ".Profile-mainColumn",
            ".Profile-main",
            ".List",
            "[class*='List']",
            "[class*='Content']",
        ]

        for step in range(1, 9):
            try:
                self.page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            except Exception:
                try:
                    self.page.mouse.wheel(0, 2500)
                except Exception:
                    pass

            # 一些页面把滚动绑定在内部容器，不是 window
            for selector in scroll_container_selectors:
                try:
                    locator = self.page.locator(selector)
                    if locator.count() <= 0:
                        continue
                    target = locator.first
                    if not target.is_visible():
                        continue
                    target.evaluate(
                        """(el) => {
                            el.scrollTop = el.scrollHeight;
                        }"""
                    )
                except Exception:
                    continue

            self._sleep_with_throttle()
            try:
                self.page.wait_for_load_state("networkidle", timeout=2500)
            except Exception:
                pass

            try:
                current_count = self.page.locator(item_selector).count()
            except Exception:
                current_count = before_count
            current_marker = self._get_page_marker()
            current_tail_signature = self._get_item_tail_signature(item_selector)
            try:
                current_scroll_height = self.page.evaluate(
                    "() => (document.documentElement && document.documentElement.scrollHeight) || 0"
                )
            except Exception:
                current_scroll_height = before_scroll_height

            self._debug_log(
                "_try_infinite_scroll_load step={} current_count={} marker_changed={} tail_changed={} scroll_height={}".format(
                    step,
                    current_count,
                    current_marker != before_marker,
                    current_tail_signature != before_tail_signature,
                    current_scroll_height,
                )
            )

            if (
                current_count > before_count
                or current_marker != before_marker
                or current_tail_signature != before_tail_signature
                or current_scroll_height > before_scroll_height + 150
            ):
                self._debug_log("_try_infinite_scroll_load success")
                return True

        self._debug_log("_try_infinite_scroll_load no additional content loaded")
        return False

    def _goto_next_page(
        self,
        item_selector: str = ".ContentItem, .AnswerItem, .ArticleItem, .PinItem"
    ) -> bool:
        """
        翻到下一页。
        失败时进行一次滚动重试，仍失败则返回 False。
        """
        for attempt in range(2):
            self._debug_log(f"_goto_next_page attempt={attempt + 1}/2 url='{self.page.url}'")
            next_button = self._find_next_page_button()
            if not next_button:
                self._debug_log("_goto_next_page stop reason=no_next_button")
                self._debug_navigation_snapshot("no_next_button")
                if self._try_infinite_scroll_load(item_selector=item_selector):
                    self._sleep_with_throttle()
                    self._debug_log(f"_goto_next_page fallback=infinite_scroll success delay={self.current_delay:.2f}s")
                    return True
                return False
            if self._is_next_page_button_disabled(next_button):
                self._debug_log("_goto_next_page stop reason=button_disabled")
                return False

            previous_marker = self._get_page_marker()
            self._debug_log(f"_goto_next_page previous_marker='{previous_marker[:120]}'")

            try:
                next_button.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            clicked = False
            last_click_error = ""
            for click_retry in range(2):
                try:
                    next_button.click(timeout=6000)
                    clicked = True
                    self._debug_log(f"_goto_next_page click success retry={click_retry}")
                    break
                except Exception as e:
                    last_click_error = str(e)
                    if click_retry == 0:
                        try:
                            self.page.mouse.wheel(0, 2500)
                            time.sleep(0.8)
                        except Exception:
                            pass

            if not clicked:
                self._debug_log(f"_goto_next_page click failed last_error='{last_click_error[:200]}'")
                if attempt == 0:
                    try:
                        self.page.mouse.wheel(0, 5000)
                        time.sleep(1.0)
                    except Exception:
                        pass
                    continue
                return False

            if self._wait_for_page_marker_change(previous_marker):
                self._sleep_with_throttle()
                self._debug_log(f"_goto_next_page success delay={self.current_delay:.2f}s new_url='{self.page.url}'")
                return True

            self._debug_log("_goto_next_page marker_not_changed_after_click")
            if attempt == 0:
                try:
                    self.page.mouse.wheel(0, 5000)
                    time.sleep(1.0)
                except Exception:
                    pass

        self._debug_log("_goto_next_page exhausted retries, return False")
        return False

    def _wait_for_item_count(
        self,
        item_selector: str,
        min_count: int = 1,
        timeout_ms: int = 15000,
    ) -> int:
        """等待列表最小数量达到阈值，返回最后观测到的数量。"""
        deadline = time.time() + timeout_ms / 1000
        attempts = 0
        last_count = 0
        while time.time() < deadline:
            attempts += 1
            try:
                last_count = self.page.locator(item_selector).count()
            except Exception:
                last_count = 0
            if last_count >= min_count:
                return last_count
            if attempts % 3 == 0:
                try:
                    self.page.mouse.wheel(0, 1200)
                except Exception:
                    pass
            self.page.wait_for_timeout(400)
        return last_count

    def _recover_empty_viewport(
        self,
        item_selector: str,
        attempts: int = 4,
    ) -> int:
        """列表空白时滚动恢复。"""
        for step in range(1, attempts + 1):
            try:
                metrics = self.page.evaluate(
                    "() => ({ y: window.scrollY || 0, h: window.innerHeight || 0 })"
                )
            except Exception:
                metrics = {"y": 0, "h": 1200}

            y = int(metrics.get("y", 0))
            inner_height = int(metrics.get("h", 1200))
            targets = [
                max(0, y - inner_height),
                max(0, y - inner_height * 2),
                y + inner_height,
            ]
            for target in targets:
                try:
                    self.page.evaluate("(value) => window.scrollTo(0, value)", target)
                except Exception:
                    continue
                self.page.wait_for_timeout(900)
                count = self.page.locator(item_selector).count()
                self._debug_log(
                    f"_recover_empty_viewport step={step} target={target} count={count}"
                )
                if count > 0:
                    return count
        return 0

    def _extract_initial_data(self, html: str) -> Optional[Dict[str, Any]]:
        """提取页面 js-initialData JSON。"""
        match = re.search(
            r'<script id="js-initialData" type="text/json">(.*?)</script>',
            html,
            re.S,
        )
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            self._debug_log(f"initialData decode failed: {e}")
            return None

    def _html_to_text(self, content_html: str) -> str:
        """基础 HTML -> 纯文本转换。"""
        text = content_html
        block_map = {
            "</p>": "\n",
            "</li>": "\n",
            "<br>": "\n",
            "<br/>": "\n",
            "<br />": "\n",
            "</h1>": "\n",
            "</h2>": "\n",
            "</h3>": "\n",
            "</h4>": "\n",
            "</h5>": "\n",
            "</h6>": "\n",
        }
        for token, replacement in block_map.items():
            text = text.replace(token, replacement)
        text = re.sub(r"<li[^>]*>", "- ", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()

    def _save_contents(self, contents: List[ZhihuContent], prefix: str) -> List[str]:
        """保存内容到文件。"""
        data = [content.to_dict() for content in contents]
        return self.saver.save_all_formats(data, prefix)

    def _get_console(self) -> Console:
        """获取 rich console。"""
        return console

    def close(self):
        """关闭浏览器"""
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        console.print("[dim]浏览器已关闭[/dim]")

    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
