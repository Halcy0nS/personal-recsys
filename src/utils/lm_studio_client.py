"""
LM Studio LLM 客户端 - OpenAI 兼容 chat API 封装
"""

import json
import urllib.request
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatChoice:
    message: ChatMessage


@dataclass
class ChatResponse:
    choices: List[ChatChoice]


class LMStudioLLMClient:
    """
    LM Studio LLM 客户端
    实现 chat() 方法，匹配 ProfileExtractor 期望的接口
    """

    def __init__(self, base_url: str = "http://localhost:1234/v1",
                 model: str = "qwen/qwen3.5-9b",
                 temperature: float = 0.3,
                 max_tokens: int = 2000):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, messages: List[Dict]) -> ChatResponse:
        """
        调用 LM Studio chat completions API

        Args:
            messages: [{"role": "system", "content": ...}, {"role": "user", "content": ...}]

        Returns:
            ChatResponse 兼容 OpenAI 格式
        """
        url = f"{self.base_url}/chat/completions"
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        content = result["choices"][0]["message"]["content"]

        return ChatResponse(
            choices=[
                ChatChoice(
                    message=ChatMessage(
                        role="assistant",
                        content=content
                    )
                )
            ]
        )
