import urllib.request
import urllib.error
import json
import time
import logging
from typing import Dict, List, Optional
import concurrent.futures

logger = logging.getLogger(__name__)

class DeepSeekClient:
    """
    极速官方 DeepSeek 客户端。
    采用标准的 urllib，无外部依赖。
    支持并发调用。
    """
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.1, max_tokens: int = 1000) -> Optional[str]:
        """单次调用，返回 content 文本"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, headers=self.headers)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
                result = json.loads(body)
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            logger.error("DeepSeek API HTTPError %d: %s", e.code, e.read().decode("utf-8"))
        except Exception as e:
            logger.error("DeepSeek API Exception: %s", e)
        return None

    def chat_json(self, messages: List[Dict[str, str]], temperature: float = 0.1) -> Optional[Dict]:
        """请求返回 JSON 对象 (如果模型支持 JSON mode，或者只依靠 prompt 约束)"""
        # Note: DeepSeek API supports response_format={"type": "json_object"}
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"}
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, headers=self.headers)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            logger.error("DeepSeek API JSON Parse Exception: %s", e)
        return None

    def extract_profile(self, prompt: str) -> Optional[Dict]:
        """提取知识胶囊"""
        messages = [
            {"role": "system", "content": "你是一个专业的用户画像分析师。请严格按照要求返回JSON格式的结果。"},
            {"role": "user", "content": prompt}
        ]
        return self.chat_json(messages)

    def _generate_reason_for_item(self, profile_summary: str, item_title: str, item_content: str) -> str:
        prompt = f"""
请根据以下“用户画像总结”，为推荐的这篇文章写一句简短、吸引人的“推荐理由”（控制在30个字以内，不要多余的废话，不要包含换行符）。

=== 用户画像总结 ===
{profile_summary}

=== 推荐文章 ===
标题: 《{item_title}》
摘要: {item_content[:200]}...

请直接输出这句推荐理由，不需要额外的问候语或说明：
"""
        messages = [{"role": "user", "content": prompt}]
        res = self.chat(messages, temperature=0.3, max_tokens=100)
        return res.strip() if res else "基于您的综合兴趣匹配。"

    def generate_reasons_batch(self, profile_summary: str, items: List[Dict]) -> Dict[str, str]:
        """
        高并发为多个候选项生成推荐理由
        Args:
            profile_summary: 画像总结字符串
            items: 字典列表，包含 'item_id', 'title', 'content'
        Returns:
            Dict: {item_id: reasoning_string}
        """
        results = {}
        if not items:
            return results

        t0 = time.time()
        logger.info("DeepSeek batch reasoning for %d items...", len(items))

        def _worker(item):
            reason = self._generate_reason_for_item(profile_summary, item.get('title', ''), item.get('content', ''))
            return item['item_id'], reason

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(items), 20)) as executor:
            futures = [executor.submit(_worker, item) for item in items]
            for future in concurrent.futures.as_completed(futures):
                try:
                    item_id, reason = future.result()
                    results[item_id] = reason
                except Exception as e:
                    logger.error("Error generating reason: %s", e)

        logger.info("DeepSeek batch reasoning completed in %.2fs", time.time() - t0)
        return results

