#!/usr/bin/env python3
import asyncio
import json
import logging
import urllib.request
import urllib.error
import websockets
import subprocess
import time
from datetime import datetime
import os
import sys

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PasikaDaemon")

SIYUAN_URL = "http://127.0.0.1:6806"
SIYUAN_WS = "ws://127.0.0.1:6806/ws"
SIYUAN_TOKEN = os.environ.get("SIYUAN_TOKEN", "")

NOTEBOOK_NAME = "AI_Wiki"
DOC_PATH = "/🤖 Pasika 引擎控制中心"
DOC_TITLE = "🤖 Pasika 引擎控制中心"

def _post(endpoint: str, data: dict) -> dict:
    url = f"{SIYUAN_URL}/api/{endpoint}"
    payload = json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if SIYUAN_TOKEN:
        headers["Authorization"] = f"Token {SIYUAN_TOKEN}"

    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"SiYuan API Request Failed [{endpoint}]: {e}")
        return {}

def query_sql(stmt: str):
    res = _post("query/sql", {"stmt": stmt})
    return res.get("data", [])

def get_notebook_id() -> str:
    res = _post("notebook/lsNotebooks", {})
    for nb in res.get("data", {}).get("notebooks", []):
        if nb.get("name") == NOTEBOOK_NAME:
            return nb.get("id")
    return None

def find_or_create_control_panel(notebook_id: str):
    # Check if exists
    res = _post("filetree/listDocsByPath", {"notebook": notebook_id, "path": "/"})
    for f in res.get("data", {}).get("files", []):
        if f.get("name").replace(".sy", "") == DOC_TITLE:
            return f.get("id")
    
    # Create
    initial_md = f"""# {DOC_TITLE}

> 欢迎回到外脑主脑。

## 🛠️ 执行面板
- [ ] 🚀 **执行今日全自动推荐** 
"""
    res = _post("filetree/createDocWithMd", {
        "notebook": notebook_id,
        "path": DOC_PATH,
        "markdown": initial_md
    })
    logger.info("Created Pasika Control Panel.")
    return res.get("data")

def get_trigger_block_id(doc_id: str):
    # Search for the block starting with "- [ ] 🚀" or "- [x] 🚀" in the document
    blocks = query_sql(f"SELECT * FROM blocks WHERE root_id='{doc_id}' AND type='i' AND markdown LIKE '%🚀 **执行今日全自动推荐**%'")
    if blocks:
        return blocks[0]["id"]
    return None

def update_block(block_id: str, markdown: str):
    _post("block/updateBlock", {
        "id": block_id,
        "dataType": "markdown",
        "data": markdown
    })

async def run_pipeline(block_id: str):
    logger.info("Triggering Daily MVP Pipeline...")
    # Provide visual feedback
    update_block(block_id, "- [ ] ⏳ **正在执行今日全自动推荐中...** (这可能需要几分钟，请勿重复点击)")
    
    try:
        # Run the pipeline script
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "run_daily_mvp.py"))
        process = await asyncio.create_subprocess_exec(
            sys.executable, script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            logger.info("Pipeline completed successfully.")
            now = datetime.now().strftime("%H:%M:%S")
            update_block(block_id, f"- [ ] 🚀 **执行今日全自动推荐** (上次成功: {now})")
        else:
            logger.error(f"Pipeline failed with code {process.returncode}")
            logger.error(f"Stderr: {stderr.decode()}")
            update_block(block_id, f"- [ ] ❌ **执行失败，请查看日志**")
            
    except Exception as e:
        logger.error(f"Failed to run pipeline: {e}")
        update_block(block_id, f"- [ ] ❌ **执行发生异常**")

async def listen():
    notebook_id = get_notebook_id()
    if not notebook_id:
        logger.error(f"Notebook '{NOTEBOOK_NAME}' not found.")
        return

    doc_id = find_or_create_control_panel(notebook_id)
    if not doc_id:
        logger.error("Failed to find or create Control Panel.")
        return
        
    # Wait a bit for indexing if just created
    time.sleep(1)
    
    trigger_block_id = get_trigger_block_id(doc_id)
    if not trigger_block_id:
        logger.warning("Trigger block not found immediately. It will be resolved dynamically.")

    # Reset block just in case it was stuck
    if trigger_block_id:
        update_block(trigger_block_id, "- [ ] 🚀 **执行今日全自动推荐** ")
        logger.info(f"Tracking Trigger Block ID: {trigger_block_id}")

    is_running = False

    try:
        async with websockets.connect(SIYUAN_WS) as websocket:
            logger.info("Connected to SiYuan WebSocket. Listening for UI events...")
            while True:
                try:
                    message = await websocket.recv()
                    data = json.loads(message)
                    cmd = data.get("cmd")
                    if cmd == "transactions":
                        for tx in data.get("data", []):
                            for op in tx.get("doOperations", []):
                                if op.get("action") == "update":
                                    block_id = op.get("id")
                                    # If we don't have trigger_block_id, try fetching it again
                                    if not trigger_block_id:
                                        trigger_block_id = get_trigger_block_id(doc_id)
                                        
                                    if block_id == trigger_block_id and not is_running:
                                        # Small delay to let SiYuan SQLite commit the transaction
                                        await asyncio.sleep(0.5)
                                        # Query DB to see if it's checked
                                        b_data = query_sql(f"SELECT * FROM blocks WHERE id='{block_id}'")
                                        if b_data:
                                            md = b_data[0].get("markdown", "")
                                            # SiYuan sometimes uses capital X for checked tasks
                                            if md.lower().startswith("- [x]") or md.lower().startswith("* [x]"):
                                                logger.info("Checkbox ticked! Launching pipeline...")
                                                is_running = True
                                                
                                                async def task_wrapper(bid):
                                                    nonlocal is_running
                                                    await run_pipeline(bid)
                                                    is_running = False
                                                
                                                asyncio.create_task(task_wrapper(block_id))
                                                
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")

if __name__ == "__main__":
    asyncio.run(listen())
