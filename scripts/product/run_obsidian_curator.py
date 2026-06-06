import argparse
import sys
import os
from datetime import datetime
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.engine import PersonalRecSys
from src.contracts.config import PipelineConfig
from src.utils.embeddings import get_embedder
from src.utils.lm_studio_client import LMStudioLLMClient
from src.profiling.explicit_profile import UserExplicitProfile
from src.services.curator import LLMCurator

from src.utils.rss_loader import fetch_rss_candidates
from src.utils.obsidian_loader import read_obsidian_anchor, write_daily_curation


def main():
    parser = argparse.ArgumentParser(description="Local-First AI Generative Curator MVP")
    parser.add_argument("--feeds", type=str, required=True, help="RSS feeds url separated by comma")
    parser.add_argument("--obsidian-anchor", type=str, required=True, help="Path to Obsidian Active_Project.md")
    parser.add_argument("--obsidian-vault", type=str, required=True, help="Path to Obsidian Vault directory")
    parser.add_argument("--llm-base-url", type=str, default="http://localhost:1234/v1", help="LM Studio or OpenAI compatible base URL")
    parser.add_argument("--llm-api-key", type=str, default="lm-studio", help="API key")
    parser.add_argument("--llm-model", type=str, default="qwen2", help="Model name")
    parser.add_argument("--top-k", type=int, default=3, help="Number of articles to curate")
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🚀 启动 Local-First AI Generative Curator MVP")
    print("="*60)
    
    # 1. 抓取 RSS 源
    feed_urls = [url.strip() for url in args.feeds.split(",") if url.strip()]
    print(f"\n[1] 正在拉取 {len(feed_urls)} 个 RSS 源...")
    candidates = fetch_rss_candidates(feed_urls, max_per_feed=5)
    print(f"    共拉取到 {len(candidates)} 篇文章候选。")
    if not candidates:
        print("未获取到任何文章，流程结束。")
        return
        
    # 2. 读取知识锚点
    print(f"\n[2] 正在读取 Obsidian 知识锚点: {args.obsidian_anchor} ...")
    anchor_text = read_obsidian_anchor(args.obsidian_anchor)
    if not anchor_text:
        anchor_text = "默认知识锚点：寻找有深度的技术与产品创新。"
    print(f"    锚点截取: {anchor_text[:50]}...")
    
    # 3. 初始化 LLM Client
    llm_client = LMStudioLLMClient(
        base_url=args.llm_base_url,
        api_key=args.llm_api_key,
        model=args.llm_model,
        temperature=0.7
    )
    
    # 4. 初始化推荐引擎
    print("\n[3] 初始化推荐引擎，进行多维过滤与排序...")
    config = PipelineConfig(
        embedding_dim=128,
        enable_reranker=True, # 启用大模型重排
        rerank_top_n=args.top_k * 2 # 传给重排器的数量
    )
    recsys = PersonalRecSys(
        embedder=get_embedder("mock", dim=128),  # 粗排使用 Mock embedder 即可
        embedding_dim=128,
        config=config
    )
    
    # 设置显式画像（用作排序规则）
    recsys.explicit_profile = UserExplicitProfile(
        core_topics=[anchor_text[:100]], # 提取部分锚点用于标签匹配
        writing_style=["深度长文", "洞察"],
        content_depth=[],
        negative_tags=["广告", "水文", "营销"],
        authors=[],
        custom_tags={}
    )
    # 注入 LLM Client 给 Reranker
    recsys._orchestrator._reranker.llm_client = llm_client
    
    # 为了满足推荐引擎必须有隐式画像的约束，我们简单构建一个伪装的画像
    mock_collection = [{"title": "背景知识", "content": anchor_text, "url": "local"}]
    recsys.build_profile_from_collection(mock_collection, llm_client=None)
    
    recsys.add_candidates(candidates)
    recsys.embed_candidates()
    
    # 5. 执行排序 (粗排 -> LLM精排)
    results = recsys.recommend(top_k=args.top_k, preset="exploration")
    
    print(f"\n[4] 排序完成。选出了 Top-{len(results.ranked_items)} 篇文章：")
    for r in results.ranked_items:
        print(f"  - [{r.final_score:.2f}] {r.item_id}")
        # 为了在 curator 中能访问到完整内容，我们将它存在 metadata 中
        original_cand = recsys.candidates[r.item_id]
        r.metadata['title'] = original_cand.title
        r.metadata['url'] = original_cand.metadata.get('url', '')
        r.metadata['content_snippet'] = original_cand.content[:500]
        
    # 6. 生成导读
    print("\n[5] 启动 LLM 策展器生成导读...")
    curator = LLMCurator(llm_client)
    curation_content = curator.generate_daily_curation(results.ranked_items, anchor_text)
    
    # 7. 写入 Obsidian
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = write_daily_curation(args.obsidian_vault, date_str, curation_content)
    
    print("\n" + "="*60)
    if output_path:
        print(f"🎉 策展完成！导读已写入：{output_path}")
    else:
        print("写入 Obsidian 失败，请查看日志。")
        print("导读内容如下：")
        print(curation_content)
    print("="*60)

if __name__ == "__main__":
    main()
