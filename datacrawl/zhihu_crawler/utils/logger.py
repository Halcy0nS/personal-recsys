"""
日志工具
"""
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger

# 移除默认的handler
logger.remove()

# 添加控制台输出
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)

# 添加文件输出
log_dir = Path("./logs")
log_dir.mkdir(exist_ok=True)

logger.add(
    log_dir / "zhihu_crawler_{time:YYYY-MM-DD}.log",
    rotation="00:00",  # 每天午夜轮转
    retention="7 days",  # 保留7天
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    encoding="utf-8"
)

__all__ = ["logger"]
