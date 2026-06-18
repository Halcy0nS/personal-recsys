"""
LM Studio LLM 客户端 - OpenAI 兼容 chat API 封装
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ChatMessage:
    role: str
    content: str
    reasoning_content: str = ""


@dataclass
class ChatChoice:
    message: ChatMessage


@dataclass
class ChatResponse:
    choices: List[ChatChoice]
    usage: Optional[Dict[str, Any]] = None
    raw_response: Optional[Dict[str, Any]] = None


class LMStudioLLMClient:
    """
    LM Studio LLM 客户端
    实现 chat() 方法，匹配 ProfileExtractor 期望的接口
    """

    def __init__(self, base_url: str = "http://localhost:1234/v1",
                 model: str = "qwen/qwen3.5-9b",
                 temperature: float = 0.3,
                 max_tokens: int = 2000,
                 api_key: Optional[str] = None,
                 extra_body: Optional[Dict[str, Any]] = None,
                 timeout: int = 300,
                 max_retries: int = 3,
                 retry_backoff_seconds: float = 1.5):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.extra_body = dict(extra_body or {})
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    def chat(
        self,
        messages: List[Dict],
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        """
        调用 LLM chat completions API (支持 OpenAI 协议与 Anthropic 协议自适应)

        Args:
            messages: [{"role": "system", "content": ...}, {"role": "user", "content": ...}]

        Returns:
            ChatResponse 兼容 OpenAI 格式
        """
        is_anthropic = "anthropic" in self.base_url.lower() or "claude" in self.model.lower()

        if is_anthropic:
            system_content = None
            user_messages = []
            for msg in messages:
                if msg.get("role") == "system":
                    system_content = msg.get("content")
                else:
                    user_messages.append({
                        "role": msg.get("role"),
                        "content": msg.get("content")
                    })
            url = f"{self.base_url}/v1/messages"
            payload_dict = {
                "model": self.model,
                "messages": user_messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            if system_content:
                payload_dict["system"] = system_content
            
            payload_dict.update(self.extra_body)
            if extra_body:
                payload_dict.update(extra_body)
            payload = json.dumps(payload_dict).encode("utf-8")

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
        else:
            url = f"{self.base_url}/chat/completions"
            payload_dict: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            payload_dict.update(self.extra_body)
            if extra_body:
                payload_dict.update(extra_body)
            payload = json.dumps(payload_dict).encode("utf-8")

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(
                url,
                data=payload,
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {408, 409, 429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise

            sleep_s = self.retry_backoff_seconds * attempt
            if sleep_s > 0:
                time.sleep(sleep_s)
        else:
            raise last_error or RuntimeError("chat request failed without explicit error")

        if is_anthropic:
            content_blocks = result.get("content", [])
            content = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    content += block.get("text", "")
            reasoning_content = ""
        else:
            message = result["choices"][0]["message"]
            content = message.get("content", "")
            reasoning_content = message.get("reasoning_content", "")

        return ChatResponse(
            choices=[
                ChatChoice(
                    message=ChatMessage(
                        role="assistant",
                        content=content,
                        reasoning_content=reasoning_content,
                    )
                )
            ],
            usage=result.get("usage"),
            raw_response=result,
        )
