import re
from publish_wiki_to_siyuan import make_request, get_notebook_id
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.wiki_loader import load_wiki_candidates

date_str = datetime.now().strftime("%Y-%m-%d")
filepath = f"今日简报_{date_str}.md"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

candidates = load_wiki_candidates("datacrawl/rss_crawler/data/compressed")
title_to_id = {c.title: c.item_id for c in candidates}

blocks = content.split("---")
new_blocks = []

for block in blocks:
    if "## " in block and "[**" not in block:
        # Match title
        match = re.search(r'## \d+\. \[(.*?)\]\(', block)
        if match:
            title = match.group(1)
            item_id = title_to_id.get(title, "unknown_id")
            
            panel = f"""
<!-- item_id: {item_id} -->
**【交互面板】**
- [ ] 👍 值得一读
- [ ] 👎 毫无兴趣 (可选原因：[ ] 主题不关 [ ] 太浅/太水 [ ] 来源太差 [ ] 重复看过)
"""
            block = block.rstrip() + "\n" + panel + "\n"
    new_blocks.append(block)

new_content = "---\n".join(new_blocks)

notebook_name = "AI_Wiki"
target_path = f"/Inbox/Daily/今日简报_{date_str}"
notebook_id = get_notebook_id(notebook_name)
resp = make_request("filetree/createDocWithMd", {
    "notebook": notebook_id,
    "path": target_path,
    "markdown": new_content
})
print(f"✓ 成功快速推送至 SiYuan: {target_path}")
