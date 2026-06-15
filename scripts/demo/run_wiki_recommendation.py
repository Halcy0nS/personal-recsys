"""
基于本地 SiYuan Wiki 的推荐系统演示脚本。
将提取出的结构化 Wiki 作为候选池，用户输入自然语言意图，引擎推荐最相关的笔记页面。
"""

import sys
import time
import os
import json
import argparse

# Add the project root to the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.engine import PersonalRecSys
from src.contracts.config import PipelineConfig
from src.utils.embeddings import get_embedder
from src.utils.wiki_loader import load_wiki_candidates

CACHE_DIR = "./data/wiki_recsys_cache"

def build_wiki_engine() -> PersonalRecSys:
    """初始化推荐引擎"""
    import os

    # 1. 优先检测环境变量中的 Google Gemini API Key
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        print("  ✓ 检测到 GEMINI_API_KEY，使用 Google Gemini 进行文本向量化 (768维)。")
        config = PipelineConfig(
            embedding_dim=768,
            embedder_type="gemini",
            top_k=5,
            preset="precision",
            batch_size=16,
            cache_dir=CACHE_DIR,
            enable_reranker=False
        )
        embedder = get_embedder("gemini", dim=768, api_key=gemini_key)
        return PersonalRecSys(
            embedder=embedder,
            embedding_dim=768,
            cache_dir=CACHE_DIR,
            config=config,
        )

    # 2. 回退到原有逻辑 (LM Studio / Mock)
    config = PipelineConfig(
        embedding_dim=1024,
        embedder_type="lmstudio",
        embedding_model="text-embedding-bge-large-zh-v1.5",
        lm_studio_base_url="http://localhost:1234/v1",
        top_k=5,
        preset="precision", # 精确模式 - 强调查查找最相似的内容
        batch_size=16,
        cache_dir=CACHE_DIR,
        enable_reranker=False # 演示暂不开启 reranker
    )
    
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:1234/v1/models", timeout=2)
        print("  ✓ LM Studio 在线，将使用 BGE 模型进行文本向量化。")
        embedder = get_embedder(
            "lmstudio",
            dim=config.embedding_dim,
            base_url=config.lm_studio_base_url,
            model=config.embedding_model,
        )
    except Exception:
        print("  ! LM Studio 未启动或未加载模型。自动降级为 Mock Embedder 进行演示！")
        embedder = get_embedder("mock", dim=1024)

    return PersonalRecSys(
        embedder=embedder,
        embedding_dim=config.embedding_dim,
        cache_dir=CACHE_DIR,
        config=config,
    )

def main():
    parser = argparse.ArgumentParser(description="运行 Wiki 意图推荐引擎")
    parser.add_argument("--wiki_dir", type=str, default="/Users/salmon/research/wiki", help="包含 Markdown 文件的目录路径")
    args = parser.parse_args()

    print("=" * 70)
    print("Personal RecSys - 智能检索与推荐演示")
    print(f"目标数据目录: {args.wiki_dir}")
    print("=" * 70)

    # 1. 加载数据
    print(f"\n[1] 加载本地笔记 ({args.wiki_dir})...")
    candidates = load_wiki_candidates(args.wiki_dir)
    if not candidates:
        print("未找到任何 Wiki 文件，请检查路径。")
        return

    # 2. 初始化引擎并送入数据
    print("\n[2] 初始化推荐引擎...")
    recsys = build_wiki_engine()
    
    print(f"\n[3] 正在对 {len(candidates)} 篇 Wiki 笔记进行向量化计算...")
    t0 = time.time()
    recsys.add_candidates(candidates)
    recsys.embed_candidates(batch_size=16)
    print(f"  ✓ 向量化完成，耗时: {time.time() - t0:.2f}s")

    # 3. 交互式查询
    print("\n" + "=" * 70)
    print("系统就绪！请输入您的研究意图，系统将为您推荐最契合的知识切片。")
    print("(输入 'q' 或 'quit' 退出)")
    
    while True:
        try:
            query = input("\n🔍 请输入意图: ").strip()
            if not query:
                continue
            if query.lower() in ['q', 'quit', 'exit']:
                break
                
            # 将用户的 query 伪装为一篇“收藏文章”，强行注入隐式画像 (VectorCloud)
            # 因为引擎是基于用户收藏构建的画像来做召回的
            print("  正在思考并匹配图谱...")
            mock_collection = [{"title": "User Current Intent", "content": query}]
            recsys.build_profile_from_collection(mock_collection)
            
            # 运行推荐
            t0 = time.time()
            results = recsys.recommend(top_k=5, preset="precision")
            
            print(f"\n🎯 匹配结果 (耗时: {time.time() - t0:.3f}s):")
            print("-" * 50)
            
            if not results.ranked_items:
                print("抱歉，未能找到相关的推荐内容。")
                continue
                
            for item in results.ranked_items:
                cand = recsys.candidates.get(item.item_id)
                path = cand.metadata.get("path", "") if cand else ""
                tags = cand.tags if cand else []
                
                print(f"[匹配度: {item.final_score:.3f}] {cand.title}")
                print(f"  文件: {path}")
                if tags:
                    print(f"  标签: {', '.join(tags)}")
                
                # 打印出分数的详细构成
                scores_str = " | ".join(f"{k}: {v:.2f}" for k, v in item.component_scores.items())
                print(f"  分数构成: {scores_str}")
                print("-" * 30)
                
        except EOFError:
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n! 发生错误: {e}")

    print("\n演示结束，再见！")

if __name__ == "__main__":
    main()
