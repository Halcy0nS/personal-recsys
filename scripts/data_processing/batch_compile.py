"""
Capsule Batch Compiler (batch_compile.py)
Reads Markdown files from 'datacrawl/rss_crawler/data/md', calls the DeepSeek flash model in Anthropic messages format
to compress the articles into 300-word summaries, preserving original YAML frontmatter, and outputs them to
'datacrawl/rss_crawler/data/compressed'.
"""

import os
import sys
import asyncio
import time
from pathlib import Path
import httpx

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Configurations from environment variables
API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic").rstrip("/")
MODEL = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash")
MAX_CONCURRENCY_ENV = os.environ.get("DEEPSEEK_MAX_CONCURRENCY")
MAX_CONCURRENCY = int(MAX_CONCURRENCY_ENV) if MAX_CONCURRENCY_ENV else 200

INPUT_DIR = Path("datacrawl/rss_crawler/data/md")
OUTPUT_DIR = Path("datacrawl/rss_crawler/data/compressed")

import yaml # Ensure pyyaml is available or do string injection

SYSTEM_PROMPT = """你是一个无情的知识提纯机器。请严格输出以下三部分内容，绝对不要出现任何多余的寒暄和解释：

1. 核心主张 (Core Claims)
2. 关键论据与数据 (Key Arguments)
3. 潜在的反驳视角 (Counter-arguments)
全文请控制在 300 字以内。

【关键指令：强制输出元数据 JSON】
在总结的最后，你必须附加一段 JSON 格式的元数据，用 ```json 和 ``` 包裹，包含以下严格的 Schema：
{
  "topics": ["提取1-3个核心主题词"],
  "depth": "只能是 shallow 或 deep",
  "style": "只能从 [tutorial, opinion, news, paper, analysis] 中选一",
  "quality": "1到5的整数评分",
  "metadata_version": "v1.0.20260604"
}
"""

def split_frontmatter_and_content(file_content: str) -> tuple[str, str]:
    """Split markdown file by --- separator to isolate YAML frontmatter from body."""
    parts = file_content.split('---', 2)
    if len(parts) >= 3:
        frontmatter_text = parts[1]
        main_content = parts[2].strip()
        return frontmatter_text, main_content
    else:
        return "", file_content.strip()

async def compress_article(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    filepath: Path,
    stats: dict
):
    async with semaphore:
        filename = filepath.name
        output_filepath = OUTPUT_DIR / filename
        
        if output_filepath.exists():
            print(f"[~] Skip '{filename}': already compressed.")
            stats["skipped"] += 1
            return
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            frontmatter, body = split_frontmatter_and_content(content)
            if not body:
                print(f"[-] Skip '{filename}': empty body content.")
                stats["skipped"] += 1
                return

            # 检测是否使用 Anthropic / Messages 协议
            is_anthropic = "anthropic" in BASE_URL.lower() or "claude" in MODEL.lower()

            if is_anthropic:
                payload = {
                    "model": MODEL,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": body}],
                    "max_tokens": 1024,
                    "thinking": {"type": "disabled"}
                }
                headers = {
                    "x-api-key": API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                url = f"{BASE_URL}/v1/messages"
            else:
                # 兼容 OpenAI / DeepSeek 官方协议
                payload = {
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": body}
                    ],
                    "max_tokens": 1024
                }
                headers = {
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                }
                base = BASE_URL
                if not base.endswith("/v1") and "api.deepseek.com" in base:
                    base = f"{base}/v1"
                url = f"{base}/chat/completions"

            # Trace
            print(f"[>] Compressing: {filename}...")
            
            t0 = time.time()
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            elapsed = time.time() - t0
            
            if response.status_code != 200:
                print(f"[x] Failed '{filename}': HTTP {response.status_code} - {response.text[:200]}")
                stats["failed"] += 1
                return

            data = response.json()
            summary_text = ""
            if is_anthropic:
                content_blocks = data.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        summary_text += block.get("text", "")
            else:
                choices = data.get("choices", [])
                if choices:
                    summary_text = choices[0].get("message", {}).get("content", "")
            
            summary_text = summary_text.strip()
            
            if not summary_text:
                print(f"[x] Failed '{filename}': empty response content")
                stats["failed"] += 1
                return

            # Extract JSON block
            import re
            import json
            import yaml
            
            json_str = ""
            json_match = re.search(r'```json\s*(.*?)\s*```', summary_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                # Remove JSON block from summary
                summary_text = summary_text.replace(json_match.group(0), "").strip()
            else:
                # Try to find a JSON-like structure if code blocks are missing
                json_match_fallback = re.search(r'(\{.*"metadata_version".*\})', summary_text, re.DOTALL)
                if json_match_fallback:
                    json_str = json_match_fallback.group(1)
                    summary_text = summary_text.replace(json_match_fallback.group(0), "").strip()

            metadata = {}
            if json_str:
                try:
                    metadata = json.loads(json_str)
                except json.JSONDecodeError as e:
                    print(f"[-] Warning: Failed to parse JSON in '{filename}': {e}")
            
            # Parse existing YAML frontmatter if any
            frontmatter_dict = {}
            if frontmatter.strip():
                try:
                    frontmatter_dict = yaml.safe_load(frontmatter) or {}
                except Exception as e:
                    print(f"[-] Warning: Failed to parse YAML in '{filename}': {e}")
            
            # Merge LLM metadata into frontmatter
            for k, v in metadata.items():
                frontmatter_dict[k] = v
                
            # Reconstruct output
            new_frontmatter_yaml = yaml.dump(frontmatter_dict, allow_unicode=True, default_flow_style=False)
            output_content = f"---\n{new_frontmatter_yaml}---\n\n{summary_text}\n"
            
            output_path = OUTPUT_DIR / filename
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(output_content)

            print(f"[✓] Compressed: {filename} ({elapsed:.1f}s)")
            stats["success"] += 1

        except Exception as e:
            print(f"[x] Error processing '{filename}': {e}")
            stats["failed"] += 1

async def main():
    if not API_KEY:
        print("[-] Error: DEEPSEEK_API_KEY environment variable is not set.")
        sys.exit(1)

    if not INPUT_DIR.exists():
        print(f"[-] Error: Input directory '{INPUT_DIR}' does not exist.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted([p for p in INPUT_DIR.glob("*.md") if p.is_file()])
    if not files:
        print(f"[-] No markdown files found in '{INPUT_DIR}'")
        return

    print("=" * 70)
    print(f"🤖 Starting capsule compiler. Files to compile: {len(files)}")
    print(f"  • Model: {MODEL}")
    print(f"  • Base URL: {BASE_URL}")
    print(f"  • Concurrency Limit: {MAX_CONCURRENCY}")
    print(f"  • Output Dir: {OUTPUT_DIR}")
    print("=" * 70)

    stats = {"success": 0, "failed": 0, "skipped": 0}
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    
    t_start = time.time()
    
    async with httpx.AsyncClient() as client:
        tasks = [
            compress_article(client, semaphore, filepath, stats)
            for filepath in files
        ]
        await asyncio.gather(*tasks)

    t_total = time.time() - t_start
    print("=" * 70)
    print("Compilation Complete!")
    print(f"  • Success: {stats['success']}")
    print(f"  • Failed:  {stats['failed']}")
    print(f"  • Skipped: {stats['skipped']}")
    print(f"  • Total Time: {t_total:.1f} seconds")
    print("=" * 70)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Program interrupted by user.")
