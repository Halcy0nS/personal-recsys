"""
收藏夹爬虫模块
支持从收藏夹列表页获取所有收藏夹，并区分正/负样本
"""
import time
import re
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from urllib.parse import urljoin

from playwright.sync_api import Page
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

from models import ZhihuContent, CrawlResult
from crawler import ZhihuCrawler

console = Console()


@dataclass
class FavoriteFolder:
    """收藏夹信息"""
    name: str
    url: str
    item_count: int = 0
    label: int = 0  # 0=负样本(待看), 1=正样本(已消费)
    is_public: bool = True


class FavoritesCrawler(ZhihuCrawler):
    """收藏夹爬虫 - 支持从收藏夹列表页获取所有收藏夹"""

    def get_favorites_list(self, username: str = "cjm926") -> List[FavoriteFolder]:
        """
        获取用户的所有收藏夹列表
        从 https://www.zhihu.com/people/{username}/collections 页面获取

        Returns:
            List[FavoriteFolder]: 收藏夹列表（已标记正负样本）
        """
        collections_url = f"https://www.zhihu.com/people/{username}/collections"
        console.print(f"[blue]正在获取收藏夹列表...[/blue]")
        console.print(f"[dim]{collections_url}[/dim]")

        if not self._safe_goto(collections_url, wait_until="domcontentloaded", retries=3):
            console.print("[yellow]收藏夹列表页访问失败[/yellow]")
            return []
        self.page.wait_for_load_state("networkidle")
        time.sleep(3)

        # 等待收藏夹列表加载
        try:
            # 等待页面主要内容加载 - 使用更精确的选择器
            self.page.wait_for_selector(".Card, .SelfCollectionItem", timeout=10000)
        except:
            console.print("[yellow]未找到收藏夹或页面加载超时[/yellow]")
            return []

        folders: List[FavoriteFolder] = []
        seen_urls: set = set()  # 用于去重

        # 获取所有收藏夹卡片 - 过滤出真正的收藏夹
        all_cards = self.page.query_selector_all(".Card")
        collection_items = []

        for card in all_cards:
            # 检查是否包含收藏夹链接
            has_collection_link = card.query_selector("a[href*='/collection/']")
            # 检查是否包含"条内容"文本
            text_content = card.inner_text()
            has_content_count = "条内容" in text_content

            # 真正的收藏夹应该同时满足这两个条件
            if has_collection_link and has_content_count:
                collection_items.append(card)

        console.print(f"[dim]找到 {len(collection_items)} 个有效收藏夹 (过滤前: {len(all_cards)})[/dim]")
        console.print(f"[dim]找到 {len(collection_items)} 个收藏夹[/dim]")

        for item in collection_items:
            try:
                # 提取收藏夹名称
                # 首先尝试从链接文本获取名称
                name = None
                link_elem = item.query_selector("a[href*='/collection/']")
                if link_elem:
                    name = link_elem.inner_text().strip().split('\n')[0].strip()

                # 如果无法从链接获取，尝试其他选择器
                if not name:
                    name_selectors = [
                        ".Card-title",
                        ".CollectionItem-title",
                        "h2",
                        ".title"
                    ]
                    for selector in name_selectors:
                        name_elem = item.query_selector(selector)
                        if name_elem:
                            name = name_elem.inner_text().strip()
                            if name:
                                break

                # 最后尝试从整个卡片文本中提取第一行
                if not name:
                    full_text = item.inner_text()
                    name = full_text.split('\n')[0].strip()[:50]

                if not name:
                    continue

                # 提取收藏夹链接
                url = ""
                link_elem = item.query_selector("a[href*='/collection/']")
                if link_elem:
                    href = link_elem.get_attribute("href") or ""
                    url = href if href.startswith("http") else f"https://www.zhihu.com{href}"

                # 去重检查 - 在获取URL后立即检查
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # 提取内容数量 - 从文本中匹配
                item_count = 0
                item_text = item.inner_text()
                # 匹配 "X 条内容" 或 "X条内容"
                count_match = re.search(r'(\d+)\s*条内容', item_text)
                if count_match:
                    item_count = int(count_match.group(1))

                # 所有收藏夹都标记为正样本(1)
                # "待看"只是感兴趣，不是负样本
                label = 1

                folder = FavoriteFolder(
                    name=name,
                    url=url,
                    item_count=item_count,
                    label=label
                )
                folders.append(folder)

            except Exception as e:
                console.print(f"[dim]解析收藏夹出错: {e}[/dim]")
                continue

        # 显示收藏夹列表
        self._display_favorites_table(folders)

        return folders

    def _display_favorites_table(self, folders: List[FavoriteFolder]):
        """显示收藏夹列表表格"""
        table = Table(
            title=f"找到 {len(folders)} 个收藏夹",
            box=None,
            show_header=True,
            header_style="bold cyan"
        )
        table.add_column("名称", style="green")
        table.add_column("数量", justify="right", style="cyan")
        table.add_column("标签", justify="center")
        table.add_column("URL", style="dim")

        for folder in folders:
            label_text = "[red]负样本(待看)" if folder.label == 0 else "[green]正样本"
            table.add_row(
                folder.name,
                str(folder.item_count),
                label_text,
                folder.url[:50] + "..." if len(folder.url) > 50 else folder.url
            )

        console.print(table)

    def crawl_favorites(
        self,
        username: str = "cjm926",
        max_pages: int = 10,
        fetch_full_content: bool = False
    ) -> CrawlResult:
        """
        爬取用户收藏夹内容
        先获取收藏夹列表，然后逐个爬取每个收藏夹

        Args:
            username: 知乎用户名
            max_pages: 每个收藏夹最大爬取页数
            fetch_full_content: 是否获取完整内容(需要点击进入详情页，较慢)
        """
        result = CrawlResult()

        # 步骤1: 获取所有收藏夹列表
        folders = self.get_favorites_list(username)

        if not folders:
            result.message = "未找到任何收藏夹"
            return result

        # 步骤2: 逐个爬取每个收藏夹
        all_contents: List[ZhihuContent] = []

        # 分别统计正负样本
        positive_count = sum(1 for f in folders if f.label == 1)
        negative_count = sum(1 for f in folders if f.label == 0)

        console.print(f"\n[bold]开始爬取 {len(folders)} 个收藏夹...[/bold]")
        console.print(f"  [green]正样本: {positive_count} 个[/green]")
        console.print(f"  [red]负样本(待看): {negative_count} 个[/red]")
        if fetch_full_content:
            console.print(f"  [yellow]⚠ 将获取完整内容(速度较慢)[/yellow]")

        for folder in folders:
            if not folder.url:
                continue

            label_name = "负样本" if folder.label == 0 else "正样本"
            console.print(f"\n[cyan]▶ 正在爬取: {folder.name} ({label_name})[/cyan]")

            try:
                contents = self._crawl_single_collection(
                    folder.url,
                    folder.label,
                    max_pages,
                    fetch_full_content
                )
                all_contents.extend(contents)

                console.print(f"  [dim]获取 {len(contents)} 条内容[/dim]")

            except Exception as e:
                console.print(f"  [red]爬取失败: {e}[/red]")
                continue

        # 保存所有数据
        if all_contents:
            files = self._save_contents(all_contents, f"favorites_{username}_all")
            result.success = True
            result.total_count = len(all_contents)
            result.contents = all_contents
            result.saved_files = files

            # 统计正负样本数量
            pos_count = sum(1 for c in all_contents if c.metadata.get('label') == 1)
            neg_count = sum(1 for c in all_contents if c.metadata.get('label') == 0)

            result.message = (
                f"成功爬取 {len(all_contents)} 条内容，"
                f"其中正样本 {pos_count} 条，负样本 {neg_count} 条"
            )
        else:
            result.message = "未获取到任何内容"

        return result

    def _crawl_single_collection(
        self,
        collection_url: str,
        label: int,
        max_pages: int,
        fetch_full_content: bool = False
    ) -> List[ZhihuContent]:
        """
        爬取单个收藏夹的内容

        Args:
            collection_url: 收藏夹URL
            label: 标签(0/1)
            max_pages: 最大页数
            fetch_full_content: 是否获取完整内容(需要点击进入详情页)
        """
        contents: List[ZhihuContent] = []

        if not self._safe_goto(collection_url, wait_until="domcontentloaded", retries=3):
            console.print(f"[yellow]收藏夹页面访问失败: {collection_url}[/yellow]")
            return contents
        time.sleep(3)

        for page_num in range(1, max_pages + 1):
            # 等待内容加载
            try:
                self.page.wait_for_selector(
                    ".ContentItem, .AnswerItem, .ArticleItem",
                    timeout=10000
                )
            except:
                break

            if fetch_full_content:
                items = self.page.query_selector_all(
                    ".ContentItem, .AnswerItem, .ArticleItem, .PinItem"
                )
                page_contents: List[ZhihuContent] = []
                for item in items:
                    content = self._fetch_full_content_from_item(item)
                    if content:
                        page_contents.append(content)
            else:
                page_contents = self._extract_page_contents(
                    ".ContentItem, .AnswerItem, .ArticleItem, .PinItem"
                )

            type_counter = {"answer": 0, "article": 0, "pin": 0}
            for content in page_contents:
                # 添加标签信息到 metadata
                content.metadata['label'] = label
                content.metadata['collection_url'] = collection_url
                contents.append(content)

                if content.content_type in type_counter:
                    type_counter[content.content_type] += 1

            console.print(
                "  [dim]第 {} 页获取 {} 条: answers={}, articles={}, pins={}[/dim]".format(
                    page_num,
                    len(page_contents),
                    type_counter["answer"],
                    type_counter["article"],
                    type_counter["pin"],
                )
            )

            # 尝试翻页
            has_next = self._goto_next_page()
            if not has_next:
                break

        return contents

    def _fetch_full_content_from_item(self, item) -> Optional[ZhihuContent]:
        """
        从列表项点击进入详情页获取完整内容

        Args:
            item: 列表项元素

        Returns:
            ZhihuContent: 包含完整内容的对象
        """
        try:
            # 首先解析列表页的基本信息
            content = self._parse_content_item(item)
            if not content:
                return None

            # 如果没有URL，无法获取详情
            if not content.url:
                return content

            console.print(f"    [dim]正在获取详情: {content.title[:30] if content.title else '无标题'}...[/dim]")

            # 打开详情页（在新标签页）
            detail_page = self.context.new_page()
            try:
                detail_page.goto(content.url, timeout=30000)
                detail_page.wait_for_load_state("networkidle")
                time.sleep(2)

                # 根据内容类型提取完整内容
                if content.content_type == "article":
                    self._extract_article_full_content(detail_page, content)
                elif content.content_type == "answer":
                    self._extract_answer_full_content(detail_page, content)

                return content

            finally:
                detail_page.close()

        except Exception as e:
            console.print(f"    [dim red]获取详情失败: {e}[/dim red]")
            # 返回列表页解析的基本信息
            return self._parse_content_item(item)

    def _extract_article_full_content(self, page, content: ZhihuContent):
        """从文章详情页提取完整内容"""
        try:
            # 等待文章内容加载
            page.wait_for_selector(".Post-RichText, .RichText, article", timeout=10000)

            # 提取完整内容
            content_selectors = [
                ".Post-RichText",
                ".RichText",
                "article .RichText",
                ".Post-content .RichText"
            ]

            for selector in content_selectors:
                elem = page.query_selector(selector)
                if elem:
                    full_text = elem.inner_text().strip()
                    content.content = full_text
                    content.excerpt = full_text[:500] if len(full_text) > 500 else full_text
                    break

            # 提取更准确的标题
            title_selectors = [
                "h1.Post-Title",
                "h1",
                ".Post-content h1"
            ]
            for selector in title_selectors:
                title_elem = page.query_selector(selector)
                if title_elem:
                    title = title_elem.inner_text().strip()
                    if title:
                        content.title = title
                        break

        except Exception as e:
            console.print(f"    [dim red]提取文章完整内容失败: {e}[/dim red]")

    def _extract_answer_full_content(self, page, content: ZhihuContent):
        """从回答详情页提取完整内容"""
        try:
            # 等待回答内容加载
            page.wait_for_selector(".RichContent, .RichText, .AnswerCard", timeout=10000)

            # 提取完整内容
            content_selectors = [
                ".RichContent .RichText",
                ".AnswerCard .RichText",
                ".RichText",
                ".Answer-content .RichText"
            ]

            for selector in content_selectors:
                elem = page.query_selector(selector)
                if elem:
                    full_text = elem.inner_text().strip()
                    content.content = full_text
                    content.excerpt = full_text[:500] if len(full_text) > 500 else full_text
                    break

            # 提取问题标题作为标题
            title_selectors = [
                "h1.QuestionHeader-title",
                "h1",
                ".QuestionHeader h1"
            ]
            for selector in title_selectors:
                title_elem = page.query_selector(selector)
                if title_elem:
                    title = title_elem.inner_text().strip()
                    if title:
                        content.title = title
                        break

        except Exception as e:
            console.print(f"    [dim red]提取回答完整内容失败: {e}[/dim red]")

# 便捷函数
def create_crawler(headless: bool = False) -> FavoritesCrawler:
    """创建爬虫实例"""
    return FavoritesCrawler(headless=headless)
