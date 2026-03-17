"""
Personal RecSys - 真实数据端到端演示
使用知乎爬虫数据 + LM Studio 本地模型

数据:
  - 收藏夹 (166 items) -> 用户画像
  - 作者回答 (1871 items, 去重后) -> 候选池

模型 (LM Studio localhost:1234):
  - Embedding: bge-large-zh-v1.5
  - LLM: qwen3.5-9b (显式画像提取)
  - Reranker: qwen3-reranker-8b (Pointwise Rerank)
"""

import time
import json
from pathlib import Path

from src.engine import PersonalRecSys, CandidateItem
from src.evaluation.comparator import RecommendationComparator
from src.utils.embeddings import get_embedder
from src.utils.data_loader import load_zhihu_items, split_collection_candidates, compute_popularity
from src.utils.lm_studio_client import LMStudioLLMClient
from src.contracts.config import PipelineConfig


# === 数据路径 ===
DATA_DIR = Path("datacrawl/zhihu_crawler/data")
FAVORITES_PATH = DATA_DIR / "favorites_cjm926_all_20260305_150447.json"
AUTHOR_PATH = DATA_DIR / "author_L.M.Sherlock_answers_20260305_175050.json"
CACHE_DIR = "./data/real_data_cache"


def build_config(enable_reranker: bool) -> PipelineConfig:
    return PipelineConfig(
        embedding_dim=1024,
        embedder_type="lmstudio",
        embedding_model="text-embedding-bge-large-zh-v1.5",
        llm_model="qwen/qwen3.5-9b",
        reranker_model="qwen3-reranker-8b",
        max_profile_items=50,
        top_k=20,
        preset="balanced",
        batch_size=16,  # LM Studio 较小 batch
        cache_dir=CACHE_DIR,
        enable_reranker=enable_reranker,
        rerank_strategy="pointwise",
        rerank_top_n=50,
    )


def build_engine(enable_reranker: bool) -> PersonalRecSys:
    config = build_config(enable_reranker=enable_reranker)
    embedder = get_embedder(
        "lmstudio",
        dim=config.embedding_dim,
        base_url=config.lm_studio_base_url,
        model=config.embedding_model,
    )
    return PersonalRecSys(
        embedder=embedder,
        embedding_dim=config.embedding_dim,
        cache_dir=CACHE_DIR,
        config=config,
    )


def build_candidate_items(candidates_raw):
    candidate_items = []
    for item in candidates_raw:
        pop = compute_popularity(item)
        candidate_items.append(
            CandidateItem(
                item_id=item["id"],
                title=item["title"],
                content=item["content"][:500],  # 截断内容
                tags=[],
                metadata={
                    "popularity": pop,
                    "voteup_count": item.get("voteup_count", 0),
                    "comment_count": item.get("comment_count", 0),
                    "author_name": item.get("author_name", ""),
                    "url": item.get("url", ""),
                }
            )
        )
    return candidate_items


def ensure_profile(recsys: PersonalRecSys, collection):
    print("\n[3] 构建用户画像...")
    if recsys.vector_cloud and len(recsys.vector_cloud.vectors) > 0 and recsys.explicit_profile:
        print(f"  ✓ 从缓存加载画像: {len(recsys.vector_cloud.vectors)} vectors")
        recsys.collection_items = list(collection)
        return

    t0 = time.time()
    llm_client = LMStudioLLMClient(model="qwen/qwen3.5-9b")
    profile_summary = recsys.build_profile_from_collection(
        collection,
        llm_client=llm_client,
        max_items=50
    )
    elapsed = time.time() - t0
    print(f"  画像构建耗时: {elapsed:.1f}s")
    print(f"  画像摘要: {json.dumps(profile_summary, ensure_ascii=False, indent=2)}")


def run_recommendation(label: str, recsys: PersonalRecSys, candidates_raw):
    print(f"\n[{label}] 准备候选内容池 ({len(candidates_raw)} items)...")
    recsys.add_candidates(build_candidate_items(candidates_raw))

    print(f"\n[{label}] 为候选内容生成 Embedding...")
    t0 = time.time()
    recsys.embed_candidates(batch_size=recsys._config.batch_size)
    elapsed = time.time() - t0
    print(f"  Embedding 耗时: {elapsed:.1f}s")

    print(f"\n[{label}] 生成推荐...")
    t0 = time.time()
    results = recsys.recommend(top_k=20, preset="balanced")
    elapsed = time.time() - t0
    print(f"  推荐耗时: {elapsed:.3f}s")
    print(f"  阶段耗时: {json.dumps(results.timing, indent=2)}")
    return results


def main():
    print("=" * 70)
    print("Personal RecSys - 真实数据端到端演示")
    print("=" * 70)

    # === Step 0: 检查 LM Studio ===
    print("\n[0] 检查 LM Studio 连接...")
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:1234/v1/models", timeout=5)
        models = json.loads(resp.read().decode())
        model_ids = [m["id"] for m in models["data"]]
        print(f"  ✓ LM Studio 在线, 模型: {model_ids}")
    except Exception as e:
        print(f"  ✗ LM Studio 不可用: {e}")
        print("  请先启动 LM Studio 并加载模型")
        return

    # === Step 1: 加载数据 ===
    print("\n[1] 加载知乎数据...")
    t0 = time.time()
    favorites = load_zhihu_items(str(FAVORITES_PATH))
    author_data = load_zhihu_items(str(AUTHOR_PATH))
    collection, candidates_raw = split_collection_candidates(favorites, author_data)
    print(f"  加载耗时: {time.time() - t0:.2f}s")

    # === Step 2: 初始化引擎 ===
    print("\n[2] 初始化 baseline / rerank 两套引擎...")
    baseline_recsys = build_engine(enable_reranker=False)
    rerank_recsys = build_engine(enable_reranker=True)

    # === Step 3: 构建用户画像 ===
    ensure_profile(rerank_recsys, collection)
    if not (baseline_recsys.vector_cloud and baseline_recsys.explicit_profile):
        baseline_recsys.vector_cloud = rerank_recsys.vector_cloud
        baseline_recsys.explicit_profile = rerank_recsys.explicit_profile
    baseline_recsys.collection_items = list(collection)

    # === Step 4/5: 生成 baseline 与 rerank 推荐 ===
    baseline_results = run_recommendation("Baseline", baseline_recsys, candidates_raw)
    rerank_results = run_recommendation("Rerank", rerank_recsys, candidates_raw)

    print(f"\n{'='*70}")
    print(f"Rerank 推荐结果 (Top 20)")
    print(f"{'='*70}")
    print(f"总候选: {rerank_results.total_candidates}")
    print(f"过滤数: {rerank_results.filter_count}")
    print(f"阶段耗时: {json.dumps(rerank_results.timing, indent=2)}")

    print(f"\n{'─'*70}")
    for item in rerank_results.ranked_items[:20]:
        cand = rerank_recsys.candidates.get(item.item_id)
        title = cand.title if cand else "Unknown"
        url = cand.metadata.get("url", "") if cand else ""
        voteup = cand.metadata.get("voteup_count", 0) if cand else 0

        print(f"\n[排名 {item.rank:2d}] 总分: {item.final_score:.4f}")
        print(f"  标题: {title[:60]}")
        print(f"  各维度: i2i={item.component_scores.get('i2i', 0):.3f} "
              f"tag={item.component_scores.get('tag', 0):.3f} "
              f"rerank={item.component_scores.get('rerank', 0):.3f} "
              f"pop={item.component_scores.get('popularity', 0):.3f}")
        print(f"  赞同: {voteup}  URL: {url[:80]}")

    # === Step 6: 对比其他预设 ===
    print(f"\n\n{'='*70}")
    print("Baseline vs Rerank (Top 5)")
    print(f"{'='*70}")
    for rank in range(5):
        baseline_item = baseline_results.ranked_items[rank]
        rerank_item = rerank_results.ranked_items[rank]
        baseline_title = baseline_recsys.candidates[baseline_item.item_id].title[:50]
        rerank_title = rerank_recsys.candidates[rerank_item.item_id].title[:50]
        print(f"\n[Rank {rank + 1}]")
        print(f"  Baseline: {baseline_item.final_score:.3f} | {baseline_title}")
        print(f"  Rerank:   {rerank_item.final_score:.3f} | {rerank_title}")

    # === Step 7: 导出评估对比 ===
    comparator = RecommendationComparator(CACHE_DIR)
    blind_comparison = comparator.build_blind_comparison(
        baseline_results.ranked_items,
        rerank_results.ranked_items,
        rerank_recsys.candidates,
        top_k=10,
    )
    blind_path = comparator.save_blind_comparison(blind_comparison)
    report = comparator.generate_report()
    report_path = comparator.save_report(report)
    print(f"\n盲测文件已保存到: {blind_path}")
    print(f"评估报告已保存到: {report_path}")

    # === Step 8: 保存引擎状态 ===
    save_path = CACHE_DIR
    rerank_recsys.save(save_path)
    print(f"\n\n✓ 引擎状态已保存到: {save_path}")

    print(f"\n{'='*70}")
    print("演示完成！")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
