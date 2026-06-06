#!/usr/bin/env python3
"""
MVP Daily Orchestrator (run_daily_mvp.py)
一键执行脚本：串联爬虫、大模型压缩、精排推荐与思源笔记交付。
"""

import sys
import os
import time
import subprocess
from pathlib import Path
from datetime import datetime

# 将当前项目根目录加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.engine import PersonalRecSys
from src.contracts.config import PipelineConfig
from src.utils.embeddings import get_embedder
from src.utils.wiki_loader import load_wiki_candidates
from scripts.publish_wiki_to_siyuan import make_request, get_notebook_id
from scripts.harvest_feedback import harvest_siyuan_feedback

def step_0_harvest():
    try:
        harvest_siyuan_feedback()
    except Exception as e:
        print(f"✗ 收集历史反馈失败: {e}")

def step_1_ingest():
    print("\n[1/4] 开始数据摄取 (Crawler) ...")
    t0 = time.time()
    # 执行 GraphQL 爬虫 (仅爬取最近几天的数据)
    script_path = os.path.join("datacrawl", "rss_crawler", "lesswrong.py")
    if os.path.exists(script_path):
        subprocess.run([sys.executable, script_path], check=True)
        print(f"✓ 爬虫执行完毕，耗时: {time.time()-t0:.2f}s")
    else:
        print(f"✗ 警告: 找不到爬虫脚本 {script_path}，跳过摄取阶段。")

def step_2_compile():
    print("\n[2/4] 开始高密度知识压缩 (Batch Compile) ...")
    t0 = time.time()
    script_path = os.path.join("scripts", "data_processing", "batch_compile.py")
    if os.path.exists(script_path):
        # 传入必要环境变量
        env = os.environ.copy()
        env["DEEPSEEK_MAX_CONCURRENCY"] = "10"
        subprocess.run([sys.executable, script_path], env=env, check=True)
        print(f"✓ 压缩编译完毕，耗时: {time.time()-t0:.2f}s")
    else:
        print(f"✗ 警告: 找不到编译脚本 {script_path}，请确保胶囊已生成。")

def step_3_recommend() -> tuple[list, dict]:
    print("\n[3/4] 开始双轨精排推荐 (I2I + SiliconFlow Qwen3 Reranker) ...")
    t0 = time.time()
    wiki_dir = "/Users/salmon/research/wiki"
    capsule_dir = "datacrawl/rss_crawler/data/compressed"

    config = PipelineConfig(
        embedding_dim=768, 
        top_k=5,
        preset="precision",
        enable_reranker=True,
        embedder_type="gemini",
        reranker_model="qwen3-reranker-8b"
    )

    print("  - 初始化 Gemini Embedder 与 SiliconFlow Reranker")
    embedder = get_embedder("gemini", dim=config.embedding_dim)
    
    recsys = PersonalRecSys(embedder=embedder, config=config)

    # 加载 Wiki 画像
    print("  - 加载 Wiki 画像库")
    wiki_candidates = load_wiki_candidates(wiki_dir)
    wiki_collection = [
        {"title": c.title, "content": c.content, "source": "wiki"} for c in wiki_candidates
    ]
    recsys.build_profile_from_collection(wiki_collection, llm_client=None)

    # 加载候选胶囊
    print("  - 加载侯选胶囊并进行匹配")
    candidates = load_wiki_candidates(capsule_dir)
    recsys.add_candidates(candidates)
    recsys.embed_candidates(batch_size=10)

    # 执行推荐
    results = recsys.recommend(top_k=config.top_k, preset=config.preset)
    print(f"✓ 推荐计算完毕，耗时: {time.time()-t0:.2f}s")
    return results.ranked_items, recsys.candidates

def step_4_delivery(ranked_items, candidates):
    print("\n[4/4] 开始生成今日简报并推送至 SiYuan ...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    md_content = f"# 帕西卡外脑：今日专属知识简报 ({date_str})\n\n"
    md_content += "基于您 Wiki 知识图谱的深度对撞，以下是系统为您挑选的 Top 5 必读：\n\n---\n\n"

    for idx, item in enumerate(ranked_items):
        cand = candidates.get(item.item_id)
        if not cand: continue
        
        frontmatter = cand.metadata.get("frontmatter", {})
        author = frontmatter.get("author", "Unknown")
        url = frontmatter.get("url", "")
        
        md_content += f"## {idx+1}. [{cand.title}]({url})\n"
        md_content += f"> **作者**: {author} | **综合推荐指数**: {item.final_score:.3f}\n>\n"
        
        # 处理 Reranker 返回的 reasoning
        if hasattr(item, "component_scores") and "rerank" in item.component_scores:
            md_content += f"> 💡 **AI 推荐理由**: {item.reasoning if hasattr(item, 'reasoning') else '高度契合核心研究方向'}\n\n"
        else:
            md_content += "> 💡 **AI 推荐理由**: (纯向量匹配命中)\n\n"
            
        # 内容摘要截断
        preview = cand.content.strip().split("\n")[0][:200]
        md_content += f"**摘要**：{preview}...\n\n"
        
        # 交互面板
        md_content += f"<!-- item_id: {item.item_id} -->\n"
        md_content += "**【交互面板】**\n"
        md_content += "- [ ] 👍 值得一读\n"
        md_content += "- [ ] 👎 毫无兴趣 (可选原因：[ ] 主题不关 [ ] 太浅/太水 [ ] 来源太差 [ ] 重复看过)\n\n---\n"

    # 使用默认的笔记本，如果在您的环境中不存在，请修改为实际的笔记本名称
    notebook_name = "AI_Wiki"
    target_path = f"/Inbox/Daily/今日简报_{date_str}"
    
    try:
        notebook_id = get_notebook_id(notebook_name)
        # 这里尝试调用 push 接口
        resp = make_request("filetree/createDocWithMd", {
            "notebook": notebook_id,
            "path": target_path,
            "markdown": md_content
        })
        print(f"✓ 成功推送至 SiYuan: {target_path}")
    except Exception as e:
        print(f"⚠ 调用 SiYuan API 异常: {e}")
        with open(f"今日简报_{date_str}.md", "w", encoding="utf-8") as f:
            f.write(md_content)

def main():
    print("="*60)
    print("  🚀 启动帕西卡引擎 (Pasika MVP Daily Run)")
    print("="*60)
    
    try:
        step_0_harvest()
        # step_1_ingest() # 暂时注释，避免在测试期间重复抓取
        # step_2_compile() # 暂时注释，使用已有的胶囊
        ranked_items, candidates = step_3_recommend()
        if ranked_items:
            step_4_delivery(ranked_items, candidates)
        else:
            print("⚠ 未推荐出任何内容。")
    except Exception as e:
        print(f"\n❌ MVP 运行异常中断: {e}")

if __name__ == "__main__":
    main()
