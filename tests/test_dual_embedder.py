"""
测试双轨向量设计与推荐管线
"""

import sys
import os
import tempfile
import json
import shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from src.profiling.implicit_profile import VectorCloud
from src.profiling.feedback_memory import FeedbackMemory
from src.contracts.config import PipelineConfig
from src.engine import PersonalRecSys, CandidateItem
from src.utils.embeddings import MockEmbedder


def test_feedback_memory_dimension_filtering():
    """测试 FeedbackMemory 在混合维度下的过滤防御，防止 dot 乘积崩溃"""
    print("\n[Test] FeedbackMemory Dimension Filtering")
    fml = FeedbackMemory()

    # 模拟在 feedback memory 中存入 256 维 (coarse) 和 128 维 (fine) 的反馈向量
    vec_256 = np.random.randn(256).astype(np.float32)
    vec_128 = np.random.randn(128).astype(np.float32)

    # 注入数据结构中
    fml.negative_vectors["item_256"] = vec_256.tolist()
    fml.negative_vectors["item_128"] = vec_128.tolist()

    fml.duplicate_vectors["dup_256"] = vec_256.tolist()
    fml.duplicate_vectors["dup_128"] = vec_128.tolist()

    # 1. 提取 128 维的负反馈矩阵
    neg_128 = fml.get_negative_vectors_matrix(target_dim=128)
    assert neg_128.shape == (1, 128), f"Expected (1, 128), got {neg_128.shape}"
    assert np.allclose(neg_128[0], vec_128), "Vector content does not match"

    # 2. 提取 256 维的负反馈矩阵
    neg_256 = fml.get_negative_vectors_matrix(target_dim=256)
    assert neg_256.shape == (1, 256), f"Expected (1, 256), got {neg_256.shape}"
    assert np.allclose(neg_256[0], vec_256), "Vector content does not match"

    # 3. 提取不存在的维度，应返回空矩阵而不是报错
    neg_empty = fml.get_negative_vectors_matrix(target_dim=512)
    assert neg_empty.shape == (0, 512), f"Expected (0, 512), got {neg_empty.shape}"

    # 4. 重复过滤矩阵同理
    dup_128 = fml.get_duplicate_vectors_matrix(target_dim=128)
    assert dup_128.shape == (1, 128), f"Expected (1, 128), got {dup_128.shape}"
    print("  ✓ FeedbackMemory dimension filtering works correctly")


def test_dual_embedder_pipeline():
    """测试双轨向量召回 + 精排重计算完整推荐管线"""
    print("\n[Test] Dual Embedder Pipeline Integration")

    temp_dir = tempfile.mkdtemp()
    try:
        # 1. 创建配置
        # 粗召回维度: 256-dim (模拟 BGE)
        # 精重排维度: 128-dim (模拟 Gemini)
        config = PipelineConfig(
            embedding_dim=256,
            enable_dual_embedder=True,
            fine_embedder_type="mock",
            fine_embedding_dim=128,
            cache_dir=temp_dir,
            top_k=2,
            preset="precision"
        )

        coarse_embedder = MockEmbedder(dim=256)
        fine_embedder = MockEmbedder(dim=128)

        recsys = PersonalRecSys(
            embedder=coarse_embedder,
            embedding_dim=256,
            cache_dir=temp_dir,
            config=config,
            fine_embedder=fine_embedder
        )

        assert recsys.coarse_embedder is coarse_embedder
        assert recsys.fine_embedder is fine_embedder
        assert recsys.vector_cloud is None
        assert recsys.vector_cloud_fine is None

        # 2. 构建用户画像
        collection = [
            {"title": "机器学习基础", "content": "学习机器学习和深度学习的好处"},
            {"title": "高等数学", "content": "微积分与线性代数"}
        ]
        recsys.build_profile_from_collection(collection)

        # 验证是否生成了粗细两个向量云
        assert recsys.vector_cloud is not None
        assert recsys.vector_cloud_fine is not None
        assert len(recsys.vector_cloud.vectors) == 2
        assert len(recsys.vector_cloud_fine.vectors) == 2
        assert recsys.vector_cloud.vectors_matrix.shape[1] == 256
        assert recsys.vector_cloud_fine.vectors_matrix.shape[1] == 128

        # 3. 验证画像缓存加载/保存
        recsys_new = PersonalRecSys(
            embedder=coarse_embedder,
            embedding_dim=256,
            cache_dir=temp_dir,
            config=config,
            fine_embedder=fine_embedder
        )
        assert recsys_new.vector_cloud is not None
        assert recsys_new.vector_cloud_fine is not None
        assert recsys_new.vector_cloud.vectors_matrix.shape[1] == 256
        assert recsys_new.vector_cloud_fine.vectors_matrix.shape[1] == 128

        # 4. 添加候选集
        candidates = [
            CandidateItem(item_id="cand_1", title="机器学习大模型", content="深度学习大型语言模型实践与思考"),
            CandidateItem(item_id="cand_2", title="微积分与代数", content="微积分极限和导数的概念"),
            CandidateItem(item_id="cand_3", title="做饭教程", content="如何在家做一顿美味的晚餐"),
        ]
        recsys.add_candidates(candidates)

        # 此时应尚未生成 fine embeddings
        assert recsys.candidates["cand_1"].embedding_fine is None

        # 5. 执行推荐 (召回/排序)
        results = recsys.recommend(top_k=2)

        # 检查是否成功推荐了 top-2
        assert len(results.ranked_items) == 2
        
        # 验证 Top-2 候选的 fine embedding 是否在运行中被按需计算并回写
        # 推荐出来的候选必然被计算了 fine embedding
        item_ids = [item.item_id for item in results.ranked_items]
        for item_id in item_ids:
            assert recsys.candidates[item_id].embedding_fine is not None
            assert len(recsys.candidates[item_id].embedding_fine) == 128

        # 验证缓存文件的生成
        cache_fine_path = Path(temp_dir) / "candidate_embeddings_fine.npz"
        cache_coarse_path = Path(temp_dir) / "candidate_embeddings.npz"
        assert cache_fine_path.exists(), "Fine candidate cache should be created"
        
        # 加载缓存验证内容维度
        with np.load(cache_fine_path, allow_pickle=False) as data:
            assert data["embeddings"].shape[1] == 128
            
        print("  ✓ Dual embedder pipeline integration verified successfully")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_all_tests():
    print("=" * 60)
    print("Personal RecSys - Dual Embedder Unit Tests")
    print("=" * 60)
    try:
        test_feedback_memory_dimension_filtering()
        test_dual_embedder_pipeline()
        print("\n" + "=" * 60)
        print("All Dual Embedder Tests Passed!")
        print("=" * 60)
        return True
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    run_all_tests()
