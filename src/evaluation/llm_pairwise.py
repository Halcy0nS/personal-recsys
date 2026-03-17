"""
LLM pairwise evaluation with order-swap analysis.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..profiling.explicit_profile import UserExplicitProfile
from ..utils.data_loader import load_zhihu_items
from ..utils.lm_studio_client import LMStudioLLMClient
from .pairwise import PairwiseEvaluationSession, PairwiseMatchup


@dataclass
class PairwiseArticle:
    article_id: str
    title: str
    summary: str
    author: str = "未知"
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class PairwiseUserProfile:
    core_topics: List[str]
    writing_style: List[str]
    negative_tags: List[str]
    exemplars: List[PairwiseArticle]


class LLMPairwiseExperiment:
    """Run A/B and B/A pairwise experiments and summarize order bias."""

    def __init__(
        self,
        llm_client: Optional[LMStudioLLMClient] = None,
        model: str = "qwen3-reranker-8b",
        base_url: str = "http://localhost:1234/v1",
        temperature: float = 0.0,
        max_tokens: int = 320,
    ):
        self.llm_client = llm_client or LMStudioLLMClient(
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def build_profile_from_cache(
        self,
        explicit_profile_path: str,
        favorites_path: str,
        exemplar_count: int = 3,
    ) -> PairwiseUserProfile:
        profile = UserExplicitProfile.load(explicit_profile_path)
        favorites = load_zhihu_items(favorites_path)[:exemplar_count]
        exemplars = [
            PairwiseArticle(
                article_id=item.get("id", ""),
                title=item.get("title", ""),
                summary=item.get("content", "")[:160],
                author=item.get("author_name", "未知"),
            )
            for item in favorites
        ]
        return PairwiseUserProfile(
            core_topics=profile.core_topics,
            writing_style=profile.writing_style,
            negative_tags=profile.negative_tags,
            exemplars=exemplars,
        )

    def _build_prompt(
        self,
        user_profile: PairwiseUserProfile,
        article_a: PairwiseArticle,
        article_b: PairwiseArticle,
    ) -> str:
        exemplar_lines = []
        for idx, exemplar in enumerate(user_profile.exemplars, 1):
            exemplar_lines.append(
                f"[{idx}] 《{exemplar.title}》\n"
                f"    摘要: {exemplar.summary[:100]}..."
            )

        return f"""请做内容收藏偏好二选一判断。

=== 用户收藏偏好示例 ===
{chr(10).join(exemplar_lines)}

=== 用户兴趣画像 ===
核心主题: {', '.join(user_profile.core_topics[:8])}
偏好风格: {', '.join(user_profile.writing_style[:5])}
负向偏好: {', '.join(user_profile.negative_tags[:5]) if user_profile.negative_tags else '无明确负向偏好'}

=== 候选文章 ===
【文章A】
标题: 《{article_a.title}》
作者: {article_a.author}
摘要: {article_a.summary[:220]}...

【文章B】
标题: 《{article_b.title}》
作者: {article_b.author}
摘要: {article_b.summary[:220]}...

=== 任务 ===
判断用户更可能收藏哪篇文章。
只能返回 A、B 或 tie。
不要输出分析过程，不要输出 <think>，不要输出 Markdown。
直接输出一行 JSON：
{{
  "preferred": "A" | "B" | "tie",
  "confidence": <0-1>,
  "reasoning": "<20字内简短理由>"
}}"""

    def _parse_response(self, response_text: str) -> Dict:
        text = response_text.strip()
        text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        if "</think>" in text:
            text = text.split("</think>")[-1].strip()

        if text.startswith("<think>") and "{" in text:
            text = text[text.find("{"):].strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)

        try:
            data = json.loads(text)
            parse_mode = "json"
        except json.JSONDecodeError:
            preferred_match = re.search(
                r'"?preferred"?\s*[:=]\s*"?(A|B|tie)"?',
                text,
                flags=re.IGNORECASE,
            )
            confidence_match = re.search(
                r'"?confidence"?\s*[:=]\s*([01](?:\.\d+)?)',
                text,
                flags=re.IGNORECASE,
            )
            reasoning_match = re.search(
                r'"?reasoning"?\s*[:=]\s*"([^"]{1,120})"',
                text,
                flags=re.IGNORECASE,
            )

            if preferred_match:
                data = {
                    "preferred": preferred_match.group(1),
                    "confidence": float(confidence_match.group(1)) if confidence_match else 0.5,
                    "reasoning": reasoning_match.group(1) if reasoning_match else "regex_rescued",
                }
                parse_mode = "regex_rescued"
            else:
                choice_match = re.search(r"\b(A|B|tie)\b", text, flags=re.IGNORECASE)
                if choice_match:
                    data = {
                        "preferred": choice_match.group(1),
                        "confidence": 0.3,
                        "reasoning": "choice_rescued",
                    }
                    parse_mode = "choice_rescued"
                else:
                    return {
                        "preferred": "tie",
                        "confidence": 0.1,
                        "reasoning": f"parse_failed: {text[:120]}",
                        "parsed_ok": False,
                        "parse_mode": "failed",
                    }

        preferred = str(data.get("preferred", "tie")).strip().upper()
        if preferred not in {"A", "B", "TIE"}:
            preferred = "TIE"

        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        return {
            "preferred": preferred,
            "confidence": max(0.0, min(1.0, confidence)),
            "reasoning": str(data.get("reasoning", ""))[:120],
            "parsed_ok": True,
            "parse_mode": parse_mode,
        }

    def _system_winner(self, preferred: str, system_a: str, system_b: str) -> str:
        if preferred == "A":
            return system_a
        if preferred == "B":
            return system_b
        return "tie"

    def _chat_pairwise(self, prompt: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个严格的排序判断器。"
                    "禁止输出思考过程、解释性前缀或 Markdown。"
                    "必须只输出一行 JSON。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        return self.llm_client.chat(messages).choices[0].message.content

    def _build_article(self, article_id: str, title: str, summary: str) -> PairwiseArticle:
        return PairwiseArticle(article_id, title, summary)

    def _build_side_result(self, order: str, parsed: Dict, system_winner: str) -> Dict:
        return {
            "order": order,
            "preferred": parsed["preferred"],
            "system_winner": system_winner,
            "confidence": parsed["confidence"],
            "reasoning": parsed["reasoning"],
            "parsed_ok": parsed["parsed_ok"],
            "parse_mode": parsed["parse_mode"],
        }

    def evaluate_articles(
        self,
        user_profile: PairwiseUserProfile,
        article_a: PairwiseArticle,
        article_b: PairwiseArticle,
        system_a: str = "left",
        system_b: str = "right",
        pair_id: str = "custom_pair",
    ) -> Dict:
        """Evaluate one article pair with both A/B and B/A orders."""
        forward_prompt = self._build_prompt(user_profile, article_a, article_b)
        forward_raw = self._chat_pairwise(forward_prompt)
        forward = self._parse_response(forward_raw)
        forward_system_winner = self._system_winner(forward["preferred"], system_a, system_b)

        reverse_prompt = self._build_prompt(user_profile, article_b, article_a)
        reverse_raw = self._chat_pairwise(reverse_prompt)
        reverse = self._parse_response(reverse_raw)
        reverse_system_winner = self._system_winner(reverse["preferred"], system_b, system_a)

        if forward_system_winner == reverse_system_winner:
            resolved_winner = forward_system_winner
        elif "tie" in {forward_system_winner, reverse_system_winner}:
            resolved_winner = forward_system_winner if reverse_system_winner == "tie" else reverse_system_winner
        else:
            resolved_winner = "unstable"

        return {
            "pair_id": pair_id,
            "left_item_id": article_a.article_id,
            "right_item_id": article_b.article_id,
            "left_title": article_a.title,
            "right_title": article_b.title,
            "forward": self._build_side_result("left_vs_right", forward, forward_system_winner),
            "reverse": self._build_side_result("right_vs_left", reverse, reverse_system_winner),
            "resolved_winner": resolved_winner,
            "order_consistent": forward_system_winner == reverse_system_winner,
            "raw_preview": {
                "forward": forward_raw[:160],
                "reverse": reverse_raw[:160],
            },
        }

    def evaluate_matchup(self, matchup: PairwiseMatchup, user_profile: PairwiseUserProfile) -> Dict:
        article_a = self._build_article(matchup.item_id_a, matchup.title_a, matchup.summary_a)
        article_b = self._build_article(matchup.item_id_b, matchup.title_b, matchup.summary_b)
        result = self.evaluate_articles(
            user_profile=user_profile,
            article_a=article_a,
            article_b=article_b,
            system_a=matchup.system_a,
            system_b=matchup.system_b,
            pair_id=matchup.pair_id,
        )

        return {
            "pair_id": result["pair_id"],
            "baseline_item_id": matchup.item_id_a,
            "rerank_item_id": matchup.item_id_b,
            "baseline_title": matchup.title_a,
            "rerank_title": matchup.title_b,
            "forward": {
                **result["forward"],
                "order": "baseline_vs_rerank",
            },
            "reverse": {
                **result["reverse"],
                "order": "rerank_vs_baseline",
            },
            "resolved_winner": result["resolved_winner"],
            "order_consistent": result["order_consistent"],
            "raw_preview": result["raw_preview"],
        }

    def summarize_results(self, results: List[Dict]) -> Dict:
        summary = {
            "total_pairs": len(results),
            "order_consistent_pairs": 0,
            "order_inconsistent_pairs": 0,
            "order_flip_rate": 0.0,
            "forward_baseline_wins": 0,
            "forward_rerank_wins": 0,
            "forward_ties": 0,
            "forward_parse_failures": 0,
            "reverse_baseline_wins": 0,
            "reverse_rerank_wins": 0,
            "reverse_ties": 0,
            "reverse_parse_failures": 0,
            "resolved_baseline_wins": 0,
            "resolved_rerank_wins": 0,
            "resolved_ties": 0,
            "resolved_unstable": 0,
            "updated_at": datetime.now().isoformat(),
        }

        for result in results:
            if result["order_consistent"]:
                summary["order_consistent_pairs"] += 1
            else:
                summary["order_inconsistent_pairs"] += 1

            forward_winner = result["forward"]["system_winner"]
            if forward_winner == "baseline":
                summary["forward_baseline_wins"] += 1
            elif forward_winner == "rerank":
                summary["forward_rerank_wins"] += 1
            else:
                summary["forward_ties"] += 1
            if not result["forward"]["parsed_ok"]:
                summary["forward_parse_failures"] += 1

            reverse_winner = result["reverse"]["system_winner"]
            if reverse_winner == "baseline":
                summary["reverse_baseline_wins"] += 1
            elif reverse_winner == "rerank":
                summary["reverse_rerank_wins"] += 1
            else:
                summary["reverse_ties"] += 1
            if not result["reverse"]["parsed_ok"]:
                summary["reverse_parse_failures"] += 1

            winner = result["resolved_winner"]
            if winner == "baseline":
                summary["resolved_baseline_wins"] += 1
            elif winner == "rerank":
                summary["resolved_rerank_wins"] += 1
            elif winner == "tie":
                summary["resolved_ties"] += 1
            else:
                summary["resolved_unstable"] += 1

        if results:
            summary["order_flip_rate"] = round(
                summary["order_inconsistent_pairs"] / len(results),
                4,
            )

        decisive = summary["resolved_baseline_wins"] + summary["resolved_rerank_wins"]
        summary["rerank_win_rate"] = round(summary["resolved_rerank_wins"] / decisive, 4) if decisive else None

        if summary["resolved_rerank_wins"] > summary["resolved_baseline_wins"]:
            conclusion = "Pairwise LLM experiment currently favors rerank"
        elif summary["resolved_baseline_wins"] > summary["resolved_rerank_wins"]:
            conclusion = "Pairwise LLM experiment currently favors baseline"
        else:
            conclusion = "Pairwise LLM experiment is tied between baseline and rerank"

        summary["conclusion"] = conclusion
        return summary

    def run(
        self,
        cache_dir: str,
        explicit_profile_path: str,
        favorites_path: str,
        strategy: str = "rank_aligned",
        skip_same_item: bool = True,
        max_pairs: Optional[int] = None,
        verbose: bool = False,
    ) -> Dict:
        session = PairwiseEvaluationSession(cache_dir)
        matchups = session.load_matchups_by_strategy(strategy=strategy, skip_same_item=skip_same_item)
        if max_pairs is not None:
            matchups = matchups[:max_pairs]
        user_profile = self.build_profile_from_cache(explicit_profile_path, favorites_path)
        results = []
        total = len(matchups)

        for idx, matchup in enumerate(matchups, 1):
            if verbose:
                print(
                    f"[{idx}/{total}] {matchup.title_a[:28]}  <vs>  {matchup.title_b[:28]}",
                    flush=True,
                )
            results.append(self.evaluate_matchup(matchup, user_profile))

        summary = self.summarize_results(results)
        return {
            "strategy": strategy,
            "pair_count": len(matchups),
            "results": results,
            "summary": summary,
        }
