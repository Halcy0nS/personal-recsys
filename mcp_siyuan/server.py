import os
import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from fastmcp import FastMCP, Context

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastMCP Server
mcp = FastMCP("SiYuan Note MCP")

# Config
SIYUAN_URL = os.environ.get("SIYUAN_URL", "http://127.0.0.1:6806").rstrip("/")
SIYUAN_TOKEN = os.environ.get("SIYUAN_TOKEN", "")

def _post(endpoint: str, data: dict) -> dict:
    """Helper method to make POST requests to SiYuan API."""
    url = f"{SIYUAN_URL}/api/{endpoint}"
    payload = json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if SIYUAN_TOKEN:
        headers["Authorization"] = f"Token {SIYUAN_TOKEN}"

    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("code") != 0:
                logger.warning("SiYuan API Error [%s]: %s", endpoint, res.get("msg"))
            return res
    except Exception as e:
        logger.error("SiYuan API Request Failed [%s]: %s", endpoint, e)
        return {"code": -1, "msg": str(e), "data": None}


@mcp.tool(name="siyuan_search", description="Search blocks in SiYuan with full text search.")
def siyuan_search(query: str, types: Optional[List[str]] = None) -> List[Dict]:
    """Search for blocks. types can be ['d', 'p', 'h'] (document, paragraph, heading)."""
    if not types:
        types = ["d", "p", "h"]
    res = _post("search/fullTextSearchBlock", {"query": query, "types": {t: True for t in types}})
    if res.get("code") == 0 and res.get("data"):
        return res["data"].get("blocks", [])
    return []

@mcp.tool(name="siyuan_get_doc", description="Pull the complete markdown content of a document by block ID.")
def siyuan_get_doc(id: str) -> str:
    """Gets the entire markdown content of a block/document by its ID."""
    res = _post("export/exportMdContent", {"id": id})
    if res.get("code") == 0 and res.get("data"):
        return res["data"].get("content", "")
    return ""

@mcp.tool(name="siyuan_create_doc", description="Create a new document with markdown content. path must start with /.")
def siyuan_create_doc(notebook: str, path: str, markdown: str) -> str:
    """Create a new document in the given notebook. Path should start with a slash (e.g., /MyDoc)."""
    res = _post("filetree/createDocWithMd", {"notebook": notebook, "path": path, "markdown": markdown})
    if res.get("code") == 0:
        return res.get("data", "")
    return ""

@mcp.tool(name="siyuan_append_block", description="Append a new markdown block to a parent block ID.")
def siyuan_append_block(data: str, parentID: str) -> List[Dict]:
    """Appends markdown text to a parent block/document."""
    res = _post("block/appendBlock", {"data": data, "dataType": "markdown", "parentID": parentID})
    if res.get("code") == 0:
        return res.get("data", [])
    return []

@mcp.tool(name="siyuan_list_notebooks", description="List all open notebooks in SiYuan.")
def siyuan_list_notebooks() -> List[Dict]:
    """Returns a list of all notebooks with their IDs and names."""
    res = _post("notebook/lsNotebooks", {})
    if res.get("code") == 0:
        return res.get("data", {}).get("notebooks", [])
    return []

@mcp.tool(name="siyuan_list_docs", description="List documents and folders under a specific path in a notebook.")
def siyuan_list_docs(notebook: str, path: str) -> List[Dict]:
    """Lists files/docs under a path. Use '/' for the root of the notebook."""
    res = _post("filetree/listDocsByPath", {"notebook": notebook, "path": path})
    if res.get("code") == 0:
        return res.get("data", {}).get("files", [])
    return []

@mcp.tool(name="siyuan_sql", description="Run raw SQL query against the SiYuan local SQLite database.")
def siyuan_sql(stmt: str) -> List[Dict]:
    """Execute arbitrary SQL queries on the blocks database (e.g., SELECT * FROM blocks LIMIT 10)."""
    res = _post("query/sql", {"stmt": stmt})
    if res.get("code") == 0:
        return res.get("data", [])
    return []

@mcp.tool(name="siyuan_backlinks", description="Get all backlinks (references) for a specific block ID.")
def siyuan_backlinks(id: str) -> Dict:
    """Returns all blocks that link to the provided block ID."""
    res = _post("ref/getBacklink", {"id": id})
    if res.get("code") == 0:
        return res.get("data", {})
    return {}

if __name__ == "__main__":
    mcp.run(transport="stdio")
