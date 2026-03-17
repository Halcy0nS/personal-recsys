"""
Interactive pairwise evaluation for baseline vs rerank blind comparison.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.evaluation.pairwise import PairwiseDecision, PairwiseEvaluationSession


CACHE_DIR = "./data/real_data_cache"
PAIRWISE_STRATEGY = "cross_system_full"


def prompt_choice() -> str:
    while True:
        choice = input("选择更想收藏的文章 [A/B/T/Q]: ").strip().upper()
        if choice in {"A", "B", "T", "Q"}:
            return choice
        print("请输入 A / B / T / Q。")


def main():
    session = PairwiseEvaluationSession(CACHE_DIR)
    matchups = session.load_matchups_by_strategy(
        strategy=PAIRWISE_STRATEGY,
        skip_same_item=True,
    )
    existing = {item["pair_id"] for item in session.load_decisions()}

    print("=" * 70)
    print("Pairwise Evaluation")
    print("=" * 70)
    print(f"缓存目录: {Path(CACHE_DIR).resolve()}")
    print(f"对局策略: {PAIRWISE_STRATEGY}")
    print(f"可评测对局数: {len(matchups)}")
    print(f"已完成对局数: {len(existing)}")

    for matchup in matchups:
        if matchup.pair_id in existing:
            continue

        print("\n" + "-" * 70)
        print(f"对局: {matchup.pair_id}")
        print(f"[A] {matchup.title_a}")
        if matchup.summary_a:
            print(f"    摘要: {matchup.summary_a}")
        print(f"    URL: {matchup.url_a}")
        print(f"[B] {matchup.title_b}")
        if matchup.summary_b:
            print(f"    摘要: {matchup.summary_b}")
        print(f"    URL: {matchup.url_b}")

        choice = prompt_choice()
        if choice == "Q":
            print("已退出，本轮结果已保存。")
            break

        note = input("备注（可留空）: ").strip()
        winning_system = "tie"
        if choice == "A":
            winning_system = matchup.system_a
        elif choice == "B":
            winning_system = matchup.system_b

        decision = PairwiseDecision(
            comparison_id=matchup.comparison_id,
            pair_id=matchup.pair_id,
            blind_id_a=matchup.blind_id_a,
            blind_id_b=matchup.blind_id_b,
            winner=choice if choice in {"A", "B"} else "tie",
            winning_system=winning_system,
            note=note,
            created_at=datetime.now().isoformat(),
        )
        session.save_decision(decision)
        existing.add(matchup.pair_id)

        report = session.build_report()
        ratings = session.summarize_rankings(top_n=5)
        print(f"当前统计: baseline={report['baseline_wins']} rerank={report['rerank_wins']} tie={report['ties']}")
        print(f"当前结论: {report['conclusion']}")
        if ratings["top_items"]:
            print("当前 Glicko2 Top-5:")
            for blind_id, rating in ratings["top_items"]:
                print(f"  {blind_id}: {rating}")

    final_report = session.build_report()
    session.build_glicko_ratings()
    print("\n" + "=" * 70)
    print("评测完成")
    print("=" * 70)
    print(f"pairwise 决策文件: {session.decisions_path}")
    print(f"pairwise 报告文件: {session.report_path}")
    print(f"Glicko2 评分文件: {session.glicko_path}")
    print(f"当前结论: {final_report['conclusion']}")


if __name__ == "__main__":
    main()
