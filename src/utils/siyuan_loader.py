import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SiYuanClient:
    """思源笔记本地 API 客户端"""

    def __init__(self, base_url: str = "http://127.0.0.1:6806", token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _post(self, endpoint: str, data: dict,
              max_retries: int = 3, retry_backoff: float = 0.5) -> dict:
        """发送 POST 请求到思源 API，带重试逻辑。

        Returns:
            API 响应 dict；持久失败时返回 {"_error": True, "message": ...} 以便
            调用方区分"成功空响应"和"连接失败"。
        """
        url = f"{self.base_url}/api/{endpoint}"
        payload = json.dumps(data).encode("utf-8")
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"

        last_error: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            req = urllib.request.Request(url, data=payload, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                    if res.get("code") != 0:
                        logger.warning("SiYuan API 返回错误 [%s]: %s", endpoint, res.get("msg"))
                    return res
            except urllib.error.URLError as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(retry_backoff * attempt)
            except Exception as e:
                last_error = e
                break

        logger.error("SiYuan API 连接失败 [%s]（重试 %d 次后仍失败）: %s",
                     endpoint, max_retries, last_error)
        return {"_error": True, "message": str(last_error)}

    def get_md_content(self, block_id: str) -> str:
        """根据块 ID 获取 Markdown 内容"""
        res = self._post("export/exportMdContent", {"id": block_id})
        if res.get("_error"):
            return ""
        return res.get("data", {}).get("content", "")

    def sql_query(self, sql: str) -> List[dict]:
        """执行 SQL 查询"""
        res = self._post("query/sql", {"stmt": sql})
        if res.get("_error"):
            return []
        return res.get("data", [])

    def create_doc_with_md(self, notebook_id: str, path: str, markdown: str) -> str:
        """新建文档并写入 Markdown。注意 path 需以 / 开头。"""
        res = self._post("filetree/createDocWithMd", {
            "notebook": notebook_id,
            "path": path,
            "markdown": markdown
        })
        if res.get("_error"):
            return ""
        return res.get("data", "")


def is_siyuan_id(text: str) -> bool:
    """简单判断是否为思源块 ID，格式如: 20210808180117-6v0iq26"""
    return bool(re.match(r"^\d{14}-[a-z0-9]{7}$", text.strip()))


def read_siyuan_anchor(client: SiYuanClient, anchor_input: str) -> str:
    """读取知识锚点。如果输入是思源 ID，拉取其内容；如果是纯文本，直接返回。"""
    anchor_input = anchor_input.strip()
    if is_siyuan_id(anchor_input):
        content = client.get_md_content(anchor_input)
        if content:
            return content
        else:
            logger.warning("无法通过 ID %s 获取内容，可能 ID 错误或无权限。", anchor_input)
            return "默认知识锚点：寻找有深度的技术与产品创新。"
    else:
        return anchor_input


def fetch_siyuan_favorites(client: SiYuanClient, limit: int = 50) -> List[str]:
    """获取所有历史笔记作为全局口味。拉取最新的 limit 个段落块。"""
    sql = (
        "SELECT markdown FROM blocks "
        "WHERE type='p' AND markdown != '' "
        f"ORDER BY updated DESC LIMIT {limit}"
    )
    rows = client.sql_query(sql)
    return [row.get("markdown", "") for row in rows]


def write_siyuan_curation(client: SiYuanClient, notebook: str,
                          date_str: str, content: str) -> str:
    """将导读写入思源笔记的指定笔记本下的 /Daily/ 目录。

    Returns:
        成功时返回创建的文档 ID，失败时返回空字符串。
    """
    if not notebook:
        logger.warning("未指定思源笔记本 ID，将导读写入本地文件 fallback.md")
        fallback_path = os.path.abspath("fallback.md")
        try:
            with open(fallback_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("已写入 fallback 文件: %s", fallback_path)
        except Exception as e:
            logger.error("写入 fallback.md 失败: %s", e)
        return ""

    path = f"/Daily/{date_str}-RSS内参"
    doc_id = client.create_doc_with_md(notebook, path, content)
    return doc_id
