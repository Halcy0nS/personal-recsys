# 个人推荐系统评估指南（无反馈场景）

## 一、人工评估协议（推荐）

### A/B 对比测试
```python
# 对同一批候选内容，用两种算法分别生成推荐
# 自己作为唯一评估者，进行盲测

import random
from dataclasses import dataclass
from typing import List, Dict
import json
from datetime import datetime

@dataclass
class ComparisonResult:
    """对比评估结果"""
    candidate_id: str
    title: str
    method_a_score: float  # 传统算法分数
    method_b_score: float  # RAG算法分数
    winner: str  # 'A', 'B', 或 'tie'
    reason: str  # 为什么选择这个
    timestamp: str

class RecommendationComparator:
    """推荐系统对比评估器"""

    def __init__(self, save_path: str = "./eval_results.json"):
        self.save_path = save_path
        self.history = self._load_history()

    def _load_history(self) -> List[Dict]:
        """加载历史评估数据"""
        try:
            with open(self.save_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def _save_history(self):
        """保存评估历史"""
        with open(self.save_path, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def present_pairwise_comparison(
        self,
        candidates: List[Dict],
        method_a_results: List[Dict],  # 传统算法推荐
        method_b_results: List[Dict]  # RAG算法推荐
    ) -> List[ComparisonResult]:
        """
        呈现成对比较，让用户（你）选择哪个推荐更好

        使用方法:
        1. 取两个算法各自推荐的前10篇文章
        2. 混合在一起，但隐藏来源（盲测）
        3. 你阅读后，判断哪组更符合你的兴趣
        4. 记录结果
        """
        results = []

        # 创建带标记的候选列表
        labeled_a = [(r, 'A') for r in method_a_results[:10]]
        labeled_b = [(r, 'B') for r in method_b_results[:10]]

        # 混合并打乱（模拟盲测）
        combined = labeled_a + labeled_b
        random.shuffle(combined)

        print(f"\n{'='*60}")
        print("推荐对比评估")
        print("="*60)
        print(f"\n共 {len(combined)} 篇候选文章（已打乱顺序）\n")

        # 展示给用户（你）进行评估
        for i, (item, source) in enumerate(combined[:15], 1):
            print(f"[{i}] {item['title']}")
            print(f"    标签: {', '.join(item.get('tags', [])[:3])}")
            print(f"    分数: {item.get('final_score', 0):.3f}")
            print()

        # 实际使用时，这里需要交互式输入
        # 为演示，记录一个模拟的评估
        result = ComparisonResult(
            candidate_id=f"comparison_{datetime.now().isoformat()}",
            title="Batch Comparison",
            method_a_score=0.75,
            method_b_score=0.85,
            winner="B",
            reason="RAG推荐的文章更符合我的兴趣分布",
            timestamp=datetime.now().isoformat()
        )

        results.append(result)
        self.history.append(result.__dict__)
        self._save_history()

        return results

    def generate_report(self, n_comparisons: int = 10) -> Dict:
        """生成评估报告"""
        recent = self.history[-n_comparisons:]

        if not recent:
            return {"message": "No evaluation data available"}

        wins_a = sum(1 for r in recent if r['winner'] == 'A')
        wins_b = sum(1 for r in recent if r['winner'] == 'B')
        ties = sum(1 for r in recent if r['winner'] == 'tie')

        avg_score_a = sum(r['method_a_score'] for r in recent) / len(recent)
        avg_score_b = sum(r['method_b_score'] for r in recent) / len(recent)

        return {
            "total_comparisons": len(recent),
            "wins_traditional (A)": wins_a,
            "wins_rag (B)": wins_b,
            "ties": ties,
            "avg_score_traditional": round(avg_score_a, 3),
            "avg_score_rag": round(avg_score_b, 3),
            "conclusion": "RAG better" if wins_b > wins_a else "Traditional better" if wins_a > wins_b else "Equivalent"
        }


# 使用示例
if __name__ == "__main__":
    comparator = RecommendationComparator()

    # 模拟两组推荐结果
    mock_candidates = [
        {"title": f"文章{i}", "tags": ["技术", "AI"], "final_score": 0.9 - i*0.05}
        for i in range(20)
    ]

    traditional_results = mock_candidates[:10]
    rag_results = mock_candidates[5:15]  # 部分重叠，模拟不同排序

    # 进行对比评估（实际使用时需要交互式输入）
    # results = comparator.present_pairwise_comparison(
    #     mock_candidates,
    #     traditional_results,
    #     rag_results
    # )

    # 生成报告
    report = comparator.generate_report()
    print("\n评估报告:")
    print(report)
