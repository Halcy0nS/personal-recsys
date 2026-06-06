"""
Personal RecSys 使用示例
展示完整的三层推荐流程
"""

from src.engine import PersonalRecSys, CandidateItem
from src.profiling.explicit_profile import UserExplicitProfile
from src.utils.embeddings import get_embedder


def demo_basic_flow():
    """演示基本使用流程"""

    print("=" * 60)
    print("Personal RecSys - 基础使用示例")
    print("=" * 60)

    # 1. 初始化引擎
    print("\n[1] 初始化推荐引擎...")
    recsys = PersonalRecSys(
        embedder=get_embedder("mock", dim=128),  # 使用mock embedding
        embedding_dim=128,
        cache_dir="./demo_cache"
    )

    # 2. 准备模拟的收藏夹数据
    print("\n[2] 构建用户画像...")
    collection_items = [
        {
            "title": "深入理解Transformer架构",
            "content": "Transformer已经成为现代NLP的基础架构。本文深入剖析self-attention机制...",
            "url": "https://example.com/transformer",
            "source": "tech_blog"
        },
        {
            "title": "认知心理学：如何有效学习",
            "content": "间隔重复、主动回忆等认知科学原理如何帮助我们更高效地学习新知识...",
            "url": "https://example.com/learning",
            "source": "psychology"
        },
        {
            "title": "FIRE运动实践指南",
            "content": "财务独立、提前退休的实践方法。储蓄率、投资组合配置详解...",
            "url": "https://example.com/fire",
            "source": "finance"
        },
        {
            "title": "分布式系统一致性算法",
            "content": "Raft和Paxos算法的深入比较，以及在生产环境中的应用实践...",
            "url": "https://example.com/consensus",
            "source": "tech_blog"
        }
    ]

    # 构建画像（不使用LLM，使用模拟数据）
    recsys.build_profile_from_collection(
        collection_items,
        llm_client=None,  # 不使用LLM，用模拟数据
        max_items=50
    )

    # 手动设置显式画像（演示用）
    recsys.explicit_profile = UserExplicitProfile(
        core_topics=["机器学习", "分布式系统", "认知心理学", "FIRE运动", "系统设计"],
        writing_style=["深度长文", "逻辑严密", "数据驱动", "案例丰富"],
        content_depth=["技术细节", "实践指南"],
        negative_tags=["情绪输出", "标题党", "软广", "抖机灵"],
        authors=[],
        custom_tags={}
    )

    print(f"  - 向量云: {len(recsys.vector_cloud.vectors)} 个向量")
    print(f"  - 核心标签: {recsys.explicit_profile.core_topics}")

    # 3. 添加候选内容
    print("\n[3] 加载候选内容池...")
    candidate_items = [
        CandidateItem(
            item_id="cand_001",
            title="深入理解神经网络反向传播",
            content="本文详细推导反向传播算法，并通过代码示例展示如何实现...",
            tags=["机器学习", "深度学习", "技术细节"],
            metadata={"likes": 1500, "author": "tech_expert"}
        ),
        CandidateItem(
            item_id="cand_002",
            title="为什么我决定不买房？理性分析",
            content="从投资回报率、流动性、机会成本等角度分析购房决策...",
            tags=["FIRE运动", "投资理财", "理性分析"],
            metadata={"likes": 2300, "author": "fire_follower"}
        ),
        CandidateItem(
            item_id="cand_003",
            title="Kubernetes入门教程",
            content="K8s基础概念、架构介绍和简单的部署示例...",
            tags=["分布式系统", "云原生", "入门教程"],
            metadata={"likes": 800, "author": "cloud_guru"}
        ),
        CandidateItem(
            item_id="cand_004",
            title="这个Python技巧让我震惊了！",
            content="一个不为人知的Python语法糖，让你的代码更Pythonic...",
            tags=["Python", "编程技巧"],
            metadata={"likes": 5000, "author": "clickbait_master"}
        ),
        CandidateItem(
            item_id="cand_005",
            title="如何建立个人知识管理系统？",
            content="基于Zettelkasten方法的知识管理实践，包括工具选择和流程设计...",
            tags=["认知心理学", "知识管理", "个人效率"],
            metadata={"likes": 1800, "author": "productivity_guru"}
        ),
        CandidateItem(
            item_id="cand_006",
            title="微服务架构设计模式",
            content="深入讲解Saga模式、CQRS、Event Sourcing等微服务设计模式...",
            tags=["分布式系统", "微服务", "系统设计"],
            metadata={"likes": 2100, "author": "architect_expert"}
        ),
    ]

    recsys.add_candidates(candidate_items)
    recsys.embed_candidates()

    print(f"  - 候选内容数: {len(recsys.candidates)}")

    # 4. 生成推荐
    print("\n[4] 生成推荐 (使用 balanced 模式)...")
    results = recsys.recommend(
        top_k=10,
        preset="balanced"
    )

    print(f"\n推荐耗时:")
    for stage, elapsed in results.timing.items():
        print(f"  - {stage}: {elapsed:.3f}s")

    print(f"\n画像摘要:")
    for key, val in results.profile_summary.items():
        if isinstance(val, list):
            print(f"  - {key}: {val[:5]}...")
        else:
            print(f"  - {key}: {val}")

    print(f"\n推荐结果:")
    print("-" * 60)
    for item in results.ranked_items[:5]:
        print(f"\n[排名 {item.rank}] 分数: {item.final_score:.3f}")
        print(f"  ID: {item.item_id}")
        print(f"  各维度分数: {item.component_scores}")
        if "title" in item.metadata:
            print(f"  标题: {item.metadata['title']}")

    return results


def demo_profile_editing():
    """演示如何手动编辑画像"""
    print("\n" + "=" * 60)
    print("演示：手动编辑显式画像")
    print("=" * 60)

    # 创建引擎
    recsys = PersonalRecSys(
        embedder=get_embedder("mock", dim=128),
        embedding_dim=128
    )

    # 设置一个基础画像
    recsys.explicit_profile = UserExplicitProfile(
        core_topics=["机器学习", "分布式系统"],
        writing_style=["深度长文", "数据驱动"],
        content_depth=["技术细节"],
        negative_tags=["情绪输出", "标题党"],
        authors=[],
        custom_tags={}
    )

    print("\n原始画像:")
    print(f"  核心主题: {recsys.explicit_profile.core_topics}")
    print(f"  负面标签: {recsys.explicit_profile.negative_tags}")

    # 手动编辑 - 添加新兴趣
    print("\n手动编辑画像...")
    recsys.explicit_profile.core_topics.append("认知心理学")
    recsys.explicit_profile.core_topics.append("FIRE运动")

    # 添加新的负面标签
    recsys.explicit_profile.negative_tags.append("软广")
    recsys.explicit_profile.negative_tags.append("抖机灵")

    # 更新时间戳
    from datetime import datetime
    recsys.explicit_profile.updated_at = datetime.now().isoformat()

    print("\n更新后的画像:")
    print(f"  核心主题: {recsys.explicit_profile.core_topics}")
    print(f"  负面标签: {recsys.explicit_profile.negative_tags}")

    # 保存到文件
    profile_path = "./demo_profile.json"
    recsys.explicit_profile.save(profile_path)
    print(f"\n画像已保存到: {profile_path}")

    # 重新加载验证
    loaded_profile = UserExplicitProfile.load(profile_path)
    print(f"加载验证 - 核心主题数: {len(loaded_profile.core_topics)}")


def main():
    demo_basic_flow()
    demo_profile_editing()

    print("\n" + "=" * 60)
    print("所有演示完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
