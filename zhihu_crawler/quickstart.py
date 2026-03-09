#!/usr/bin/env python3
"""
知乎爬虫 - 快速开始脚本
一键运行常用功能
"""
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from author_crawler import AuthorCrawler
from favorites_crawler import FavoritesCrawler

console = Console()


def quick_crawl_favorites():
    """快速爬取 cjm926 的收藏夹"""
    console.print(Panel.fit(
        "[bold cyan]快速爬取收藏夹[/bold cyan]\n"
        "用户: cjm926\n"
        "页数: 5",
        title="任务信息",
        border_style="cyan"
    ))

    with FavoritesCrawler(headless=False) as crawler:
        # 确保登录
        if not crawler.ensure_login():
            console.print("[red]✗ 登录失败，无法继续[/red]")
            return

        # 开始爬取
        result = crawler.crawl_favorites(username="cjm926", max_pages=5)

        if result.success:
            console.print(f"\n[bold green]✓ 爬取成功！[/bold green]")
            console.print(f"  获取内容: {result.total_count} 条")
            console.print(f"  保存文件:")
            for f in result.saved_files:
                console.print(f"    - {f}")
        else:
            console.print(f"\n[bold yellow]⚠ {result.message}[/bold yellow]")


def quick_crawl_author():
    """快速爬取指定作者"""
    console.print(Panel.fit(
        "[bold cyan]快速爬取作者内容[/bold cyan]",
        title="任务信息",
        border_style="cyan"
    ))

    author_id = console.input("请输入作者ID: ").strip()
    if not author_id:
        console.print("[red]✗ 作者ID不能为空[/red]")
        return

    content_type = console.input("内容类型 [1-回答 2-文章 3-全部] (默认1): ").strip()
    type_map = {"1": "answers", "2": "articles", "3": "all", "": "answers"}
    content_type = type_map.get(content_type, "answers")

    with AuthorCrawler(headless=False) as crawler:
        if not crawler.ensure_login():
            console.print("[red]✗ 登录失败[/red]")
            return

        if content_type == "all":
            results = crawler.crawl_author_all_content(author_id, max_pages=0)
            total = sum(r.total_count for r in results.values())
            console.print(f"\n[bold green]✓ 共爬取 {total} 条内容[/bold green]")
        else:
            method = getattr(crawler, f"crawl_author_{content_type}")
            result = method(author_id, max_pages=0)

            if result.success:
                console.print(f"\n[bold green]✓ {result.message}[/bold green]")
                for f in result.saved_files:
                    console.print(f"  - {f}")
            else:
                console.print(f"[yellow]⚠ {result.message}[/yellow]")


def show_menu():
    """显示菜单"""
    menu_text = Text()
    menu_text.append("\n📋 快速开始菜单\n", style="bold cyan underline")
    menu_text.append("\n")
    menu_text.append("  [1] ", style="cyan")
    menu_text.append("快速爬取收藏夹 (cjm926)\n", style="green")
    menu_text.append("  [2] ", style="cyan")
    menu_text.append("快速爬取指定作者\n", style="green")
    menu_text.append("  [3] ", style="cyan")
    menu_text.append("启动交互式菜单\n", style="green")
    menu_text.append("  [0] ", style="cyan")
    menu_text.append("退出\n", style="red")

    console.print(menu_text)


def main():
    """主函数"""
    console.print(Panel.fit(
        "[bold cyan]知乎爬虫 - 快速开始[/bold cyan]\n"
        "无需安装，一键运行常用功能",
        title="欢迎",
        border_style="cyan"
    ))

    while True:
        show_menu()
        choice = console.input("请输入选项 [0-3]: ").strip()

        if choice == "1":
            try:
                quick_crawl_favorites()
            except Exception as e:
                console.print(f"[red]✗ 出错: {e}[/red]")

        elif choice == "2":
            try:
                quick_crawl_author()
            except Exception as e:
                console.print(f"[red]✗ 出错: {e}[/red]")

        elif choice == "3":
            console.print("[dim]启动完整菜单...[/dim]")
            import run
            run.main()
            break

        elif choice == "0":
            console.print("\n[dim]再见！[/dim]")
            break

        else:
            console.print("[red]✗ 无效选项[/red]")

        console.input("\n按回车键继续...")


if __name__ == "__main__":
    main()
