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
        """基于文本内容生成确定性向量（使用本地随机状态，不污染全局 RNG）"""
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        rng = np.random.RandomState(hash_val % (2**32))
        vec = rng.randn(self.dim)
        vec = vec / (np.linalg.norm(vec) + 1e-8)
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
    OpenAI 兼容 Embedding 客户端 (原 LM Studio Embedder)
    支持对接本地 LM Studio，也支持对接 SiliconFlow 等线上服务。
    """

    def __init__(self, base_url: str = "http://localhost:1234/v1",
                 model: str = "text-embedding-bge-large-zh-v1.5",
                 api_key: Optional[str] = None,
                 dim: int = 1024):
        super().__init__(dim)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def _call_api(self, texts: List[str]) -> List[np.ndarray]:
        """调用 embeddings API"""
        url = f"{self.base_url}/embeddings"
        payload = json.dumps({
            "model": self.model,
            "input": texts
        }).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            url,
            data=payload,
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        # 按 index 排序，保证返回顺序与输入一致
        data_list = result.get("data", [])
        if any("index" not in d for d in data_list):
            sorted_data = data_list
        else:
            sorted_data = sorted(data_list, key=lambda x: x["index"])
        return [np.array(d["embedding"], dtype=np.float32) for d in sorted_data]

    def embed(self, text: str) -> np.ndarray:
        return self._call_api([text])[0]

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[np.ndarray]:
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            results.extend(self._call_api(batch))
        return results


class GoogleEmbedder(BaseEmbedder):
    """
    Google Gemini API Embedding (text-embedding-004)
    使用 google-genai 库并支持高并发 embed_batch 与重试
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-004", dim: int = 768, **kwargs):
        super().__init__(dim)
        self.api_key = api_key
        self.model = model
        self.client = None

    def _get_client(self):
        if self.client is None:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except ImportError:
                raise ImportError("Please install google-genai: pip install google-genai")
        return self.client

    def _call_api_with_fallback(self, client, contents: Union[str, List[str]], max_retries: int = 5) -> List[np.ndarray]:
        from google.genai import types
        import random
        import time

        # 将输入文本统一包装为 types.Content 对象列表，以防止 SDK 在处理 list[str] 时将其聚合为单个 embedding
        if isinstance(contents, str):
            api_contents = [types.Content(parts=[types.Part.from_text(text=contents)])]
        else:
            api_contents = [types.Content(parts=[types.Part.from_text(text=t)]) for t in contents]

        base_delay = 1.0
        
        for attempt in range(max_retries):
            # 1. 尝试使用 output_dimensionality 降维参数进行请求
            try:
                config = None
                if self.dim:
                    config = types.EmbedContentConfig(output_dimensionality=self.dim)
                response = client.models.embed_content(
                    model=self.model,
                    contents=api_contents,
                    config=config
                )
                return [np.array(emb.values, dtype=np.float32) for emb in response.embeddings]
            except Exception as e:
                err_msg = str(e)
                
                # 检查是否因为 text-embedding-004 废弃导致 404 NOT_FOUND
                is_not_found = "404" in err_msg or "not_found" in err_msg.lower() or "not found" in err_msg.lower()
                if is_not_found and self.model == "text-embedding-004":
                    # 动态切换到当前可用且支持 output_dimensionality 降维的 gemini-embedding-2 模型
                    self.model = "gemini-embedding-2"
                    continue

                # 检查是否为 429 Too Many Requests 错误
                is_429 = False
                if hasattr(e, "code") and getattr(e, "code") == 429:
                    is_429 = True
                elif hasattr(e, "status_code") and getattr(e, "status_code") == 429:
                    is_429 = True
                elif "429" in err_msg or "resource_exhausted" in err_msg.lower() or "rate_limit" in err_msg.lower() or "ratelimit" in err_msg.lower():
                    is_429 = True

                # 如果是 429 且未超重试次数，执行退避重试
                if is_429 and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    time.sleep(delay)
                    continue

                # 如果是其他配置/降维不支持错误，回退到不指定降维参数请求，再在本地做截断或填充处理
                if self.dim and not is_429:
                    try:
                        response = client.models.embed_content(
                            model=self.model,
                            contents=api_contents
                        )
                        embeddings = []
                        for emb in response.embeddings:
                            vals = np.array(emb.values, dtype=np.float32)
                            if len(vals) != self.dim:
                                if len(vals) > self.dim:
                                    vals = vals[:self.dim]
                                else:
                                    vals = np.pad(vals, (0, self.dim - len(vals)), 'constant')
                            embeddings.append(vals)
                        return embeddings
                    except Exception as fallback_err:
                        raise fallback_err

                raise e
        
        raise RuntimeError("Failed to call Gemini Embedding API after retries.")

    def embed(self, text: str) -> np.ndarray:
        client = self._get_client()
        return self._call_api_with_fallback(client, text)[0]

    def embed_batch(self, texts: List[str], batch_size: int = 10) -> np.ndarray:
        """
        高并发地批量获取 texts 的 embedding 并返回 numpy 矩阵
        """
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)

        client = self._get_client()
        import concurrent.futures

        batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
        results = [None] * len(batches)

        def process_batch(batch_idx: int, batch_texts: List[str]) -> List[np.ndarray]:
            import time
            result = self._call_api_with_fallback(client, batch_texts)
            # Gemini Free Tier 限制为 15 RPM (每分钟 15 次请求)。
            # 每发送一个 batch 强制休眠 4.2 秒，确保每分钟最多 14 次请求，彻底规避 429。
            time.sleep(4.2)
            return result

        # 谷歌免费 API (15 RPM) 极易触发 429，为了稳定性强制串行处理或降频
        max_workers = 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(process_batch, idx, batch): idx
                for idx, batch in enumerate(batches)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()

        all_embeddings = []
        for r in results:
            if r is not None:
                all_embeddings.extend(r)

        return np.array(all_embeddings, dtype=np.float32)


def get_embedder(embedder_type: str = "mock", **kwargs) -> BaseEmbedder:
    """
    工厂函数，获取指定的Embedder

    Args:
        embedder_type: "mock", "openai", "local", "lmstudio", "gemini"
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
    elif embedder_type == "gemini":
        return GoogleEmbedder(**kwargs)
    else:
        raise ValueError(f"Unknown embedder type: {embedder_type}")
