"""
基于显式标签的匹配算法
规则驱动的硬过滤 + 加权评分
"""

from typing import List, Dict, Optional, Set
from dataclasses import dataclass
import re


@dataclass
class TagMatchResult:
    """标签匹配结果"""
    item_id: str
    tag_score: float
    matched_positive: List[str]  # 匹配到的正向标签
    matched_negative: List[str]  # 匹配到的负向标签
    is_filtered: bool  # 是否被硬规则过滤


class TagMatcher:
    """
    显式标签匹配器
    基于规则的白盒匹配，支持硬过滤和加权评分
    """

    def __init__(self,
                 positive_weight: float = 1.0,
                 negative_weight: float = -2.0,
                 hard_filter_negative: bool = True,
                 case_sensitive: bool = False):
        """
        Args:
            positive_weight: 正向标签匹配的基础权重
            negative_weight: 负向标签匹配的权重（通常为负）
            hard_filter_negative: 是否对负向标签进行硬过滤
            case_sensitive: 标签匹配是否区分大小写
        """
        self.positive_weight = positive_weight
        self.negative_weight = negative_weight
        self.hard_filter_negative = hard_filter_negative
        self.case_sensitive = case_sensitive
        # Precompile regex for massive performance gain
        self._word_pattern = re.compile(r'\b[\u4e00-\u9fa5a-zA-Z]{2,}\b')

    def _normalize_tag(self, tag: str) -> str:
        """标签标准化"""
        normalized = tag.strip()
        if not self.case_sensitive:
            normalized = normalized.lower()
        return normalized

    def _extract_tags_from_text(self, text: str) -> Set[str]:
        """从文本中提取标签（简单实现，可扩展为更复杂的NER）"""
        # 简单分词去重
        words = self._word_pattern.findall(text)
        return set(w if self.case_sensitive else w.lower() for w in words)

    def _match_tags(self, item_tags: List[str],
                   profile_tags: List[str],
                   profile_tags_norm: Optional[List[str]] = None) -> tuple:
        """
        匹配两组标签，返回匹配的详细结果

        Returns:
            (matched_tags, match_details)
        """
        # 标准化
        item_tags_norm = {self._normalize_tag(t): t for t in item_tags}
        if profile_tags_norm is None:
            profile_tags_norm = [self._normalize_tag(t) for t in profile_tags]

        matched = []
        match_details = {}

        for p_tag in profile_tags_norm:
            if p_tag in item_tags_norm:
                original_tag = item_tags_norm[p_tag]
                matched.append(original_tag)
                match_details[original_tag] = {
                    "matched_with": p_tag,
                    "match_type": "exact"
                }

        return matched, match_details

    def match(self, item_id: str,
              item_tags: List[str],
              item_title: str = "",
              item_content: str = "",
              user_profile: "UserExplicitProfile" = None,
              pos_tags_norm: Optional[List[str]] = None,
              neg_tags_norm: Optional[List[str]] = None) -> TagMatchResult:
        """
        匹配单个内容与用户画像

        Args:
            item_id: 内容ID
            item_tags: 内容的显式标签
            item_title: 内容标题（用于提取隐式标签）
            item_content: 内容正文（用于提取隐式标签）
            user_profile: 用户的显式画像
            pos_tags_norm: 预处理后的正向标签
            neg_tags_norm: 预处理后的负向标签

        Returns:
            TagMatchResult: 匹配结果
        """
        if user_profile is None:
            return TagMatchResult(
                item_id=item_id,
                tag_score=0.0,
                matched_positive=[],
                matched_negative=[],
                is_filtered=False
            )

        # 合并显式和隐式标签
        all_item_tags = set(item_tags)

        # 从标题和内容提取额外标签
        if item_title:
            all_item_tags.update(self._extract_tags_from_text(item_title))
        if item_content:
            all_item_tags.update(self._extract_tags_from_text(item_content))

        all_item_tags = list(all_item_tags)

        # 匹配正向标签
        matched_positive, _ = self._match_tags(
            all_item_tags,
            user_profile.core_topics,
            pos_tags_norm
        )

        # 匹配负向标签
        matched_negative, _ = self._match_tags(
            all_item_tags,
            user_profile.negative_tags,
            neg_tags_norm
        )

        # 硬过滤
        is_filtered = False
        if self.hard_filter_negative and matched_negative:
            is_filtered = True

        # 计算分数
        if is_filtered:
            tag_score = 0.0
        else:
            pos_score = len(matched_positive) * self.positive_weight
            neg_score = len(matched_negative) * self.negative_weight
            tag_score = max(0.0, pos_score + neg_score)

        return TagMatchResult(
            item_id=item_id,
            tag_score=tag_score,
            matched_positive=matched_positive,
            matched_negative=matched_negative,
            is_filtered=is_filtered
        )

    def match_batch(self, items: List[Dict],
                   user_profile: "UserExplicitProfile") -> List[TagMatchResult]:
        """
        批量匹配

        Args:
            items: 内容列表，每项包含id, tags, title, content
            user_profile: 用户显式画像

        Returns:
            List[TagMatchResult]: 匹配结果列表
        """
        results = []
        if user_profile:
            pos_tags_norm = [self._normalize_tag(t) for t in user_profile.core_topics]
            neg_tags_norm = [self._normalize_tag(t) for t in user_profile.negative_tags]
        else:
            pos_tags_norm = []
            neg_tags_norm = []

        for item in items:
            result = self.match(
                item_id=item.get("id", ""),
                item_tags=item.get("tags", []),
                item_title=item.get("title", ""),
                item_content=item.get("content", ""),
                user_profile=user_profile,
                pos_tags_norm=pos_tags_norm,
                neg_tags_norm=neg_tags_norm
            )
            results.append(result)
        return results
