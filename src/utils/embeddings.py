"""
Embedding工具 - 文本向量化
支持多种embedding provider
"""

import numpy as np
from typing import List, Union, Optional, Callable
import hashlib
import json
import urllib.request


class BaseEmbedder:
    """Embedding基类"""

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        """单文本embedding"""
        raise NotImplementedError

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[np.ndarray]:
        """批量embedding"""
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            for text in batch:
                results.append(self.embed(text))
        return results


class MockEmbedder(BaseEmbedder):
    """
    Mock Embedding - 用于测试
    基于文本哈希生成确定性向量
    """

    def embed(self, text: str) -> np.ndarray:
        """基于文本内容生成确定性向量"""
        # 使用哈希生成种子
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        np.random.seed(hash_val % (2**32))

        # 生成归一化向量
        vec = np.random.randn(self.dim)
        vec = vec / (np.linalg.norm(vec) + 1e-8)

        # 重置随机种子
        np.random.seed(None)

        return vec


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI API Embedding (text-embedding-3-large)"""

    def __init__(self, api_key: str, model: str = "text-embedding-3-large", dim: int = 1024):
        super().__init__(dim)
        self.api_key = api_key
        self.model = model
        self.client = None

    def _get_client(self):
        if self.client is None:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("Please install openai: pip install openai")
        return self.client

    def embed(self, text: str) -> np.ndarray:
        client = self._get_client()
        response = client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self.dim
        )
        return np.array(response.data[0].embedding)

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[np.ndarray]:
        client = self._get_client()
        results = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            response = client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dim
            )
            batch_results = [np.array(d.embedding) for d in response.data]
            results.extend(batch_results)

        return results


class LocalEmbedder(BaseEmbedder):
    """
    本地Embedding模型 (Sentence Transformers)
    """

    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5", device: str = "auto"):
        # 自动确定维度
        model_dims = {
            "BAAI/bge-large-zh-v1.5": 1024,
            "BAAI/bge-m3": 1024,
            "sentence-transformers/all-MiniLM-L6-v2": 384,
        }
        dim = model_dims.get(model_name, 1024)
        super().__init__(dim)

        self.model_name = model_name
        self.device = device
        self.model = None

    def _get_model(self):
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name, device=self.device)
            except ImportError:
                raise ImportError("Please install sentence-transformers: pip install sentence-transformers")
        return self.model

    def embed(self, text: str) -> np.ndarray:
        model = self._get_model()
        embedding = model.encode(text, normalize_embeddings=True)
        return np.array(embedding)

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[np.ndarray]:
        model = self._get_model()
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 100
        )
        return [np.array(e) for e in embeddings]


class LMStudioEmbedder(BaseEmbedder):
    """
    LM Studio 本地 Embedding (OpenAI 兼容 API)
    默认使用 bge-large-zh-v1.5
    """

    def __init__(self, base_url: str = "http://localhost:1234/v1",
                 model: str = "text-embedding-bge-large-zh-v1.5",
                 dim: int = 1024):
        super().__init__(dim)
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _call_api(self, texts: List[str]) -> List[np.ndarray]:
        """调用 LM Studio embeddings API"""
        url = f"{self.base_url}/embeddings"
        payload = json.dumps({
            "model": self.model,
            "input": texts
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        # 按 index 排序，保证返回顺序与输入一致
        sorted_data = sorted(result["data"], key=lambda x: x["index"])
        return [np.array(d["embedding"], dtype=np.float32) for d in sorted_data]

    def embed(self, text: str) -> np.ndarray:
        return self._call_api([text])[0]

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[np.ndarray]:
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            results.extend(self._call_api(batch))
        return results


def get_embedder(embedder_type: str = "mock", **kwargs) -> BaseEmbedder:
    """
    工厂函数，获取指定的Embedder

    Args:
        embedder_type: "mock", "openai", "local", "lmstudio"
        **kwargs: 传递给具体Embedder的参数
    """
    if embedder_type == "mock":
        return MockEmbedder(**kwargs)
    elif embedder_type == "openai":
        return OpenAIEmbedder(**kwargs)
    elif embedder_type == "local":
        return LocalEmbedder(**kwargs)
    elif embedder_type == "lmstudio":
        return LMStudioEmbedder(**kwargs)
    else:
        raise ValueError(f"Unknown embedder type: {embedder_type}")
