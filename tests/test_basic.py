"""
基础测试用例
"""

import sys
import os
import tempfile
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from elote.competitors.glicko2 import Glicko2Competitor
from src.profiling.implicit_profile import VectorCloud
from src.profiling.explicit_profile import UserExplicitProfile, ProfileExtractor
from src.retrieval.i2i_matcher import I2IMatcher
from src.retrieval.tag_matcher import TagMatcher
from src.ranking.scorer import WeightedScorer, ScoreComponent, ConfigurableScorer
from src.utils.embeddings import MockEmbedder
from src.utils.lm_studio_client import LMStudioLLMClient
from src.contracts.config import PipelineConfig
from src.engine import PersonalRecSys, CandidateItem
from experiments.comparator import RecommendationComparator
from experiments.llm_pairwise import LLMPairwiseExperiment
from experiments.order_instability_attribution import OrderInstabilityAttributionExperiment
from experiments.pairwise import PairwiseDecision, PairwiseEvaluationSession
from experiments.rag_rerank import (
    CandidateAwareRAGReranker,
    ChunkIndexStore,
    FullTextDocument,
    chunk_document,
)
from experiments.reranker_stability import RerankerStabilityExperiment
from experiments.simulator_glicko import (
    FixedPairCalibrationConfig,
    FixedPairSpec,
    SimulatorExperimentConfig,
    SimulatorGlickoExperiment,
    build_fixed_pair_benchmark_comparison,
    cleanup_json_text,
    normalize_candidate_choice,
)
from experiments.simulator_glicko_runner import _make_client_pool
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


class FakeRAGClient:
    """模拟 RAG JSON 打分输出。"""

    def __init__(self, fail_on: str = ""):
        self.fail_on = fail_on
        self.calls = []

    def chat(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        if self.fail_on and self.fail_on in prompt:
            return FakeChatResponse("not-json-response")
        return FakeChatResponse(
            '{"relevance_score": 8, "confidence": 0.9, "reasoning": "evidence matched", '
            '"supporting_favorites": ["收藏A"], "concerns": []}'
        )


class FakeAdaptiveExtractorClient:
    """为自适应压缩实验返回稳定 JSON。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        title_match = re.search(r"文章标题: 《(.+?)》", prompt)
        title = title_match.group(1) if title_match else "未知标题"
        payload = {
            "genre": "analysis",
            "info_density": "high" if "深度" in prompt else "medium",
            "compression_strategy": "adaptive_structured",
            "core_claim": f"{title} 的核心主张",
            "key_points": [f"{title} 要点1", f"{title} 要点2"],
            "style_signals": ["理性分析", "长文"],
            "noise_level": 0.2,
        }
        return FakeChatResponse(f"<think>skip</think>\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```")


class FakeSimulatorJudgeClient:
    """为 simulator pairwise 实验返回确定性偏好。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        titles = re.findall(r"标题: 《(.+?)》", prompt)
        if len(titles) >= 2:
            left = titles[0]
            right = titles[1]
            preferred = "A" if left < right else "B"
        else:
            preferred = "tie"
        return FakeChatResponse(
            json.dumps(
                {
                    "preferred_candidate_id": "cand_left_placeholder",
                    "preferred": preferred,
                    "confidence": 0.82,
                    "reason": "stable lexical preference",
                },
                ensure_ascii=False,
            )
        )


class FixedPairPromptJudgeClient:
    """根据 prompt 版本模拟首位偏置与修复后的稳定输出。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)

        candidate_ids = re.findall(r"candidate_id=(cand_[A-Za-z0-9_]+)", prompt)
        if "候选顺序已随机化" in prompt and len(candidate_ids) >= 2:
            chosen = sorted(candidate_ids)[0]
            payload = {
                "preferred_candidate_id": chosen,
                "confidence": 0.75,
                "reason": "stable candidate id choice",
            }
            return FakeChatResponse(json.dumps(payload, ensure_ascii=False))

        payload = {
            "preferred": "A",
            "confidence": 0.8,
            "reason": "prefer first",
        }
        return FakeChatResponse(json.dumps(payload, ensure_ascii=False))


class ProbeFailOnceJudgeClient(FixedPairPromptJudgeClient):
    """第一次调用失败，后续恢复，用于测试 preflight 降级。"""

    def __init__(self):
        super().__init__()
        self.failed_once = False

    def chat(self, messages):
        if not self.failed_once:
            self.failed_once = True
            raise urllib.error.HTTPError(
                url="https://api.siliconflow.cn/v1/chat/completions",
                code=429,
                msg="rate limited",
                hdrs=None,
                fp=None,
            )
        return super().chat(messages)


class FixedPairRetryJudgeClient(FixedPairPromptJudgeClient):
    """对指定标题连续失败若干次，用于测试 resume。"""

    def __init__(self, fail_title: str, fail_times: int):
        super().__init__()
        self.fail_title = fail_title
        self.fail_times = fail_times
        self.fail_count = 0

    def chat(self, messages):
        prompt = messages[-1]["content"]
        if self.fail_count < self.fail_times and self.fail_title in prompt:
            self.fail_count += 1
            raise urllib.error.URLError("temporary network failure")
        return super().chat(messages)


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

    start = datetime(2026, 1, 1, 0, 0, 0)
    winner = Glicko2Competitor(initial_time=start)
    loser = Glicko2Competitor(initial_time=start)
    winner.beat(loser, match_time=start + timedelta(seconds=1))

    assert winner.rating > 1500
    assert loser.rating < 1500
    print(f"  ✓ Winner rating increased to {winner.rating:.2f}")


def test_glicko2_online_updates_remain_bounded():
    """测试逐局增量更新不会出现数值爆炸。"""
    print("\n[Test] Glicko2 Online Update Stability")

    ratings = {}
    sequence = [
        ("A", "B", 1.0),
        ("A", "C", 1.0),
        ("B", "C", 0.5),
        ("C", "D", 1.0),
        ("D", "A", 0.0),
        ("B", "D", 1.0),
        ("A", "B", 0.5),
        ("C", "A", 0.0),
    ]

    start = datetime(2026, 1, 1, 0, 0, 0)
    for index, (player_a, player_b, score_for_a) in enumerate(sequence * 10, 1):
        competitor_a = ratings.setdefault(player_a, Glicko2Competitor(initial_time=start))
        competitor_b = ratings.setdefault(player_b, Glicko2Competitor(initial_time=start))
        match_time = start + timedelta(seconds=index)
        if score_for_a >= 1.0:
            competitor_a.beat(competitor_b, match_time=match_time)
        elif score_for_a <= 0.0:
            competitor_b.beat(competitor_a, match_time=match_time)
        else:
            competitor_a.tied(competitor_b, match_time=match_time)

    values = [competitor.rating for competitor in ratings.values()]
    assert values
    assert all(np.isfinite(value) for value in values)
    assert max(abs(value) for value in values) < 10000
    print(f"  ✓ Online ratings remain bounded: min={min(values):.2f}, max={max(values):.2f}")


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


def test_chunk_index_store_and_chunking():
    """测试 chunk 切分与缓存加载。"""
    print("\n[Test] Chunk Index Store")

    with tempfile.TemporaryDirectory() as tmpdir:
        embedder = CountingEmbedder(dim=32)
        store = ChunkIndexStore(embedder=embedder, cache_dir=tmpdir)
        document = FullTextDocument(
            doc_id="doc_1",
            title="长文",
            content="A" * 1600 + "B" * 1600,
        )

        chunks = chunk_document(document, chunk_size=1200, overlap=150)
        assert len(chunks) >= 2

        index_1 = store.build_or_load([document], prefix="favorite", chunk_size=1200, overlap=150, batch_size=8)
        calls_after_first = embedder.embed_calls
        index_2 = store.build_or_load([document], prefix="favorite", chunk_size=1200, overlap=150, batch_size=8)

        assert len(index_1.chunks) == len(index_2.chunks)
        assert embedder.embed_calls == calls_after_first
        print("  ✓ Chunk cache hit skips re-embedding")


def test_candidate_aware_rag_reranker():
    """测试 candidate-aware RAG 精排和解析回退。"""
    print("\n[Test] Candidate-Aware RAG Reranker")

    embedder = MockEmbedder(dim=64)
    favorites = [
        FullTextDocument(doc_id="fav_1", title="收藏A", content="学习 科学 认知 心理 学习 科学 " * 120),
        FullTextDocument(doc_id="fav_2", title="收藏B", content="教育 制度 分析 教育 制度 分析 " * 120),
    ]
    candidates = [
        FullTextDocument(doc_id="cand_1", title="候选A", content="学习 科学 方法 间隔重复 学习 科学 " * 120),
        FullTextDocument(doc_id="cand_2", title="候选B", content="教育 快乐教育 制度 对比 分析 " * 120),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        store = ChunkIndexStore(embedder=embedder, cache_dir=tmpdir)
        favorites_index = store.build_or_load(favorites, prefix="fav", batch_size=8)
        candidates_index = store.build_or_load(candidates, prefix="cand", batch_size=8)

        reranker = CandidateAwareRAGReranker(
            embedder=embedder,
            llm_client=FakeRAGClient(fail_on="《候选B》"),
            candidate_top_k=2,
            favorite_top_k=3,
            max_prompt_chars=6000,
        )
        profile = UserExplicitProfile(
            core_topics=["学习科学", "教育"],
            writing_style=["深度分析"],
            content_depth=["专业级"],
            negative_tags=["软广"],
            authors=[],
            custom_tags={},
        )

        documents_by_id = {doc.doc_id: doc for doc in candidates}
        scores, traces = reranker.rerank(
            candidate_documents=documents_by_id,
            candidate_ids=["cand_1", "cand_2"],
            favorites_index=favorites_index,
            candidate_index=candidates_index,
            explicit_profile=profile,
            profile_summary={"core_topics": profile.core_topics},
        )

        assert len(scores) == 2
        assert len(traces) == 2
        assert len(traces[0]["favorite_evidence"]) <= 3
        assert len(traces[0]["candidate_chunks"]) <= 2
        assert any(not trace["llm_success"] for trace in traces)
        assert any(score.reasoning.startswith("parse_failed:") for score in scores)
        print("  ✓ RAG evidence retrieval and fallback work")


def test_cleanup_json_text():
    """测试 JSON 清洗会移除 think 和代码块。"""
    print("\n[Test] Cleanup JSON Text")

    cleaned = cleanup_json_text('<think>abc</think>\n```json\n{"a": 1}\n```')

    assert cleaned == '{"a": 1}'
    print("  ✓ Cleanup removes think tags and fences")


def test_normalize_candidate_choice():
    """测试稳定 candidate_id 解析。"""
    print("\n[Test] Candidate ID Normalization")

    assert normalize_candidate_choice("cand_x", "cand_x", "cand_y") == "cand_x"
    assert normalize_candidate_choice("A", "cand_x", "cand_y") == "cand_x"
    assert normalize_candidate_choice("B", "cand_x", "cand_y") == "cand_y"
    assert normalize_candidate_choice("tie", "cand_x", "cand_y") == "tie"
    print("  ✓ Candidate ID normalization works")


def test_lm_studio_client_supports_auth_and_thinking_budget():
    """测试客户端会附带鉴权头和 thinking 参数。"""
    print("\n[Test] LM Studio Client Auth And Thinking Budget")

    captured = {}

    class _FakeHTTPResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": '{"ok": true}',
                            "reasoning_content": "hidden",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "completion_tokens_details": {"reasoning_tokens": 3},
                },
            }
            return json.dumps(payload).encode("utf-8")

    original_urlopen = urllib.request.urlopen

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeHTTPResponse()

    urllib.request.urlopen = fake_urlopen
    try:
        client = LMStudioLLMClient(
            base_url="https://api.siliconflow.cn/v1",
            model="deepseek-ai/DeepSeek-V3.2",
            max_tokens=128,
            api_key="test-key",
            extra_body={"thinking_budget": 4096},
        )
        response = client.chat([{"role": "user", "content": "hello"}])
    finally:
        urllib.request.urlopen = original_urlopen

    assert captured["url"] == "https://api.siliconflow.cn/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["thinking_budget"] == 4096
    assert response.usage["completion_tokens_details"]["reasoning_tokens"] == 3
    assert response.choices[0].message.reasoning_content == "hidden"
    print("  ✓ Client sends auth header and thinking budget")


def test_lm_studio_client_retries_retryable_http_errors():
    """测试客户端会重试可恢复的 HTTP 错误。"""
    print("\n[Test] LM Studio Client Retries Retryable Errors")

    attempts = {"count": 0}

    class _FakeHTTPResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            ).encode("utf-8")

    original_urlopen = urllib.request.urlopen
    original_sleep = time.sleep

    def fake_urlopen(request, timeout=0):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                hdrs=None,
                fp=None,
            )
        return _FakeHTTPResponse()

    urllib.request.urlopen = fake_urlopen
    time.sleep = lambda *_args, **_kwargs: None
    try:
        client = LMStudioLLMClient(
            base_url="https://api.siliconflow.cn/v1",
            model="deepseek-ai/DeepSeek-V3.2",
            max_tokens=64,
            api_key="test-key",
            max_retries=2,
            retry_backoff_seconds=0.01,
        )
        response = client.chat([{"role": "user", "content": "hello"}])
    finally:
        urllib.request.urlopen = original_urlopen
        time.sleep = original_sleep

    assert attempts["count"] == 2
    assert response.choices[0].message.content == '{"ok": true}'
    print("  ✓ Client retries retryable HTTP errors")


def test_make_client_pool_enables_thinking_mode():
    """测试 client pool 会显式打开 thinking mode。"""
    print("\n[Test] Client Pool Thinking Mode")

    pool = _make_client_pool(
        base_url="https://api.siliconflow.cn/v1",
        model="deepseek-ai/DeepSeek-V3.2",
        max_tokens=128,
        thinking_budget=4096,
        api_keys=["k1", "k2"],
        per_key_concurrency=2,
    )

    assert len(pool) == 4
    assert pool[0].extra_body["enable_thinking"] is True
    assert pool[0].extra_body["thinking_budget"] == 4096
    print("  ✓ Client pool enables thinking mode when budget > 0")


def test_simulator_sample_determinism_and_cache_isolation():
    """测试固定 seed 抽样稳定，压缩缓存按配置隔离。"""
    print("\n[Test] Simulator Sample Determinism And Cache Isolation")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(8):
            pool.append({
                "id": f"art_{idx}",
                "title": f"文章{idx}",
                "content": f"深度内容 {idx} " * 80,
                "content_type": "answer",
                "url": f"https://example.com/{idx}",
                "voteup_count": idx,
                "comment_count": idx // 2,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([
                {"id": "fav_1", "title": "收藏1", "content": "收藏内容1"},
                {"id": "fav_2", "title": "收藏2", "content": "收藏内容2"},
            ], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育", "学习"],
            writing_style=["深度分析"],
            content_depth=["专业级"],
            negative_tags=["标题党"],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        extractor_client = FakeAdaptiveExtractorClient()
        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            sample_size=4,
            sample_seed=7,
            extractor_model="model-a",
            judge_model="judge-a",
            initial_cover_rounds=1,
            max_effective_matches=4,
            max_total_attempts=6,
        )

        experiment_a = SimulatorGlickoExperiment(
            config=config,
            extractor_client=extractor_client,
            judge_client=FakeSimulatorJudgeClient(),
        )
        sample_a = experiment_a.prepare_sample()
        experiment_a.ensure_compressions(sample_a)
        first_call_count = len(extractor_client.calls)

        experiment_b = SimulatorGlickoExperiment(
            config=config,
            extractor_client=extractor_client,
            judge_client=FakeSimulatorJudgeClient(),
        )
        sample_b = experiment_b.prepare_sample()
        experiment_b.ensure_compressions(sample_b)

        assert [item.article_id for item in sample_a] == [item.article_id for item in sample_b]
        assert len(extractor_client.calls) == first_call_count

        config_new_model = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            sample_size=4,
            sample_seed=7,
            extractor_model="model-b",
            judge_model="judge-a",
            initial_cover_rounds=1,
            max_effective_matches=4,
            max_total_attempts=6,
        )
        experiment_c = SimulatorGlickoExperiment(
            config=config_new_model,
            extractor_client=extractor_client,
            judge_client=FakeSimulatorJudgeClient(),
        )
        experiment_c.ensure_compressions(experiment_c.prepare_sample())

        assert len(extractor_client.calls) > first_call_count
        print("  ✓ Stable sampling and cache isolation work")


def test_simulator_glicko_experiment_smoke():
    """测试全文 vs 压缩文本实验可端到端跑通。"""
    print("\n[Test] Simulator Glicko Experiment Smoke")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(6):
            pool.append({
                "id": f"doc_{idx}",
                "title": f"文档{idx}",
                "content": (f"文档{idx} 的正文。包含深度分析与例子。 " * 120),
                "content_type": "answer",
                "url": f"https://example.com/doc/{idx}",
                "voteup_count": idx * 10,
                "comment_count": idx,
                "metadata": {"source": "test"},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([
                {"id": "fav_1", "title": "喜欢的教育文", "content": "分析教育与学习"},
                {"id": "fav_2", "title": "喜欢的学习文", "content": "学习方法与认知"},
            ], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育", "学习方法"],
            writing_style=["深度分析", "长文"],
            content_depth=["专业级"],
            negative_tags=["标题党"],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            sample_size=6,
            sample_seed=11,
            initial_cover_rounds=1,
            max_effective_matches=6,
            max_total_attempts=12,
            swiss_rd_threshold=260.0,
            fulltext_max_chars=1600,
        )
        experiment = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=FakeSimulatorJudgeClient(),
        )

        result = experiment.run()

        assert os.path.exists(os.path.join(output_root, "runs", result["run_name"], "summary.json"))
        assert result["views"]["fulltext"]["effective_matches"] > 0
        assert result["views"]["compressed"]["effective_matches"] > 0
        assert "more_stable_view" in result["comparison"]
        assert "lower_cost_view" in result["comparison"]
        assert "view_semantics" in result["views"]["fulltext"]
        assert "result_interpretation" in result["views"]["compressed"]
        assert result["views"]["compressed"]["warnings"]
        assert result["views"]["fulltext"]["top_items"]
        assert result["views"]["compressed"]["top_items"]
        assert abs(result["views"]["fulltext"]["rating_max"]) < 10000
        assert abs(result["views"]["compressed"]["rating_max"]) < 10000
        assert result["views"]["fulltext"]["rd_min"] > 0
        assert result["views"]["compressed"]["rd_min"] > 0
        assert "top_k_overlap_rate" in result["comparison"]
        assert "top_k_jaccard" in result["comparison"]
        assert "shared_item_rank_gap_mean" in result["comparison"]
        assert "top_1_same" in result["comparison"]
        assert "view_divergence_note" in result["comparison"]
        print("  ✓ End-to-end simulator experiment completed")


def test_simulator_glicko_compressed_only_smoke():
    """测试 compressed-only 模式可以单独运行。"""
    print("\n[Test] Simulator Glicko Compressed-Only Smoke")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(4):
            pool.append({
                "id": f"doc_only_{idx}",
                "title": f"单视图文档{idx}",
                "content": (f"单视图文档{idx} 正文，包含分析与例子。 " * 80),
                "content_type": "answer",
                "url": f"https://example.com/only/{idx}",
                "voteup_count": idx,
                "comment_count": idx,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([
                {"id": "fav_only_1", "title": "收藏A", "content": "收藏内容A"},
                {"id": "fav_only_2", "title": "收藏B", "content": "收藏内容B"},
            ], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育"],
            writing_style=["分析"],
            content_depth=["专业级"],
            negative_tags=[],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            sample_size=4,
            sample_seed=3,
            initial_cover_rounds=1,
            max_effective_matches=4,
            max_total_attempts=8,
            view_types=("compressed",),
        )
        experiment = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=FakeSimulatorJudgeClient(),
        )

        result = experiment.run()

        assert "compressed" in result["views"]
        assert "fulltext" not in result["views"]
        assert result["comparison"] is None
        assert result["views"]["compressed"]["top_items"]
        assert abs(result["views"]["compressed"]["rating_max"]) < 10000
        assert result["views"]["compressed"]["rd_min"] > 0
        print("  ✓ Compressed-only simulator experiment completed")


def test_simulator_glicko_compressed_only_parallel_smoke():
    """测试正式 compressed-only 主实验可以使用多个 judge clients。"""
    print("\n[Test] Simulator Glicko Compressed-Only Parallel Smoke")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(4):
            pool.append({
                "id": f"doc_parallel_{idx}",
                "title": f"并发文档{idx}",
                "content": (f"并发文档{idx} 正文，包含分析与例子。 " * 80),
                "content_type": "answer",
                "url": f"https://example.com/parallel/{idx}",
                "voteup_count": idx,
                "comment_count": idx,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([
                {"id": "fav_parallel_1", "title": "收藏A", "content": "收藏内容A"},
                {"id": "fav_parallel_2", "title": "收藏B", "content": "收藏内容B"},
            ], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育"],
            writing_style=["分析"],
            content_depth=["专业级"],
            negative_tags=[],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            sample_size=4,
            sample_seed=4,
            initial_cover_rounds=1,
            max_effective_matches=4,
            max_total_attempts=4,
            view_types=("compressed",),
            view_judge_max_workers=2,
        )
        judge_a = FakeSimulatorJudgeClient()
        judge_b = FakeSimulatorJudgeClient()
        experiment = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=judge_a,
            judge_clients=[judge_a, judge_b],
        )

        result = experiment.run()

        assert "compressed" in result["views"]
        assert len(judge_a.calls) > 0
        assert len(judge_b.calls) > 0
        print("  ✓ Compressed-only simulator experiment uses multiple judge clients")


def test_simulator_fixed_pair_calibration():
    """测试固定 pair 校准 runner 会同时输出 legacy/new 摘要。"""
    print("\n[Test] Simulator Fixed Pair Calibration")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(4):
            pool.append({
                "id": f"doc_cal_{idx}",
                "title": f"校准文档{idx}",
                "content": (f"校准文档{idx} 正文，包含分析与例子。 " * 60),
                "content_type": "answer",
                "url": f"https://example.com/cal/{idx}",
                "voteup_count": idx,
                "comment_count": idx,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([
                {"id": "fav_cal_1", "title": "收藏A", "content": "收藏内容A"},
            ], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育"],
            writing_style=["分析"],
            content_depth=["专业级"],
            negative_tags=[],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            sample_size=4,
            sample_seed=5,
            view_types=("compressed",),
        )
        experiment = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=FixedPairPromptJudgeClient(),
        )

        result = experiment.run_fixed_pair_calibration(
            FixedPairCalibrationConfig(
                pair_specs=[
                    FixedPairSpec(match_id="pair_1", article_a_id="doc_cal_0", article_b_id="doc_cal_1"),
                    FixedPairSpec(match_id="pair_2", article_a_id="doc_cal_2", article_b_id="doc_cal_3"),
                ],
                view_type="compressed",
                compare_legacy_prompt=True,
            )
        )

        assert "legacy_v1" in result["summary"]
        assert "candidate_id_v2" in result["summary"]
        assert result["summary"]["legacy_v1"]["order_flip_rate"] == 1.0
        assert result["summary"]["candidate_id_v2"]["order_flip_rate"] == 0.0
        print("  ✓ Fixed pair calibration distinguishes legacy vs new prompt")


def test_simulator_resumable_fixed_pair_runner_outputs_and_resume():
    """测试稳态 fixed-pair runner 会落盘且二次运行不会重复。"""
    print("\n[Test] Resumable Fixed Pair Runner Outputs And Resume")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(4):
            pool.append({
                "id": f"doc_res_{idx}",
                "title": f"恢复文档{idx}",
                "content": (f"恢复文档{idx} 正文，包含分析与例子。 " * 60),
                "content_type": "answer",
                "url": f"https://example.com/res/{idx}",
                "voteup_count": idx,
                "comment_count": idx,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "fav_res_1", "title": "收藏A", "content": "收藏内容A"}], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育"],
            writing_style=["分析"],
            content_depth=["专业级"],
            negative_tags=[],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            run_name="resumable_fixed_pair_test",
            sample_size=4,
            sample_seed=7,
            fixed_pair_max_workers=1,
            view_types=("compressed",),
        )
        judge_client = FixedPairPromptJudgeClient()
        experiment = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=judge_client,
            judge_clients=[judge_client],
        )
        calibration = FixedPairCalibrationConfig(
            pair_specs=[
                FixedPairSpec(match_id="pair_r1", article_a_id="doc_res_0", article_b_id="doc_res_1"),
                FixedPairSpec(match_id="pair_r2", article_a_id="doc_res_2", article_b_id="doc_res_3"),
            ],
            view_type="compressed",
            compare_legacy_prompt=False,
            prompt_mode="candidate_id_v2",
        )

        result = experiment.run_resumable_fixed_pair_calibration(calibration)
        run_dir = os.path.join(output_root, "runs", config.run_name)
        assert result["summary"]["prompt_mode"] == "candidate_id_v2"
        assert result["summary"]["pair_count_completed"] == 2
        assert os.path.exists(os.path.join(run_dir, "startup_state.json"))
        assert os.path.exists(os.path.join(run_dir, "network_probe.json"))
        assert os.path.exists(os.path.join(run_dir, "request_log.ndjson"))
        assert os.path.exists(os.path.join(run_dir, "pair_results.ndjson"))
        assert os.path.exists(os.path.join(run_dir, "summary.json"))

        pair_lines_before = sum(1 for _ in open(os.path.join(run_dir, "pair_results.ndjson"), "r", encoding="utf-8"))
        call_count_before = len(judge_client.calls)
        result2 = experiment.run_resumable_fixed_pair_calibration(calibration)
        pair_lines_after = sum(1 for _ in open(os.path.join(run_dir, "pair_results.ndjson"), "r", encoding="utf-8"))
        assert result2["summary"]["pair_count_completed"] == 2
        assert pair_lines_after == pair_lines_before == 2
        assert len(judge_client.calls) == call_count_before
        print("  ✓ Resumable runner writes files and skips completed pairs")


def test_simulator_resumable_fixed_pair_runner_resumes_after_failure():
    """测试中途失败后可从已有结果继续补完。"""
    print("\n[Test] Resumable Fixed Pair Runner Resumes After Failure")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(4):
            pool.append({
                "id": f"doc_fail_{idx}",
                "title": f"失败文档{idx}",
                "content": (f"失败文档{idx} 正文，包含分析与例子。 " * 60),
                "content_type": "answer",
                "url": f"https://example.com/fail/{idx}",
                "voteup_count": idx,
                "comment_count": idx,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "fav_fail_1", "title": "收藏A", "content": "收藏内容A"}], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育"],
            writing_style=["分析"],
            content_depth=["专业级"],
            negative_tags=[],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            run_name="resumable_failure_test",
            sample_size=4,
            sample_seed=9,
            fixed_pair_max_workers=1,
            fixed_pair_retry_limit=1,
            view_types=("compressed",),
        )
        first_judge = FixedPairRetryJudgeClient(fail_title="失败文档2", fail_times=1)
        calibration = FixedPairCalibrationConfig(
            pair_specs=[
                FixedPairSpec(match_id="pair_f1", article_a_id="doc_fail_0", article_b_id="doc_fail_1"),
                FixedPairSpec(match_id="pair_f2", article_a_id="doc_fail_2", article_b_id="doc_fail_3"),
            ],
            view_type="compressed",
            compare_legacy_prompt=False,
            prompt_mode="candidate_id_v2",
        )

        experiment1 = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=first_judge,
            judge_clients=[first_judge],
        )
        result1 = experiment1.run_resumable_fixed_pair_calibration(calibration)
        assert result1["summary"]["pair_count_completed"] == 1
        assert result1["summary"]["pair_count_pending"] == 1

        second_judge = FixedPairPromptJudgeClient()
        experiment2 = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=second_judge,
            judge_clients=[second_judge],
        )
        result2 = experiment2.run_resumable_fixed_pair_calibration(calibration)
        run_dir = os.path.join(output_root, "runs", config.run_name)
        pair_lines = sum(1 for _ in open(os.path.join(run_dir, "pair_results.ndjson"), "r", encoding="utf-8"))
        assert result2["summary"]["pair_count_completed"] == 2
        assert result2["summary"]["pair_count_pending"] == 0
        assert pair_lines == 2
        print("  ✓ Resumable runner continues from partial results")


def test_simulator_resumable_fixed_pair_runner_degrades_on_probe_failure():
    """测试 preflight 失败会把 worker 计划降级。"""
    print("\n[Test] Resumable Fixed Pair Runner Degrades On Probe Failure")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(4):
            pool.append({
                "id": f"doc_deg_{idx}",
                "title": f"降级文档{idx}",
                "content": (f"降级文档{idx} 正文，包含分析与例子。 " * 60),
                "content_type": "answer",
                "url": f"https://example.com/deg/{idx}",
                "voteup_count": idx,
                "comment_count": idx,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "fav_deg_1", "title": "收藏A", "content": "收藏内容A"}], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育"],
            writing_style=["分析"],
            content_depth=["专业级"],
            negative_tags=[],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            run_name="resumable_degrade_test",
            sample_size=4,
            sample_seed=11,
            fixed_pair_max_workers=6,
            view_types=("compressed",),
        )
        judge_clients = [ProbeFailOnceJudgeClient()] + [FixedPairPromptJudgeClient() for _ in range(5)]
        for idx, client in enumerate(judge_clients):
            client.api_key_slot = idx // 2
            client.worker_slot = idx

        calibration = FixedPairCalibrationConfig(
            pair_specs=[
                FixedPairSpec(match_id=f"pair_d{idx}", article_a_id="doc_deg_0", article_b_id="doc_deg_1")
                for idx in range(6)
            ],
            view_type="compressed",
            compare_legacy_prompt=False,
            prompt_mode="candidate_id_v2",
        )
        experiment = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=judge_clients[0],
            judge_clients=judge_clients,
        )
        result = experiment.run_resumable_fixed_pair_calibration(calibration)
        assert result["summary"]["worker_plan_initial"] == 6
        assert result["summary"]["worker_plan_final"] == 3
        assert result["summary"]["degrade_events"]
        print("  ✓ Probe failure triggers worker plan downgrade")


def test_simulator_resumable_fixed_pair_runner_pinned_workers_do_not_degrade():
    """测试 pinned worker 模式下即使发生请求错误也不会自动降级。"""
    print("\n[Test] Resumable Fixed Pair Runner Pinned Workers Stay Fixed")

    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = os.path.join(tmpdir, "pool.json")
        profile_path = os.path.join(tmpdir, "explicit_profile.json")
        favorites_path = os.path.join(tmpdir, "favorites.json")
        output_root = os.path.join(tmpdir, "simulator")

        pool = []
        for idx in range(4):
            pool.append({
                "id": f"doc_pin_{idx}",
                "title": f"钉死文档{idx}",
                "content": (f"钉死文档{idx} 正文，包含分析与例子。 " * 60),
                "content_type": "answer",
                "url": f"https://example.com/pin/{idx}",
                "voteup_count": idx,
                "comment_count": idx,
                "metadata": {},
            })
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "fav_pin_1", "title": "收藏A", "content": "收藏内容A"}], f, ensure_ascii=False, indent=2)

        profile = UserExplicitProfile(
            core_topics=["教育"],
            writing_style=["分析"],
            content_depth=["专业级"],
            negative_tags=[],
            authors=[],
            custom_tags={},
        )
        profile.save(profile_path)

        config = SimulatorExperimentConfig(
            sample_pool_path=pool_path,
            explicit_profile_path=profile_path,
            favorites_path=favorites_path,
            output_root=output_root,
            run_name="resumable_pinned_test",
            sample_size=4,
            sample_seed=13,
            fixed_pair_max_workers=3,
            fixed_pair_retry_limit=2,
            view_types=("compressed",),
        )
        flaky_client = FixedPairRetryJudgeClient(fail_title="钉死文档2", fail_times=1)
        flaky_client.api_key_slot = 0
        flaky_client.worker_slot = 0
        steady_a = FixedPairPromptJudgeClient()
        steady_a.api_key_slot = 1
        steady_a.worker_slot = 1
        steady_b = FixedPairPromptJudgeClient()
        steady_b.api_key_slot = 2
        steady_b.worker_slot = 2
        calibration = FixedPairCalibrationConfig(
            pair_specs=[
                FixedPairSpec(match_id="pair_p1", article_a_id="doc_pin_0", article_b_id="doc_pin_1"),
                FixedPairSpec(match_id="pair_p2", article_a_id="doc_pin_2", article_b_id="doc_pin_3"),
            ],
            view_type="compressed",
            compare_legacy_prompt=False,
            prompt_mode="candidate_id_v2",
            pinned_worker_plan=3,
            enable_auto_degrade=False,
            benchmark_label="workers_3",
        )

        experiment = SimulatorGlickoExperiment(
            config=config,
            extractor_client=FakeAdaptiveExtractorClient(),
            judge_client=flaky_client,
            judge_clients=[flaky_client, steady_a, steady_b],
        )
        result = experiment.run_resumable_fixed_pair_calibration(calibration)
        assert result["summary"]["pair_count_completed"] == 2
        assert result["summary"]["worker_plan_initial"] == result["summary"]["worker_plan_final"]
        assert result["summary"]["worker_plan_initial"] == 2
        assert result["summary"]["degrade_events"] == []
        assert result["summary"]["request_count"] >= 4
        print("  ✓ Pinned worker mode keeps worker plan fixed")


def test_fixed_pair_benchmark_comparison_prefers_low_error_then_flip_then_time():
    """测试 benchmark 汇总按稳定优先规则选择赢家。"""
    print("\n[Test] Fixed Pair Benchmark Winner Rule")

    comparison = build_fixed_pair_benchmark_comparison(
        {
            "workers_3": {
                "pair_count_total": 100,
                "pair_count_completed": 100,
                "parse_failures": 0,
                "request_error_rate": 0.02,
                "order_flip_rate": 0.31,
                "wall_clock_seconds": 1000.0,
            },
            "workers_6": {
                "pair_count_total": 100,
                "pair_count_completed": 100,
                "parse_failures": 0,
                "request_error_rate": 0.025,
                "order_flip_rate": 0.21,
                "wall_clock_seconds": 900.0,
            },
            "workers_9": {
                "pair_count_total": 100,
                "pair_count_completed": 90,
                "parse_failures": 0,
                "request_error_rate": 0.01,
                "order_flip_rate": 0.15,
                "wall_clock_seconds": 800.0,
            },
        }
    )
    assert comparison["winner"] == "workers_6"
    assert comparison["qualified_runs"]["workers_9"] is False
    print("  ✓ Benchmark winner rule works")


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
        test_glicko2_online_updates_remain_bounded()
        test_pairwise_evaluation_session()
        test_llm_pairwise_order_experiment()
        test_reranker_stability_experiment()
        test_order_instability_attribution_experiment()
        test_chunk_index_store_and_chunking()
        test_candidate_aware_rag_reranker()
        test_cleanup_json_text()
        test_normalize_candidate_choice()
        test_lm_studio_client_supports_auth_and_thinking_budget()
        test_lm_studio_client_retries_retryable_http_errors()
        test_make_client_pool_enables_thinking_mode()
        test_simulator_sample_determinism_and_cache_isolation()
        test_simulator_glicko_experiment_smoke()
        test_simulator_glicko_compressed_only_smoke()
        test_simulator_glicko_compressed_only_parallel_smoke()
        test_simulator_fixed_pair_calibration()
        test_simulator_resumable_fixed_pair_runner_outputs_and_resume()
        test_simulator_resumable_fixed_pair_runner_resumes_after_failure()
        test_simulator_resumable_fixed_pair_runner_degrades_on_probe_failure()
        test_simulator_resumable_fixed_pair_runner_pinned_workers_do_not_degrade()
        test_fixed_pair_benchmark_comparison_prefers_low_error_then_flip_then_time()

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
