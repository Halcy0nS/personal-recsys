#!/usr/bin/env python3
"""
调试收藏夹页面结构
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from crawler import ZhihuCrawler
from rich.console import Console
from rich.pretty import pprint

console = Console()

def debug_collections_page():
    """调试收藏夹页面"""

    with ZhihuCrawler(headless=False) as crawler:
        # 确保登录
        crawler.ensure_login()

        # 访问收藏夹列表页
        url = "https://www.zhihu.com/people/cjm926/collections"
        console.print(f"\n[cyan]正在访问: {url}[/cyan]")

        crawler.page.goto(url)
        crawler.page.wait_for_load_state("networkidle")

        # 等待几秒让页面完全加载
        import time
        time.sleep(3)

        console.print("\n[bold]页面信息:[/bold]")
        console.print(f"  标题: {crawler.page.title()}")
        console.print(f"  URL: {crawler.page.url}")

        # 尝试多种可能的选择器
        selectors_to_try = [
            # 收藏夹卡片
            ".CollectionItem",
            ".Collections-container .Card",
            ".CollectionsPage .Card",
            "[data-za-detail-view-path-module='CollectionItem']",
            ".Collections-list .CollectionCard",
            ".CollectionCard",
            # 更通用的
            ".Card:has(a[href*='/collection/'])",
            "a[href*='/collection/']",
        ]

        console.print("\n[bold]尝试查找收藏夹元素:[/bold]")

        found_selector = None
        for selector in selectors_to_try:
            try:
                count = crawler.page.locator(selector).count()
                status = f"[green]✓ 找到 {count} 个[/green]" if count > 0 else "[dim]0 个[/dim]"
                console.print(f"  {selector:<50} {status}")

                if count > 0 and not found_selector:
                    found_selector = selector

            except Exception as e:
                console.print(f"  {selector:<50} [red]错误: {e}[/red]")

        # 如果找到了元素，尝试解析几个看看
        if found_selector:
            console.print(f"\n[bold green]使用选择器 '{found_selector}' 解析收藏夹:[/bold green]")

            items = crawler.page.query_selector_all(found_selector)
            for i, item in enumerate(items[:3]):  # 只显示前3个
                try:
                    # 尝试提取标题
                    title_selectors = [".CollectionItem-title", ".Card-title", "h2", ".title", "a"]
                    title = None
                    for ts in title_selectors:
                        title_elem = item.query_selector(ts)
                        if title_elem:
                            title = title_elem.inner_text().strip()
                            if title:
                                break

                    console.print(f"  [{i+1}] {title or '未知标题'}")
                except Exception as e:
                    console.print(f"  [{i+1}] 解析失败: {e}")

        console.print("\n[yellow]请查看以上输出，确认收藏夹选择器是否正确[/yellow]")

        # 保持浏览器打开以便查看
        console.input("\n按回车键关闭浏览器...")


if __name__ == "__main__":
    debug_collections_page()
