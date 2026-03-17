#!/usr/bin/env python3
"""
知乎爬虫工具 - 安装脚本
"""
import subprocess
import sys
from pathlib import Path


def check_python_version():
    """检查Python版本"""
    if sys.version_info < (3, 8):
        print("❌ 需要 Python 3.8 或更高版本")
        sys.exit(1)
    print(f"✅ Python 版本: {sys.version_info.major}.{sys.version_info.minor}")


def install_requirements():
    """安装依赖"""
    print("\n📦 正在安装依赖...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            check=True,
            cwd=Path(__file__).parent
        )
        print("✅ 依赖安装完成")
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败: {e}")
        sys.exit(1)


def install_browser():
    """安装Playwright浏览器"""
    print("\n🌐 正在安装 Playwright 浏览器...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True
        )
        print("✅ 浏览器安装完成")
    except subprocess.CalledProcessError as e:
        print(f"❌ 浏览器安装失败: {e}")
        print("提示: 可以尝试手动运行: playwright install chromium")


def create_data_dir():
    """创建数据目录"""
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    print(f"\n📁 数据目录: {data_dir.absolute()}")


def main():
    """主函数"""
    print("=" * 60)
    print("     知乎爬虫工具 - 安装脚本")
    print("=" * 60)

    check_python_version()
    install_requirements()
    install_browser()
    create_data_dir()

    print("\n" + "=" * 60)
    print("✅ 安装完成！")
    print("=" * 60)
    print("\n使用方式:")
    print("  1. 交互式模式: python run.py")
    print("  2. 命令行模式: python run.py --help")
    print("\n开始爬取前，请确保:")
    print("  1. 已注册知乎账号")
    print("  2. 网络连接正常")
    print("=" * 60)


if __name__ == "__main__":
    main()
