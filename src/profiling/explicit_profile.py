"""
显式画像 - LLM提取标签树
白盒可控的用户画像，支持手动编辑
"""

import json
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class UserExplicitProfile:
    """用户显式画像数据结构"""
    core_topics: List[str]          # 核心关注主题
    writing_style: List[str]        # 偏好写作风格
    content_depth: List[str]        # 内容深度偏好
    negative_tags: List[str]        # 负面/排除标签
    authors: List[str]             # 关注的作者
    custom_tags: Dict[str, List[str]]  # 自定义标签类别

    # 元数据
    created_at: str = None
    updated_at: str = None
    version: str = "1.0"

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def save(self, path: str):
        """保存到文件"""
        self.updated_at = datetime.now().isoformat()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: Dict) -> "UserExplicitProfile":
        """从字典创建"""
        # 过滤掉类中不存在的字段
        valid_fields = cls.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    @classmethod
    def load(cls, path: str) -> "UserExplicitProfile":
        """从文件加载"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)


class ProfileExtractor:
    """
    从收藏夹内容提取显式画像
    使用LLM进行标签提取
    """

    # 默认的系统提示词模板
    DEFAULT_SYSTEM_PROMPT = """你是一个用户兴趣分析专家。你的任务是从用户的收藏夹内容中提取用户的显式兴趣画像。

请仔细分析用户收藏的文章/回答，提取以下信息：
1. core_topics: 核心关注的主题（如"认知心理学", "分布式架构"）
2. writing_style: 偏好的写作风格（如"数据驱动", "深度长文"）
3. content_depth: 内容深度偏好（如"入门科普", "技术细节"）
4. negative_tags: 排斥的标签（如"情绪输出", "软广"）
5. authors: 关注的作者（如果有）

输出必须是严格的JSON格式，不要包含任何其他文字。"""

    def __init__(self, llm_client=None, system_prompt: str = None):
        """
        初始化提取器

        Args:
            llm_client: LLM客户端，需要实现 `complete()` 或 `chat()` 方法
            system_prompt: 自定义系统提示词
        """
        self.llm_client = llm_client
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

    def extract(self, collection_items: List[Dict],
                max_items: int = 50,
                sample_strategy: str = "diverse") -> UserExplicitProfile:
        """
        从收藏夹提取用户画像

        Args:
            collection_items: 收藏项列表，每项包含title, content, url等
            max_items: 最大处理数量
            sample_strategy: 采样策略 (diverse/random/recent)

        Returns:
            UserExplicitProfile: 提取的用户显式画像
        """
        # 采样
        sampled = self._sample_items(collection_items, max_items, sample_strategy)

        # 构建prompt
        prompt = self._build_prompt(sampled)

        # 调用LLM
        response = self._call_llm(prompt)

        # 解析结果
        profile_data = self._parse_response(response)

        # 创建画像对象
        profile = UserExplicitProfile(
            core_topics=profile_data.get("core_topics", []),
            writing_style=profile_data.get("writing_style", []),
            content_depth=profile_data.get("content_depth", []),
            negative_tags=profile_data.get("negative_tags", []),
            authors=profile_data.get("authors", []),
            custom_tags=profile_data.get("custom_tags", {}),
            version="1.0"
        )

        return profile

    def _sample_items(self, items: List[Dict], max_items: int,
                     strategy: str) -> List[Dict]:
        """采样收藏项"""
        if len(items) <= max_items:
            return items

        if strategy == "random":
            import random
            return random.sample(items, max_items)
        elif strategy == "recent":
            # 假设有timestamp字段
            sorted_items = sorted(items,
                                key=lambda x: x.get("timestamp", ""),
                                reverse=True)
            return sorted_items[:max_items]
        else:  # diverse - 简单的聚类采样
            # 简化为随机采样，实际可用KMeans对embedding聚类
            import random
            return random.sample(items, max_items)

    def _build_prompt(self, items: List[Dict]) -> str:
        """构建LLM提示词"""
        content_parts = []
        for i, item in enumerate(items[:30], 1):  # 限制token数
            title = item.get("title", "")
            content = item.get("content", "")[:500]  # 截断
            content_parts.append(f"[{i}] {title}\n{content}\n---")

        content_text = "\n".join(content_parts)

        prompt = f"""请分析以下用户收藏的文章/回答，提取用户的兴趣画像：

{content_text}

请提取以下信息并以JSON格式输出：
{{
  "core_topics": ["主题1", "主题2"],
  "writing_style": ["风格1", "风格2"],
  "content_depth": ["深度1"],
  "negative_tags": ["负面标签1"],
  "authors": ["作者名"]
}}"""
        return prompt

    def _call_llm(self, prompt: str) -> str:
        """调用LLM"""
        if self.llm_client is None:
            # 返回示例数据用于测试
            return self._mock_response()

        # 实际调用LLM
        try:
            if hasattr(self.llm_client, 'chat'):
                response = self.llm_client.chat(
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.choices[0].message.content
            elif hasattr(self.llm_client, 'complete'):
                response = self.llm_client.complete(prompt=prompt, system=self.system_prompt)
                return response
            else:
                raise ValueError("LLM client must have 'chat' or 'complete' method")
        except Exception as e:
            print(f"LLM call failed: {e}")
            return self._mock_response()

    def _mock_response(self) -> str:
        """测试用mock数据"""
        return '''{
  "core_topics": ["认知心理学", "分布式系统", "个人效率"],
  "writing_style": ["深度长文", "逻辑严密", "案例丰富"],
  "content_depth": ["专业级", "技术细节"],
  "negative_tags": ["情绪输出", "标题党", "软广"],
  "authors": []
}'''

    def _parse_response(self, response: str) -> Dict:
        """解析LLM响应"""
        # 提取JSON部分
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取 ```json ``` 中的内容
            import re
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            # 尝试提取 {...}
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass

            print(f"Failed to parse response: {response[:500]}")
            return {}
