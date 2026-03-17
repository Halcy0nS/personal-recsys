#!/usr/bin/env python3
"""
知乎爬虫启动脚本
"""
import sys
import argparse
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from author_crawler import AuthorCrawler
from favorites_crawler import FavoritesCrawler

console = Console()


class UnifiedCrawler(FavoritesCrawler, AuthorCrawler):
    """同时支持收藏夹与作者抓取。"""


def show_banner():
    """显示欢迎信息"""
    banner = """
    ╔═══════════════════════════════════════════════════════╗
    ║                                                       ║
    ║     🕷️  知乎爬虫工具 (Zhihu Crawler)                   ║
    ║                                                       ║
    ║     支持: 收藏夹爬取 | 作者内容爬取                   ║
    ║                                                       ║
    ╚═══════════════════════════════════════════════════════╝
    """
    console.print(banner, style="bold cyan")


def show_menu():
    """显示主菜单"""
    table = Table(
        title="请选择爬取模式",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    table.add_column("选项", style="cyan", justify="center")
    table.add_column("功能", style="green")
    table.add_column("说明", style="dim")

    table.add_row("1", "爬取收藏夹", "爬取指定用户的收藏夹内容")
    table.add_row("2", "爬取作者回答", "爬取指定作者的所有回答")
    table.add_row("3", "爬取作者文章", "爬取指定作者的所有文章")
    table.add_row("4", "爬取作者全部内容", "爬取指定作者的回答+文章")
    table.add_row("0", "退出", "退出程序")

    console.print(table)


def crawl_favorites_flow(crawler: UnifiedCrawler):
    """收藏夹爬取流程"""
    console.print("\n[bold cyan]📚 收藏夹爬取[/bold cyan]")

    username = console.input("请输入知乎用户ID [dim](默认: cjm926)[/dim]: ").strip()
    if not username:
        username = "cjm926"

    max_pages_str = console.input("请输入最大爬取页数 [dim](默认: 5)[/dim]: ").strip()
    max_pages = int(max_pages_str) if max_pages_str.isdigit() else 5

    console.print(f"\n[yellow]即将爬取用户 [cyan]{username}[/cyan] 的收藏夹，最多 [cyan]{max_pages}[/cyan] 页...[/yellow]")
    confirm = console.input("确认开始? [Y/n]: ").strip().lower()

    if confirm in ('', 'y', 'yes'):
        result = crawler.crawl_favorites(username, max_pages)

        if result.success:
            console.print(f"\n[bold green]✓ {result.message}[/bold green]")
            console.print(f"[dim]保存文件: {', '.join(result.saved_files)}[/dim]")
        else:
            console.print(f"\n[bold yellow]⚠ {result.message}[/bold yellow]")
    else:
        console.print("[dim]已取消[/dim]")


def crawl_author_flow(crawler: UnifiedCrawler, content_type: str):
    """作者内容爬取流程"""
    type_map = {
        "answers": ("回答", "crawl_author_answers"),
        "articles": ("文章", "crawl_author_articles"),
        "all": ("全部内容", "crawl_author_all_content")
    }

    type_name, method_name = type_map.get(content_type, ("内容", ""))
    console.print(f"\n[bold cyan]✍️ 爬取作者{type_name}[/bold cyan]")

    author_id = console.input("请输入作者ID [dim](URL中的用户标识，如 'cjm926')[/dim]: ").strip()
    if not author_id:
        console.print("[red]✗ 作者ID不能为空[/red]")
        return

    max_pages_str = console.input("请输入最大爬取页数 [dim](默认: 5，作者抓取可输入 0 表示全量)[/dim]: ").strip()
    max_pages = int(max_pages_str) if max_pages_str.isdigit() else 5
    target_count_str = console.input("请输入目标条数 [dim](默认: 0，不限)[/dim]: ").strip()
    target_count = int(target_count_str) if target_count_str.isdigit() else 0

    pages_desc = "全量（直到连续2轮无新增）" if max_pages <= 0 else f"{max_pages} 页"
    target_desc = "不限" if target_count <= 0 else str(target_count)
    console.print(f"\n[yellow]即将爬取作者 [cyan]{author_id}[/cyan] 的{type_name}，范围 [cyan]{pages_desc}[/cyan]，目标 [cyan]{target_desc}[/cyan] 条...[/yellow]")
    confirm = console.input("确认开始? [Y/n]: ").strip().lower()

    if confirm in ('', 'y', 'yes'):
        if content_type == "all":
            results = crawler.crawl_author_all_content(author_id, max_pages, target_count=target_count)
            total = sum(r.total_count for r in results.values())
            console.print(f"\n[bold green]✓ 成功爬取 {total} 条内容[/bold green]")
            for content_type, result in results.items():
                if result.saved_files:
                    console.print(f"[dim]{content_type}: {', '.join(result.saved_files)}[/dim]")
        else:
            method = getattr(crawler, method_name)
            result = method(author_id, max_pages, target_count=target_count)

            if result.success:
                console.print(f"\n[bold green]✓ {result.message}[/bold green]")
                console.print(f"[dim]保存文件: {', '.join(result.saved_files)}[/dim]")
            else:
                console.print(f"\n[bold yellow]⚠ {result.message}[/bold yellow]")
    else:
        console.print("[dim]已取消[/dim]")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="知乎爬虫工具")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器）")
    parser.add_argument("--favorites", type=str, help="直接爬取指定用户的收藏夹")
    parser.add_argument("--author", type=str, help="直接爬取指定作者的内容")
    parser.add_argument("--type", type=str, choices=["answers", "articles", "all"], default="answers", help="爬取内容类型")
    parser.add_argument("--pages", type=int, default=5, help="最大爬取页数（作者任务中 0 表示抓全量）")
    parser.add_argument("--target-count", type=int, default=0, help="作者任务目标条数（0 表示不限）")

    args = parser.parse_args()

    show_banner()

    # 命令行模式
    if args.favorites:
        with FavoritesCrawler(headless=args.headless) as crawler:
            crawler.ensure_login()
            result = crawler.crawl_favorites(args.favorites, args.pages)
            if result.success:
                print(f"✓ {result.message}")
            else:
                print(f"⚠ {result.message}")

        return

    if args.author:
        with AuthorCrawler(headless=args.headless) as crawler:
            crawler.ensure_login()

            if args.type == "answers":
                result = crawler.crawl_author_answers(args.author, args.pages, target_count=args.target_count)
            elif args.type == "articles":
                result = crawler.crawl_author_articles(args.author, args.pages, target_count=args.target_count)
            else:
                results = crawler.crawl_author_all_content(args.author, args.pages, target_count=args.target_count)
                total = sum(r.total_count for r in results.values())
                print(f"✓ 成功爬取 {total} 条内容")
                return

            if result.success:
                print(f"✓ {result.message}")
            else:
                print(f"⚠ {result.message}")

        return

    # 交互式菜单模式
    with UnifiedCrawler(headless=args.headless) as crawler:
        # 先登录
        crawler.ensure_login()

        while True:
            show_menu()
            choice = console.input("\n请输入选项 [0-4]: ").strip()

            if choice == "1":
                crawl_favorites_flow(crawler)
            elif choice == "2":
                crawl_author_flow(crawler, "answers")
            elif choice == "3":
                crawl_author_flow(crawler, "articles")
            elif choice == "4":
                crawl_author_flow(crawler, "all")
            elif choice == "0":
                console.print("\n[dim]感谢使用，再见！[/dim]")
                break
            else:
                console.print("[red]✗ 无效选项，请重新输入[/red]")

            console.input("\n按回车键继续...")


if __name__ == "__main__":
    main()
