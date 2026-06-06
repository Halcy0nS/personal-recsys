"""
Passive Auto-Recommendation Engine Demonstration Script.
Loads SiYuan Wiki notes as user interest profile (Vector Cloud + Explicit Profile) and LessWrong articles as candidate pool.
Performs semantic retrieval matching (I2I), tags matching, and LLM pointwise reranking without manual query input.
"""

import sys
import os
import time
import json
import argparse
from typing import List, Dict

# Add the project root to the python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.engine import PersonalRecSys, CandidateItem
from src.contracts.config import PipelineConfig
from src.contracts.types import ProfileContext
from src.utils.embeddings import get_embedder
from src.utils.wiki_loader import load_wiki_candidates

CACHE_DIR = "./data/auto_recommendation_cache"

def build_engine_with_detection() -> tuple[PersonalRecSys, PipelineConfig, any]:
    """检测 LM Studio 是否在线并构建对应的推荐引擎"""
    config = PipelineConfig(
        embedding_dim=1024,
        top_k=5,
        preset="precision",  # 精确匹配模式，重在寻找相似的研究方向
        batch_size=16,
        cache_dir=CACHE_DIR,
        enable_reranker=True,  # 开启重排器 (Stage 2)
        rerank_top_n=20        # 粗排选出 Top-20 送入 LLM 精排
    )
    
    lm_studio_url = "http://localhost:1234/v1"
    
    print("\n[0] 检查 LM Studio 状态...")
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{lm_studio_url}/models", timeout=2)
        models_data = json.loads(resp.read().decode())
        model_ids = [m["id"] for m in models_data.get("data", [])]
        print(f"  ✓ LM Studio 在线! 检查到模型: {model_ids}")
        
        # 默认推荐模型配置
        config.embedder_type = "lmstudio"
        config.lm_studio_base_url = lm_studio_url
        
        embedder = get_embedder(
            "lmstudio",
            dim=config.embedding_dim,
            base_url=config.lm_studio_base_url,
            model=config.embedding_model,
        )
        
        # 强制将 llm_client 设为 None，绝不使用 qwen3.5 9b
        llm_client = None
        print("  ✓ 已成功连接 LM Studio (使用 BGE Embedding, 禁用 Qwen 3.5 9b 画像抽取，只使用已启动的 Reranker)")
    except Exception as e:
        print(f"  ✗ LM Studio 未启动或连接超时: {e}")
        print("  ✓ 自动降级为 MockEmbedder，并跳过 LLM 画像处理与 LLM 重排进行本地快速演示")
        config.embedder_type = "mock"
        config.enable_reranker = False  # 降级关闭重排
        embedder = get_embedder("mock", dim=config.embedding_dim)
        llm_client = None

    recsys = PersonalRecSys(
        embedder=embedder,
        embedding_dim=config.embedding_dim,
        cache_dir=CACHE_DIR,
        config=config,
    )
    
    return recsys, config, llm_client

def main():
    parser = argparse.ArgumentParser(description="运行全自动被动推荐引擎 (含 LLM Reranker)")
    parser.add_argument("--wiki_dir", type=str, default="/Users/salmon/research/wiki", help="用户 SiYuan Wiki 知识库路径")
    parser.add_argument("--lesswrong_dir", type=str, default="datacrawl/rss_crawler/data/md", help="爬取的 LessWrong Markdown 文件目录")
    args = parser.parse_args()

    print("=" * 80)
    print("      Personal RecSys - 全自动被动推荐引擎 (Wiki 兴趣图谱对撞 LessWrong)")
    print("=" * 80)
    print(f"  用户画像来源 (Wiki): {args.wiki_dir}")
    print(f"  新候选内容 (LessWrong): {args.lesswrong_dir}")
    print("-" * 80)

    # 0. 初始化引擎
    recsys, config, llm_client = build_engine_with_detection()

    # 1. 加载 Wiki 个人知识库，并构建用户画像
    print(f"\n[1] 正在加载私人知识库 Wiki 笔记...")
    wiki_candidates = load_wiki_candidates(args.wiki_dir)
    if not wiki_candidates:
        print("  ✗ 错误: 未能在指定路径找到 Wiki Markdown 文件！请确认 Wiki 目录是否正确。")
        return
        
    print(f"  ✓ 成功读取了 {len(wiki_candidates)} 篇本地 Wiki 笔记，正在构建/更新高维画像...")
    
    # 转换为画像构建所需的 Dict 结构
    wiki_collection = [
        {
            "title": cand.title,
            "content": cand.content,
            "url": cand.metadata.get("path", "") if cand.metadata else "",
            "source": "wiki"
        }
        for cand in wiki_candidates
    ]
    
    t0 = time.time()
    
    # 暂存已从缓存加载的显式画像
    cached_explicit = recsys.explicit_profile
    
    profile_summary = recsys.build_profile_from_collection(wiki_collection, llm_client=llm_client)
    
    # 恢复或生成默认的显式画像，供 Reranker 使用，防止被覆盖为 None
    if llm_client is None:
        if cached_explicit is not None:
            recsys.explicit_profile = cached_explicit
            print("  ✓ 恢复已缓存的显式画像，跳过 LLM 画像重新抽取。")
        else:
            from src.profiling.explicit_profile import UserExplicitProfile
            recsys.explicit_profile = UserExplicitProfile(
                core_topics=["认知心理学", "分布式系统", "个人效率"],
                writing_style=["深度长文", "逻辑严密"],
                content_depth=["专业级"],
                negative_tags=["情绪输出", "软广"],
                authors=[],
                custom_tags={}
            )
            print("  ✓ 未检测到已缓存的显式画像，已初始化默认画像进行重排。")
            
        # 更新 profile summary
        profile_summary = recsys.get_profile_summary()

    print(f"  ✓ 画像构建完成，耗时: {time.time() - t0:.2f}s")
    print(f"  画像特征云摘要: 已学习 {profile_summary.get('vector_count', 0)} 个高维兴趣锚点")
    if profile_summary.get("has_explicit_profile"):
        print(f"  显式研究兴趣点: {', '.join(profile_summary.get('core_topics', []))}")
        print(f"  偏好文风: {', '.join(profile_summary.get('writing_style', []))}")

    # 2. 加载新文章候选池 (LessWrong)
    print(f"\n[2] 正在加载 LessWrong 候选文章...")
    lesswrong_candidates = load_wiki_candidates(args.lesswrong_dir)
    if not lesswrong_candidates:
        print("  ✗ 错误: 未能在指定路径找到 LessWrong Markdown 文件！请先运行 lesswrong.py 爬虫。")
        return
    print(f"  ✓ 成功读取了 {len(lesswrong_candidates)} 篇 LessWrong 候选文章")

    # 3. 添加候选并进行文本向量化
    print(f"\n[3] 正在对候选文章进行向量化 Embedding 计算...")
    t0 = time.time()
    recsys.add_candidates(lesswrong_candidates)
    recsys.embed_candidates(batch_size=config.batch_size)
    print(f"  ✓ 向量计算与缓存加载完成，耗时: {time.time() - t0:.2f}s")

    # 4. 全自动多维匹配与融合排序
    print(f"\n[4] 启动高维特征交叉（I2I 匹配）、标签规则匹配与大模型精排重排 (LLM Reranker)...")
    t0 = time.time()
    
    # 构造 ProfileContext 以直接调用编排器，从而保留并获取 rerank_details
    profile_ctx = ProfileContext(
        vector_cloud=recsys.vector_cloud,
        explicit_profile=recsys.explicit_profile,
        summary=recsys.get_profile_summary()
    )
    
    raw_result = recsys._orchestrator.recommend(
        candidates=recsys.candidates,
        profile_ctx=profile_ctx,
        top_k=config.top_k,
        preset=config.preset,
        collection_items=recsys.collection_items,
    )
    print(f"  ✓ 推荐匹配与重排完成，耗时: {time.time() - t0:.3f}s")

    # 5. 终端结果展示
    print("\n" + "=" * 80)
    print(f"🌟 为您从 {len(lesswrong_candidates)} 篇 LessWrong 新文章中，筛选出最契合您知识库的前 {config.top_k} 篇深度好文 🌟")
    print("=" * 80)

    ranked_items = raw_result.get("ranked_items", [])
    if not ranked_items:
        print("抱歉，未找到符合筛选标准的推荐文章。")
        return

    rerank_details = raw_result.get("rerank_details")

    for idx, item in enumerate(ranked_items):
        cand = recsys.candidates.get(item.item_id)
        if not cand:
            continue
            
        title = cand.title
        frontmatter = cand.metadata.get("frontmatter", {})
        author = frontmatter.get("author", "Unknown")
        published = frontmatter.get("published", "Unknown")
        url = frontmatter.get("url", "")
        
        # 详细展示分数构成
        score_details = " | ".join(f"{k}: {v:.3f}" for k, v in item.component_scores.items())
        
        print(f"\n🏆 [推荐第 {idx + 1} 顺位] 综合契合度分数: {item.final_score:.4f}")
        print(f"  • 标题: {title}")
        print(f"  • 作者: {author}  |  发布时间: {published}")
        print(f"  • 链接: {url}")
        print(f"  • 分数构成: {score_details}")
        
        # 输出大模型提供的推荐理由和特征提取
        if rerank_details:
            rr_obj = next((rr for rr in rerank_details if rr.item_id == item.item_id), None)
            if rr_obj:
                print(f"  • AI 推荐理由: {rr_obj.reasoning}")
                if rr_obj.matched_topics:
                    print(f"  • 匹配主题: {', '.join(rr_obj.matched_topics)}")
                if rr_obj.concerns:
                    print(f"  • 潜在问题/顾虑: {', '.join(rr_obj.concerns)}")
        
        print(f"  • 内容摘要: {cand.content[:240]}...")
        print("-" * 80)

if __name__ == "__main__":
    main()
