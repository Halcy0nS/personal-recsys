"""
基础测试用例
"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from src.profiling.implicit_profile import VectorCloud
from src.profiling.explicit_profile import UserExplicitProfile, ProfileExtractor
from src.retrieval.i2i_matcher import I2IMatcher
from src.retrieval.tag_matcher import TagMatcher
from src.ranking.scorer import WeightedScorer, ScoreComponent, ConfigurableScorer
from src.utils.embeddings import MockEmbedder
from src.contracts.config import PipelineConfig
from src.engine import PersonalRecSys, CandidateItem
from src.evaluation.comparator import RecommendationComparator
from src.evaluation.glicko2 import GlickoRating, batch_update
from src.evaluation.llm_pairwise import LLMPairwiseExperiment
from src.evaluation.order_instability_attribution import OrderInstabilityAttributionExperiment
from src.evaluation.pairwise import PairwiseDecision, PairwiseEvaluationSession
from src.evaluation.reranker_stability import RerankerStabilityExperiment
from src.services.reranker import RerankerResult


class CountingEmbedder(MockEmbedder):
    """用于验证缓存命中的 embedder。"""

    def __init__(self, dim: int = 128):
        super().__init__(dim=dim)
        self.embed_calls = 0

    def embed_batch(self, texts, batch_size: int = 32):
        self.embed_calls += len(texts)
        return super().embed_batch(texts, batch_size=batch_size)


class FakeChatResponse:
    """模拟 LM Studio chat 返回结构。"""

    class _Message:
        def __init__(self, content: str):
            self.content = content

    class _Choice:
        def __init__(self, content: str):
            self.message = FakeChatResponse._Message(content)

    def __init__(self, content: str):
        self.choices = [FakeChatResponse._Choice(content)]


class FakeRerankClient:
    """根据标题返回确定性 rerank 分数。"""

    def __init__(self, title_scores):
        self.title_scores = title_scores
        self.calls = []

    def chat(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)

        matched_title = None
        for title in self.title_scores.keys():
            if f"《{title}》" in prompt:
                matched_title = title
                break

        score = self.title_scores.get(matched_title, 5)
        return FakeChatResponse(
            f'{{"relevance_score": {score}, "confidence": 0.9, "reasoning": "mock", "matched_topics": ["机器学习"], "concerns": []}}'
        )


class FakePairwiseClient:
    """为 pairwise 实验返回可控偏好。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)

        if "《文章A》" in prompt and "《文章B》" in prompt:
            return FakeChatResponse('{"preferred": "A", "confidence": 0.8, "reasoning": "prefer A"}')
        if "《文章B》" in prompt and "《文章A》" in prompt:
            return FakeChatResponse('{"preferred": "A", "confidence": 0.8, "reasoning": "prefer first"}')

        return FakeChatResponse('{"preferred": "tie", "confidence": 0.5, "reasoning": "tie"}')


class FakeMonteCarloReranker:
    """为稳定性实验返回带波动的重排结果。"""

    def __init__(self):
        self.rerank_top_n = 3
        self.call_count = 0

    def rerank(self, candidates, profile_topics, profile_styles, profile_negatives, exemplar_titles, coarse_ranked_ids=None):
        self.call_count += 1
        if self.call_count == 1:
            scores = {"a": 9.0, "b": 8.0, "c": 6.0}
        elif self.call_count == 2:
            scores = {"a": 7.0, "b": 9.5, "c": 6.0}
        else:
            scores = {"a": 8.8, "b": 8.2, "c": 6.0}

        results = []
        ids = coarse_ranked_ids or list(scores.keys())
        for item_id in ids:
            results.append(
                RerankerResult(
                    item_id=item_id,
                    relevance_score=scores[item_id],
                    confidence=0.9,
                    reasoning="mock",
                    matched_topics=[],
                    concerns=[],
                )
            )
        results.sort(key=lambda item: item.relevance_score, reverse=True)
        return results


def test_vector_cloud():
    """测试向量云"""
    print("\n[Test] VectorCloud")

    cloud = VectorCloud(embedding_dim=128)

    # 添加测试向量
    for i in range(5):
        vec = np.random.randn(128)
        cloud.add_vector(vec, metadata={"id": i, "title": f"item_{i}"})

    assert len(cloud.vectors) == 5

    # 测试最近邻搜索
    query = np.random.randn(128)
    score, indices = cloud.find_closest_in_cloud(query, top_k=3)

    assert len(indices) == 3
    assert -1 <= score <= 1

    print(f"  ✓ VectorCloud: {len(cloud.vectors)} vectors, similarity score: {score:.3f}")


def test_i2i_matcher():
    """测试I2I匹配"""
    print("\n[Test] I2IMatcher")

    # 创建用户向量云
    cloud = VectorCloud(embedding_dim=128)
    for i in range(10):
        vec = np.random.randn(128)
        cloud.add_vector(vec, metadata={"id": f"collected_{i}"})

    # 测试匹配
    matcher = I2IMatcher(top_k=3, metric="cosine")
    candidate_vec = np.random.randn(128)

    result = matcher.match(candidate_vec, cloud)

    assert result.i2i_score >= 0
    assert len(result.matched_source_indices) <= 3

    print(f"  ✓ I2I Score: {result.i2i_score:.3f}, matched {len(result.matched_source_indices)} items")


def test_tag_matcher():
    """测试标签匹配"""
    print("\n[Test] TagMatcher")

    # 创建用户画像
    profile = UserExplicitProfile(
        core_topics=["机器学习", "深度学习", "Python"],
        writing_style=["深度长文"],
        content_depth=["技术细节"],
        negative_tags=["软广", "标题党"],
        authors=[],
        custom_tags={}
    )

    # 测试匹配
    matcher = TagMatcher(
        positive_weight=1.0,
        negative_weight=-2.0,
        hard_filter_negative=True
    )

    # 应该被过滤的内容
    result_filtered = matcher.match(
        item_id="bad_001",
        item_tags=["标题党", "震惊"],
        item_title="震惊！这个Python技巧让你秒变大神",
        user_profile=profile
    )

    # 应该高分的内容
    result_good = matcher.match(
        item_id="good_001",
        item_tags=["机器学习", "深度学习", "技术细节"],
        item_title="Transformer架构详解",
        user_profile=profile
    )

    assert result_filtered.is_filtered == True
    assert result_good.tag_score > result_filtered.tag_score

    print(f"  ✓ Filtered item (bad): score={result_filtered.tag_score}, filtered={result_filtered.is_filtered}")
    print(f"  ✓ Good item: score={result_good.tag_score:.3f}, matched: {result_good.matched_positive}")


def test_weighted_scorer():
    """测试加权计分器"""
    print("\n[Test] WeightedScorer")

    # 模拟分数数据
    item_scores = {
        "item_001": {
            ScoreComponent.I2I: 0.8,
            ScoreComponent.TAG: 0.7,
            ScoreComponent.POPULARITY: 0.9
        },
        "item_002": {
            ScoreComponent.I2I: 0.6,
            ScoreComponent.TAG: 0.9,
            ScoreComponent.POPULARITY: 0.5
        },
        "item_003": {
            ScoreComponent.I2I: 0.9,
            ScoreComponent.TAG: 0.4,
            ScoreComponent.POPULARITY: 0.8
        }
    }

    # 测试平衡模式
    weights = {
        ScoreComponent.I2I: 0.5,
        ScoreComponent.TAG: 0.3,
        ScoreComponent.POPULARITY: 0.2
    }

    scorer = WeightedScorer(weights=weights, normalize=True)
    ranked = scorer.calculate(item_scores)

    assert len(ranked) == 3
    assert ranked[0].rank == 1

    print(f"  ✓ Ranked {len(ranked)} items")
    for item in ranked:
        print(f"    Rank {item.rank}: {item.item_id} (score: {item.final_score:.3f})")


def test_full_pipeline():
    """测试完整流程"""
    print("\n[Test] Full Pipeline")

    # 创建引擎
    recsys = PersonalRecSys(
        embedder=MockEmbedder(dim=128),
        embedding_dim=128
    )

    # 1. 构建画像
    collection_items = [
        {"title": "机器学习基础", "content": "介绍ML基本概念和算法...", "url": "#1"},
        {"title": "Python编程技巧", "content": "提高Python代码质量的方法...", "url": "#2"},
        {"title": "深度学习入门", "content": "神经网络基础...", "url": "#3"},
    ]

    recsys.build_profile_from_collection(collection_items, llm_client=None)

    # 手动设置显式画像
    recsys.explicit_profile = UserExplicitProfile(
        core_topics=["机器学习", "Python", "深度学习"],
        writing_style=["入门教程"],
        content_depth=["基础概念"],
        negative_tags=[],
        authors=[],
        custom_tags={}
    )

    # 2. 添加候选
    candidates = [
        CandidateItem(
            item_id="cand_1",
            title="PyTorch入门指南",
            content="学习PyTorch框架的基础用法...",
            tags=["深度学习", "Python"],
            metadata={"likes": 100}
        ),
        CandidateItem(
            item_id="cand_2",
            title="Scikit-learn实战",
            content="使用sklearn解决实际问题...",
            tags=["机器学习", "Python"],
            metadata={"likes": 150}
        ),
    ]

    recsys.add_candidates(candidates)
    recsys.embed_candidates()

    # 3. 推荐
    results = recsys.recommend(top_k=5, preset="balanced")

    assert len(results.ranked_items) > 0
    assert results.ranked_items[0].rank == 1

    print(f"  ✓ Generated {len(results.ranked_items)} recommendations")
    print(f"  ✓ Total candidates: {results.total_candidates}")
    for item in results.ranked_items[:3]:
        print(f"    Rank {item.rank}: {item.item_id} (score: {item.final_score:.3f})")


def test_reranker_integration():
    """测试 reranker 接入后会影响最终排序。"""
    print("\n[Test] Reranker Integration")

    config = PipelineConfig(
        embedding_dim=4,
        enable_reranker=True,
        rerank_top_n=2,
    )
    recsys = PersonalRecSys(
        embedder=MockEmbedder(dim=4),
        embedding_dim=4,
        config=config,
    )

    recsys.build_profile_from_collection([
        {"title": "机器学习基础", "content": "介绍机器学习"},
        {"title": "深度学习实践", "content": "介绍神经网络"},
    ], llm_client=None)

    recsys.vector_cloud = VectorCloud(embedding_dim=4)
    recsys.vector_cloud.add_vector(np.array([1.0, 0.0, 0.0, 0.0]))
    recsys.vector_cloud.add_vector(np.array([1.0, 0.0, 0.0, 0.0]))
    recsys.explicit_profile = UserExplicitProfile(
        core_topics=["机器学习"],
        writing_style=["深度长文"],
        content_depth=["技术细节"],
        negative_tags=[],
        authors=[],
        custom_tags={}
    )

    candidates = [
        CandidateItem(
            item_id="cand_a",
            title="Candidate A",
            content="更像基线最优项",
            embedding=np.array([1.0, 0.0, 0.0, 0.0]),
            tags=["机器学习"],
        ),
        CandidateItem(
            item_id="cand_b",
            title="Candidate B",
            content="rerank 应提升这一项",
            embedding=np.array([0.8, 0.2, 0.0, 0.0]),
            tags=["机器学习"],
        ),
        CandidateItem(
            item_id="cand_c",
            title="Candidate C",
            content="不相关项",
            embedding=np.array([0.0, 1.0, 0.0, 0.0]),
            tags=["其他"],
        ),
    ]
    recsys.add_candidates(candidates)

    fake_client = FakeRerankClient({
        "Candidate A": 1,
        "Candidate B": 10,
    })
    recsys._orchestrator._reranker.llm_client = fake_client

    results = recsys.recommend(top_k=2, preset="balanced")

    assert len(fake_client.calls) == 2
    assert "rerank" in results.timing
    assert results.ranked_items[0].item_id == "cand_b"
    assert "rerank" in results.ranked_items[0].component_scores

    print(f"  ✓ Rerank called for top-{len(fake_client.calls)} candidates")
    print(f"  ✓ Top result after rerank: {results.ranked_items[0].item_id}")


def test_reranker_fallback_without_explicit_profile():
    """测试无显式画像时即使启用 reranker 也回退到基础链路。"""
    print("\n[Test] Reranker Fallback Without Explicit Profile")

    config = PipelineConfig(
        embedding_dim=4,
        enable_reranker=True,
        rerank_top_n=2,
    )
    recsys = PersonalRecSys(
        embedder=MockEmbedder(dim=4),
        embedding_dim=4,
        config=config,
    )

    recsys.build_profile_from_collection([
        {"title": "机器学习基础", "content": "介绍机器学习"}
    ], llm_client=None)

    recsys.vector_cloud = VectorCloud(embedding_dim=4)
    recsys.vector_cloud.add_vector(np.array([1.0, 0.0, 0.0, 0.0]))

    recsys.add_candidates([
        CandidateItem(
            item_id="cand_1",
            title="Candidate 1",
            content="related",
            embedding=np.array([1.0, 0.0, 0.0, 0.0]),
            tags=["机器学习"],
        )
    ])

    results = recsys.recommend(top_k=1)

    assert "rerank" not in results.timing
    assert "rerank" not in results.ranked_items[0].component_scores
    print("  ✓ No explicit profile -> rerank stage skipped")


def test_candidate_embedding_cache():
    """测试候选 embedding 磁盘缓存。"""
    print("\n[Test] Candidate Embedding Cache")

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = os.path.join(tmpdir, "candidate_embeddings.npz")

        embedder_first = CountingEmbedder(dim=8)
        recsys_first = PersonalRecSys(
            embedder=embedder_first,
            embedding_dim=8,
            cache_dir=tmpdir,
        )
        recsys_first.add_candidates([
            CandidateItem(item_id="cand_1", title="标题1", content="正文1")
        ])
        recsys_first.embed_candidates()

        assert embedder_first.embed_calls == 1
        assert os.path.exists(cache_file)

        embedder_second = CountingEmbedder(dim=8)
        recsys_second = PersonalRecSys(
            embedder=embedder_second,
            embedding_dim=8,
            cache_dir=tmpdir,
        )
        recsys_second.add_candidates([
            CandidateItem(item_id="cand_1", title="标题1", content="正文1")
        ])
        recsys_second.embed_candidates()

        assert embedder_second.embed_calls == 0
        assert recsys_second.candidates["cand_1"].embedding is not None

        embedder_third = CountingEmbedder(dim=8)
        recsys_third = PersonalRecSys(
            embedder=embedder_third,
            embedding_dim=8,
            cache_dir=tmpdir,
        )
        recsys_third.add_candidates([
            CandidateItem(item_id="cand_1", title="标题1", content="正文已变化")
        ])
        recsys_third.embed_candidates()

        assert embedder_third.embed_calls == 1
        print("  ✓ Cache hit skips re-embedding")
        print("  ✓ Content change invalidates cache")


def test_recommendation_comparator():
    """测试评估对比器会生成盲测文件和报告。"""
    print("\n[Test] Recommendation Comparator")

    with tempfile.TemporaryDirectory() as tmpdir:
        comparator = RecommendationComparator(tmpdir)

        candidates = {
            "cand_1": CandidateItem(item_id="cand_1", title="文章1", content="...", metadata={"url": "https://a"}),
            "cand_2": CandidateItem(item_id="cand_2", title="文章2", content="...", metadata={"url": "https://b"}),
        }

        baseline_results = [
            type("Result", (), {"item_id": "cand_1", "final_score": 0.8})(),
        ]
        rerank_results = [
            type("Result", (), {"item_id": "cand_2", "final_score": 0.9})(),
        ]

        blind = comparator.build_blind_comparison(
            baseline_results=baseline_results,
            rerank_results=rerank_results,
            candidates=candidates,
            top_k=5,
        )
        blind_path = comparator.save_blind_comparison(blind)
        report_path = comparator.save_report(comparator.generate_report())

        assert os.path.exists(blind_path)
        assert os.path.exists(report_path)
        assert len(blind["blind_items"]) == 2

        print(f"  ✓ Blind comparison saved to {blind_path}")
        print(f"  ✓ Report saved to {report_path}")


def test_glicko2_update():
    """测试 Glicko2 胜者分数会上升。"""
    print("\n[Test] Glicko2 Update")

    ratings = {
        "A": GlickoRating(),
        "B": GlickoRating(),
    }
    updated = batch_update(ratings, [("A", "B", 1.0)])

    assert updated["A"].rating > ratings["A"].rating
    assert updated["B"].rating < ratings["B"].rating
    print(f"  ✓ Winner rating increased to {updated['A'].rating:.2f}")


def test_pairwise_evaluation_session():
    """测试 pairwise 评测会生成报告和评分文件。"""
    print("\n[Test] Pairwise Evaluation Session")

    with tempfile.TemporaryDirectory() as tmpdir:
        comparator = RecommendationComparator(tmpdir)
        candidates = {
            "cand_1": CandidateItem(item_id="cand_1", title="文章1", content="...", metadata={"url": "https://a"}),
            "cand_2": CandidateItem(item_id="cand_2", title="文章2", content="...", metadata={"url": "https://b"}),
            "cand_3": CandidateItem(item_id="cand_3", title="文章3", content="...", metadata={"url": "https://c"}),
            "cand_4": CandidateItem(item_id="cand_4", title="文章4", content="...", metadata={"url": "https://d"}),
        }
        baseline_results = [
            type("Result", (), {"item_id": "cand_1", "final_score": 0.8})(),
            type("Result", (), {"item_id": "cand_2", "final_score": 0.7})(),
        ]
        rerank_results = [
            type("Result", (), {"item_id": "cand_3", "final_score": 0.9})(),
            type("Result", (), {"item_id": "cand_4", "final_score": 0.85})(),
        ]
        blind = comparator.build_blind_comparison(
            baseline_results=baseline_results,
            rerank_results=rerank_results,
            candidates=candidates,
            top_k=2,
        )
        comparator.save_blind_comparison(blind)

        session = PairwiseEvaluationSession(tmpdir)
        matchups = session.load_matchups()
        assert len(matchups) == 4

        session.save_decision(PairwiseDecision(
            comparison_id=matchups[0].comparison_id,
            pair_id=matchups[0].pair_id,
            blind_id_a=matchups[0].blind_id_a,
            blind_id_b=matchups[0].blind_id_b,
            winner="A",
            winning_system="baseline",
            note="baseline better",
            created_at="2026-03-11T10:00:00",
        ))
        session.save_decision(PairwiseDecision(
            comparison_id=matchups[1].comparison_id,
            pair_id=matchups[1].pair_id,
            blind_id_a=matchups[1].blind_id_a,
            blind_id_b=matchups[1].blind_id_b,
            winner="B",
            winning_system="rerank",
            note="rerank better",
            created_at="2026-03-11T10:00:01",
        ))

        report = session.build_report()
        ratings = session.build_glicko_ratings()
        ratings_again = session.build_glicko_ratings()

        assert report["total_pairs_decided"] == 2
        assert report["baseline_wins"] == 1
        assert report["rerank_wins"] == 1
        assert len(ratings) == 3
        assert ratings == ratings_again
        assert os.path.exists(session.glicko_path)
        print("  ✓ Pairwise report and Glicko2 ratings generated")


def test_llm_pairwise_order_experiment():
    """测试 A/B 与 B/A 顺序实验会输出顺序不一致。"""
    print("\n[Test] LLM Pairwise Order Experiment")

    experiment = LLMPairwiseExperiment(llm_client=FakePairwiseClient())
    user_profile = type("Profile", (), {
        "core_topics": ["教育"],
        "writing_style": ["深度分析"],
        "negative_tags": [],
        "exemplars": [],
    })()
    matchup = type("Matchup", (), {
        "pair_id": "pair_1",
        "item_id_a": "a",
        "item_id_b": "b",
        "title_a": "文章A",
        "title_b": "文章B",
        "summary_a": "摘要A",
        "summary_b": "摘要B",
        "system_a": "baseline",
        "system_b": "rerank",
    })()

    result = experiment.evaluate_matchup(matchup, user_profile)
    summary = experiment.summarize_results([result])

    assert result["forward"]["system_winner"] == "baseline"
    assert result["reverse"]["system_winner"] == "rerank"
    assert result["resolved_winner"] == "unstable"
    assert summary["order_inconsistent_pairs"] == 1
    assert summary["order_flip_rate"] == 1.0
    assert summary["forward_baseline_wins"] == 1
    assert summary["reverse_rerank_wins"] == 1
    assert summary["resolved_unstable"] == 1
    print("  ✓ Order swap inconsistency detected")


def test_reranker_stability_experiment():
    """测试 Monte Carlo 重排稳定性统计。"""
    print("\n[Test] Reranker Stability Experiment")

    experiment = RerankerStabilityExperiment(FakeMonteCarloReranker())
    candidates = {
        "a": CandidateItem(item_id="a", title="文章A", content="内容A"),
        "b": CandidateItem(item_id="b", title="文章B", content="内容B"),
        "c": CandidateItem(item_id="c", title="文章C", content="内容C"),
    }

    result = experiment.run(
        candidates=candidates,
        profile_topics=["学习"],
        profile_styles=["深度分析"],
        profile_negatives=[],
        exemplar_titles=["示例1"],
        coarse_ranked_ids=["a", "b", "c"],
        trials=3,
        analysis_top_k=2,
        verbose=False,
    )

    summary = result["summary"]
    assert result["trial_count"] == 3
    assert summary["top1_unique_count"] == 2
    assert summary["top1_mode_title"] in {"文章A", "文章B"}
    assert summary["mean_rank_std"] > 0
    assert summary["mean_pairwise_order_stability"] < 1.0
    print("  ✓ Monte Carlo reranker stability metrics generated")


def test_order_instability_attribution_experiment():
    """测试 judge bias 与 reranker variance 的归因汇总。"""
    print("\n[Test] Order Instability Attribution Experiment")

    reranker_experiment = RerankerStabilityExperiment(FakeMonteCarloReranker())
    judge_experiment = LLMPairwiseExperiment(llm_client=FakePairwiseClient())
    experiment = OrderInstabilityAttributionExperiment(
        reranker_experiment=reranker_experiment,
        judge_experiment=judge_experiment,
    )

    candidates = {
        "a": CandidateItem(item_id="a", title="文章A", content="摘要A"),
        "b": CandidateItem(item_id="b", title="文章B", content="摘要B"),
        "c": CandidateItem(item_id="c", title="文章C", content="摘要C"),
    }
    user_profile = type("Profile", (), {
        "core_topics": ["学习"],
        "writing_style": ["深度分析"],
        "negative_tags": [],
        "exemplars": [],
    })()

    result = experiment.run(
        candidates=candidates,
        user_profile=user_profile,
        profile_topics=["学习"],
        profile_styles=["深度分析"],
        profile_negatives=[],
        exemplar_titles=["示例1"],
        coarse_ranked_ids=["a", "b", "c"],
        reranker_trials=3,
        rerank_analysis_top_k=2,
        judge_pair_count=1,
        verbose=False,
    )

    assert result["fixed_pair_judge_summary"]["order_flip_rate"] == 1.0
    assert result["reranker_summary"]["mean_pairwise_order_stability"] < 1.0
    assert result["attribution_estimate"]["dominant_source"] in {
        "judge_order_bias",
        "reranker_variance",
        "balanced_or_low_signal",
    }
    print("  ✓ Attribution summary generated")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Personal RecSys - 测试套件")
    print("=" * 60)

    try:
        test_vector_cloud()
        test_i2i_matcher()
        test_tag_matcher()
        test_weighted_scorer()
        test_full_pipeline()
        test_reranker_integration()
        test_reranker_fallback_without_explicit_profile()
        test_candidate_embedding_cache()
        test_recommendation_comparator()
        test_glicko2_update()
        test_pairwise_evaluation_session()
        test_llm_pairwise_order_experiment()
        test_reranker_stability_experiment()
        test_order_instability_attribution_experiment()

        print("\n" + "=" * 60)
        print("所有测试通过！")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    run_all_tests()
