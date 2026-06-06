import os
import glob
import requests
import argparse
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SIYUAN_API_URL = "http://127.0.0.1:6806/api"
API_TOKEN = os.environ.get("SIYUAN_API_TOKEN", "")

def make_request(endpoint: str, data: dict = None) -> Any:
    """封装对思源 API 的请求"""
    url = f"{SIYUAN_API_URL}/{endpoint}"
    headers = {"Authorization": f"Token {API_TOKEN}"}
    if data is None:
        data = {}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    res_json = response.json()
    if res_json.get("code") != 0:
        raise Exception(f"SiYuan API Error ({endpoint}): {res_json.get('msg')}")
    return res_json.get("data")

def get_notebook_id(notebook_name: str) -> str:
    """根据笔记本名称获取笔记本 ID"""
    try:
        data = make_request("notebook/lsNotebooks")
        notebooks = data.get("notebooks", [])
        for nb in notebooks:
            if nb["name"] == notebook_name:
                return nb["id"]
        
        # 抛出明确异常以引导用户
        raise ValueError(f"Notebook '{notebook_name}' not found. Please create it manually in SiYuan first.")
    except requests.exceptions.ConnectionError:
        raise ConnectionError("Cannot connect to SiYuan Note. Is it running on http://127.0.0.1:6806?")

def publish_wiki(wiki_dir: str, notebook_name: str):
    """主推送流程"""
    if not os.path.isdir(wiki_dir):
        logger.error(f"Wiki directory does not exist: {wiki_dir}")
        return
        
    try:
        notebook_id = get_notebook_id(notebook_name)
    except Exception as e:
        logger.error(str(e))
        return
        
    logger.info(f"Connected to SiYuan. Target Notebook: '{notebook_name}' (ID: {notebook_id})")
    
    # 递归查找所有的 markdown 文件
    md_files = glob.glob(os.path.join(wiki_dir, "**", "*.md"), recursive=True)
    if not md_files:
        logger.warning(f"No Markdown files found in {wiki_dir}")
        return
        
    success_count = 0
    for file_path in md_files:
        # 计算相对路径
        rel_path = os.path.relpath(file_path, wiki_dir)
        
        # 转换为思源的文件树路径 (去后缀，加前导斜杠)
        # 例如: concepts/llm4rec.md -> /concepts/llm4rec
        siyuan_path = "/" + rel_path.replace(".md", "")
        
        # 为了兼容 Windows 路径分隔符，将反斜杠替换为正斜杠
        siyuan_path = siyuan_path.replace("\\", "/")
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        logger.info(f"Pushing: {rel_path} -> {siyuan_path}")
        try:
            make_request("filetree/createDocWithMd", {
                "notebook": notebook_id,
                "path": siyuan_path,
                "markdown": content
            })
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to push {rel_path}: {e}")
            
    logger.info(f"Publishing complete. Successfully pushed {success_count}/{len(md_files)} files to notebook '{notebook_name}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish local LLM Wiki to SiYuan Note via API")
    parser.add_argument("--wiki_dir", type=str, default="/Users/salmon/research/wiki", help="Path to the local generated wiki directory")
    parser.add_argument("--notebook", type=str, default="AI_Wiki", help="Target SiYuan notebook name (must exist)")
    
    args = parser.parse_args()
    publish_wiki(args.wiki_dir, args.notebook)
