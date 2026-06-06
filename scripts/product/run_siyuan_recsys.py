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
from src.profiling.implicit_profile import VectorCloud
from src.services.curator import LLMCurator

from src.utils.rss_loader import fetch_and_compile_rss
from src.utils.siyuan_loader import SiYuanClient, read_siyuan_anchor, fetch_siyuan_favorites, write_siyuan_curation


def run_traditional(args, candidates, llm_client, siyuan_client, embedder):
    print("\n" + "-"*40)
    print("▶ 运行 模式 A：传统推荐流水线")
    print("-"*40)
    
    # 1. 提取全局口味构建隐式画像
    print("[1] 从思源拉取全局历史笔记构建口味模型...")
    favorites = fetch_siyuan_favorites(siyuan_client, limit=20)
    
    recsys = PersonalRecSys(
        embedder=embedder,
        embedding_dim=embedder.dim
    )
    
    if favorites:
        mock_collection = [{"title": f"Note_{i}", "content": text, "url": "local"} for i, text in enumerate(favorites)]
        recsys.build_profile_from_collection(mock_collection, llm_client=llm_client)
    else:
        print("[Warning] 未找到思源笔记历史，隐式画像将为空，可能影响推荐效果。")
        # 兜底
        recsys.build_profile_from_collection([{"title": "Default", "content": "Technology, AI"}], llm_client=llm_client)
        
    # 添加候选
    recsys.add_candidates(candidates)
    recsys.embed_candidates()
    
    # 执行多维排序
    results = recsys.recommend(top_k=args.top_k, preset="balanced")
    
    print(f"\n[2] 排序完成。选出了 Top-{len(results.ranked_items)} 篇文章：")
    
    # 输出高分阅读清单
    markdown_out = f"# 今日推荐清单 ({datetime.now().strftime('%Y-%m-%d')})\n\n"
    markdown_out += "> 基于你思源笔记历史口味生成的精准推荐\n\n"
    for r in results.ranked_items:
        original_cand = recsys.candidates[r.item_id]
        score = r.final_score
        title = original_cand.title
        url = original_cand.metadata.get('url', '')
        markdown_out += f"## [{score:.2f}] [{title}]({url})\n"
        markdown_out += f"**核心摘要**：\n{original_cand.content[:300]}...\n\n"
        print(f"  - [{score:.2f}] {title}")
        
    # 写入思源
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = write_siyuan_curation(siyuan_client, args.siyuan_notebook, f"{date_str}-传统推荐单", markdown_out)
    if output_path:
        print(f"🎉 传统推荐清单已写入思源：{output_path}")


def run_karpathy(args, candidates, llm_client, siyuan_client, embedder):
    print("\n" + "-"*40)
    print("▶ 运行 模式 B：类卡帕西工作流")
    print("-"*40)
    
    # 1. 提取意图锚点
    print(f"[1] 正在拉取思源知识锚点: {args.siyuan_anchor} ...")
    anchor_text = read_siyuan_anchor(siyuan_client, args.siyuan_anchor)
    if not anchor_text:
        anchor_text = "默认探索意图：寻找有深度的技术、产品和 AI 创新，打破信息茧房。"
    print(f"    锚点截取: {anchor_text[:50]}...")
    
    # 2. 配置带 LLM 重排的推荐引擎
    config = PipelineConfig(
        embedding_dim=embedder.dim,
        enable_reranker=True,
        rerank_top_n=args.top_k * 2
    )
    recsys = PersonalRecSys(
        embedder=embedder,
        embedding_dim=embedder.dim,
        config=config
    )
    
    # 显式画像传入锚点
    recsys.explicit_profile = UserExplicitProfile(
        core_topics=[anchor_text[:200]],
        writing_style=["深度长文", "洞察"],
        content_depth=[],
        negative_tags=["广告", "水文"],
        authors=[],
        custom_tags={}
    )
    recsys._orchestrator._reranker.llm_client = llm_client
    
    # Mock隐式画像满足前置条件
    recsys.build_profile_from_collection([{"title": "背景知识", "content": anchor_text}], llm_client=None)
    
    recsys.add_candidates(candidates)
    recsys.embed_candidates()
    
    # 3. 对撞筛选
    print("\n[2] 将锚点与压缩版文章交由 LLM 进行对撞与筛选 (Reranking)...")
    results = recsys.recommend(top_k=args.top_k, preset="exploration")
    
    print(f"    对撞完成。选出了最强关联的 Top-{len(results.ranked_items)} 篇。")
    for r in results.ranked_items:
        original_cand = recsys.candidates[r.item_id]
        r.metadata['title'] = original_cand.title
        r.metadata['url'] = original_cand.metadata.get('url', '')
        r.metadata['content_snippet'] = original_cand.content
        
    # 4. 生成策展导读
    print("\n[3] 启动 LLM 策展器生成综合导读...")
    curator = LLMCurator(llm_client)
    curation_content = curator.generate_daily_curation(results.ranked_items, anchor_text)
    
    # 5. 写入思源
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = write_siyuan_curation(siyuan_client, args.siyuan_notebook, f"{date_str}-卡帕西导读", curation_content)
    if output_path:
        print(f"🎉 卡帕西导读已写入思源：{output_path}")


def main():
    parser = argparse.ArgumentParser(description="SiYuan Dual-Method AI Generative Curator MVP")
    parser.add_argument("--mode", type=str, choices=["traditional", "karpathy", "both"], default="both", help="推荐模式")
    parser.add_argument("--siyuan-url", type=str, default="http://127.0.0.1:6806", help="思源 API 地址")
    parser.add_argument("--siyuan-token", type=str, default="", help="思源 API Token")
    parser.add_argument("--siyuan-notebook", type=str, default="", help="写入的思源笔记本 ID (为空则写本地)")
    parser.add_argument("--siyuan-anchor", type=str, default="我的近期思考：大语言模型与个人知识管理的融合。", help="思源文档ID或直接输入的锚点文本")
    parser.add_argument("--llm-base-url", type=str, default="https://api.deepseek.com/v1", help="LLM Base URL")
    parser.add_argument("--llm-api-key", type=str, default=os.getenv("DEEPSEEK_API_KEY", ""), help="API key")
    parser.add_argument("--llm-model", type=str, default="deepseek-chat", help="Model name")
    parser.add_argument("--reasoning-effort", type=str, default="medium", help="Reasoning effort for reasoning models (e.g. low, medium, high)")
    parser.add_argument("--top-k", type=int, default=3, help="Number of articles to curate")
    parser.add_argument("--embedder-type", type=str, default="lmstudio", choices=["mock", "lmstudio", "openai", "local"], help="Embedder type")
    parser.add_argument("--embedder-url", type=str, default="https://generativelanguage.googleapis.com/v1beta/openai/v1", help="Embedder API URL")
    parser.add_argument("--embedder-api-key", type=str, default="AIzaSyCy2esuHFZWQDaSmJkO7cttLzKa3OOK52Y", help="Embedder API Key")
    parser.add_argument("--embedder-model", type=str, default="gemini-embedding-2", help="Embedder Model Name")
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🚀 启动 SiYuan Dual-Method AI Generative Curator MVP")
    print("="*60)
    
    # 默认抓取的 11 个技术源
    default_feeds = [
        "https://openai.com/news/rss.xml",
        "https://blog.pragmaticengineer.com/rss/",
        "https://jvns.ca/atom.xml",
        "https://danluu.com/atom.xml",
        "https://hnrss.org/frontpage",
        "https://www.lesswrong.com/feed.xml",
        "https://astralcodexten.substack.com/feed",
        "https://forum.effectivealtruism.org/feed.xml",
        "https://aeon.co/feed",
        "https://overcomingbias.substack.com/feed",
        "https://www.ribbonfarm.com/feed/"
    ]
    
    # 初始化 LLM (DeepSeek V4-Pro/medium configuration requested by user mapped to standard deepseek parameters)
    extra_body = {}
    if args.reasoning_effort:
        extra_body["reasoning_effort"] = args.reasoning_effort
        
    llm_client = LMStudioLLMClient(
        base_url=args.llm_base_url,
        api_key=args.llm_api_key,
        model=args.llm_model,
        temperature=0.6,
        timeout=120,
        extra_body=extra_body
    )
    
    siyuan_client = SiYuanClient(args.siyuan_url, args.siyuan_token)
    
    # 动态确定 Embedding 维度
    if args.embedder_type == "lmstudio":
        embedding_dim = 3072 if "gemini" in args.embedder_model.lower() else 1024
    elif args.embedder_type == "mock":
        embedding_dim = 128
    else:
        embedding_dim = 1024

    # 初始化 Embedder
    print(f"\n[Init] 正在初始化 Embedder ({args.embedder_type} - {args.embedder_model}, 维度: {embedding_dim})...")
    if args.embedder_type == "lmstudio":
        embedder = get_embedder("lmstudio", base_url=args.embedder_url, api_key=args.embedder_api_key, model=args.embedder_model, dim=embedding_dim)
    else:
        embedder = get_embedder(args.embedder_type, dim=embedding_dim)
    
    # 0. 预处理：深度抓取与压缩 (公共环节)
    print(f"\n[0] 正在拉取 {len(default_feeds)} 个 RSS 源并使用 Jina+LLM 进行压缩...")
    # 为了演示/不耗费过长时间，这里可以限制 max_per_feed，实际上生产环境可以去掉限制
    candidates = fetch_and_compile_rss(default_feeds, llm_client, max_per_feed=1) 
    print(f"    共生成了 {len(candidates)} 篇高密度压缩版候选文章。")
    if not candidates:
        print("未获取到任何文章，流程结束。")
        return
        
    # 双轨运行
    if args.mode in ["traditional", "both"]:
        run_traditional(args, candidates, llm_client, siyuan_client, embedder)
        
    if args.mode in ["karpathy", "both"]:
        run_karpathy(args, candidates, llm_client, siyuan_client, embedder)

if __name__ == "__main__":
    main()
