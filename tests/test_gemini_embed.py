"""
测试 Google Gemini Embedding (GoogleEmbedder) 的功能
"""

import sys
import os
import numpy as np

# 将项目根目录添加到 python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils.embeddings import get_embedder, GoogleEmbedder

def test_gemini_embedding():
    # 使用之前验证成功的 API key
    api_key = "AIzaSyCy2esuHFZWQDaSmJkO7cttLzKa3OOK52Y"
    
    print("1. 测试工厂实例化...")
    embedder = get_embedder("gemini", api_key=api_key)
    assert isinstance(embedder, GoogleEmbedder), "工厂函数获取的 embedder 类型不正确"
    print("  ✓ 工厂实例化成功！")
    
    print("\n2. 测试单文本向量化...")
    text = "推荐系统极速向量召回验证"
    vec = embedder.embed(text)
    print(f"  输入文本: {text}")
    print(f"  返回向量类型: {type(vec)}")
    print(f"  返回向量维度: {vec.shape}")
    assert isinstance(vec, np.ndarray), "返回类型应为 numpy 数组"
    assert vec.ndim == 1, "单文本 embedding 应该是 1 维数组"
    assert vec.shape[0] == 768, f"默认维度应为 768，但得到 {vec.shape[0]}"
    print("  ✓ 单文本向量化成功！")
    
    print("\n3. 测试批量文本向量化 (并发与分块切片)...")
    texts = [
        "Google Gemini API 极速向量化运算",
        "替换原有的本地或 Mock 方案",
        "使用高并发的 ThreadPoolExecutor 批量请求",
        "自动进行分块切片 slice 处理",
        "应对 Too Many Requests 并发限制",
    ]
    # 使用 batch_size=2 来强制触发切片分批逻辑
    vecs = embedder.embed_batch(texts, batch_size=2)
    print(f"  输入文本数量: {len(texts)}")
    print(f"  返回向量矩阵类型: {type(vecs)}")
    print(f"  返回向量矩阵维度: {vecs.shape}")
    assert isinstance(vecs, np.ndarray), "返回类型应为 numpy 矩阵"
    assert vecs.ndim == 2, "批量 embedding 应该是 2 维矩阵"
    assert vecs.shape == (5, 768), f"预期维度 (5, 768)，实际 {vecs.shape}"
    print("  ✓ 批量文本向量化成功！")

    print("\n4. 测试自定义降维输出 (Matryoshka Output Dimensionality)...")
    # API 支持 v1beta 的 outputDimensionality，比如设定 dim=256
    reduced_embedder = get_embedder("gemini", api_key=api_key, dim=256)
    reduced_vecs = reduced_embedder.embed_batch(texts, batch_size=2)
    print(f"  设置维度: 256")
    print(f"  返回向量矩阵维度: {reduced_vecs.shape}")
    assert reduced_vecs.shape == (5, 256), f"预期维度 (5, 256)，实际 {reduced_vecs.shape}"
    print("  ✓ 自定义降维输出成功！")

if __name__ == "__main__":
    try:
        test_gemini_embedding()
        print("\n🎉 所有 Google Gemini Embedding 单元测试全部通过！")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
