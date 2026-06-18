#!/usr/bin/env python3
"""
反馈收割机 (Feedback Harvester)
从思源笔记中读取最新的《今日简报》，解析用户的 Checkbox 反馈，
并更新本地的 FeedbackMemory 状态层。
"""

import os
import sys
import re
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.publish_wiki_to_siyuan import make_request
from src.profiling.feedback_memory import FeedbackMemory
from src.utils.wiki_loader import load_wiki_candidates
from src.utils.embeddings import get_embedder

def harvest_siyuan_feedback():
    print("\n[Feedback Harvester] 开始扫描思源笔记历史简报...")
    
    # 查找最近的简报 (SQL 查询思源数据库)
    query = "SELECT * FROM blocks WHERE type='d' AND content LIKE '%今日专属知识简报%' ORDER BY created DESC LIMIT 1"
    try:
        resp = make_request("query/sql", {"stmt": query})
        data = resp.get("data", [])
        if not data:
            print("[Feedback Harvester] 未在思源笔记中找到任何历史简报，跳过。")
            return
            
        doc_id = data[0]["id"]
        # 获取该文档的 Markdown 内容
        doc_resp = make_request("export/exportMdContent", {"id": doc_id})
        md_content = doc_resp.get("data", "").get("content", "")
    except Exception as e:
        print(f"[Feedback Harvester] 无法连接思源笔记 ({e})，尝试读取本地备份的最新简报...")
        # 本地兜底
        date_str = datetime.now().strftime("%Y-%m-%d")
        fallback_path = f"今日简报_{date_str}.md"
        if os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8") as f:
                md_content = f.read()
        else:
            print("[Feedback Harvester] 本地也无简报记录，跳过。")
            return

    # 解析 Markdown
    # 匹配模式:
    # <!-- item_id: xxx -->
    # - [x] 👍 ...
    # - [x] 👎 ... (可选原因：[x] 主题不关 [ ] 太浅/太水 [ ] 来源太差 [ ] 重复看过)
    
    pattern = re.compile(
        r'<!-- item_id: (.*?) -->\s*'
        r'\*\*【交互面板】\*\*\s*'
        r'- \[(.)\] 👍.*?\n\s*'
        r'- \[(.)\] 👎.*?\(\s*可选原因：\s*'
        r'\[(.)\] 主题不关\s*'
        r'\[(.)\] 太浅/太水\s*'
        r'\[(.)\] 来源太差\s*'
        r'\[(.)\] 重复看过\s*\)', re.DOTALL
    )
    
    feedbacks = []
    for match in pattern.finditer(md_content):
        item_id = match.group(1).strip()
        like = match.group(2).strip().lower() == 'x'
        dislike = match.group(3).strip().lower() == 'x'
        
        reason_topic = match.group(4).strip().lower() == 'x'
        reason_shallow = match.group(5).strip().lower() == 'x'
        reason_source = match.group(6).strip().lower() == 'x'
        reason_duplicate = match.group(7).strip().lower() == 'x'
        
        feedbacks.append({
            "item_id": item_id,
            "like": like,
            "dislike": dislike,
            "reason_topic": reason_topic,
            "reason_shallow": reason_shallow,
            "reason_source": reason_source,
            "reason_duplicate": reason_duplicate
        })

    if not feedbacks:
        print("[Feedback Harvester] 未在简报中发现任何有效的交互面板，可能未答复。")
        return

    print(f"[Feedback Harvester] 发现 {len(feedbacks)} 个交互面板记录。")

    # 过滤出有反馈的项
    active_feedbacks = [f for f in feedbacks if f["like"] or f["dislike"]]
    if not active_feedbacks:
        print("[Feedback Harvester] 用户未做任何打勾勾选，结束收集。")
        return

    # 加载候选池和 Embedder (需要获取对应的向量和元数据)
    candidates = load_wiki_candidates("datacrawl/rss_crawler/data/compressed")
    cand_dict = {c.item_id: c for c in candidates}
    
    # 检测 LM Studio 是否在线
    lm_studio_url = "http://localhost:1234/v1"
    use_lmstudio = False
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{lm_studio_url}/models", timeout=2)
        use_lmstudio = True
    except Exception:
        use_lmstudio = False

    if use_lmstudio:
        print("  ✓ 检测到 LM Studio 在线，Feedback Harvester 使用本地 BGE 模型进行文本向量化 (1024维)。")
        embedder = get_embedder(
            "lmstudio",
            dim=1024,
            base_url=lm_studio_url,
            model="text-embedding-bge-large-zh-v1.5"
        )
    else:
        print("  ! LM Studio 未启动。Feedback Harvester 自动回退使用 Google Gemini 进行文本向量化 (768维)。")
        embedder = get_embedder("gemini", dim=768)

    fml = FeedbackMemory()

    processed_count = 0
    for fb in active_feedbacks:
        item_id = fb["item_id"]
        cand = cand_dict.get(item_id)
        if not cand:
            print(f"[-] 未找到 ID 为 {item_id} 的候选文章，跳过。")
            continue
            
        # 实时 Embedding (使用统一的 string 参数)
        vector = embedder.embed(cand.content[:2000])

        
        metadata = cand.metadata.get("frontmatter", {})
        source = cand.metadata.get("source", "unknown")
        author = metadata.get("author", "unknown")
        depth = metadata.get("depth", "unknown")
        style = metadata.get("style", "unknown")
        topics = metadata.get("topics", [])

        if fb["like"]:
            fml.add_positive(
                item_id=item_id, 
                vector=vector, 
                source=source, 
                author=author, 
                facets=[depth, style] + topics
            )
            print(f"[+] 记录 👍 喜欢: {cand.title[:20]}")
            processed_count += 1
            
        elif fb["dislike"]:
            reason_provided = fb["reason_topic"] or fb["reason_shallow"] or fb["reason_source"] or fb["reason_duplicate"]
            
            # 如果什么原因都没选，默认就是主题不相关
            is_topic = fb["reason_topic"] or (not reason_provided)
            
            print(f"[-] 记录 👎 踩 ({cand.title[:20]}) -> ", end="")
            reasons_log = []
            if is_topic:
                fml.add_negative_topic(item_id, vector, facets=topics)
                reasons_log.append("主题不相关")
            if fb["reason_shallow"]:
                fml.add_negative_facet(facets=[depth, style])
                reasons_log.append("太浅/太水")
            if fb["reason_source"]:
                fml.add_negative_source(source=source, author=author)
                reasons_log.append("来源太差")
            if fb["reason_duplicate"]:
                fml.add_duplicate(item_id, vector)
                reasons_log.append("重复看过")
                
            print(" & ".join(reasons_log))
            processed_count += 1

    print(f"[Feedback Harvester] 反馈收集完毕。共处理 {processed_count} 条信号。")

if __name__ == "__main__":
    harvest_siyuan_feedback()
