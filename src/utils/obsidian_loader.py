import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def read_obsidian_anchor(file_path: str) -> str:
    """读取本地 Obsidian Markdown 文件内容，作为知识锚点（意图/上下文）。

    Returns:
        文件内容；读取失败时返回空字符串并记录错误日志。
    """
    if not os.path.exists(file_path):
        logger.warning("找不到给定的 Obsidian 文件: %s", file_path)
        return ""

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content.strip()
    except Exception as e:
        logger.error("读取 Obsidian 文件出错: %s", e)
        return ""


def write_daily_curation(vault_path: str, date_str: str, content: str) -> str:
    """将生成的导读写入 Obsidian 的 Daily 目录（原子写入，防崩溃截断）。

    Returns:
        成功时返回写入的文件路径，失败时返回空字符串并记录错误日志。
    """
    daily_dir = os.path.join(vault_path, "Daily")
    os.makedirs(daily_dir, exist_ok=True)

    file_name = f"{date_str}-内参.md"
    file_path = os.path.join(daily_dir, file_name)

    try:
        # 原子写入：先写临时文件，再 rename
        fd, tmp_path = tempfile.mkstemp(
            suffix=".md", prefix=".tmp-", dir=daily_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, file_path)
        except Exception:
            os.unlink(tmp_path)
            raise
        return file_path
    except Exception as e:
        logger.error("写入 Obsidian 文件出错: %s", e)
        return ""
