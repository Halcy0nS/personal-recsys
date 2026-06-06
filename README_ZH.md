# Personal RecSys

[English](README.md)

Personal RecSys 是一个本地运行、可解释的 Python 内容推荐核心。当前仓库中真正可运行的推荐主链路位于 `src/`：它会从用户收藏构建画像，用向量相似度和标签规则给候选内容打分，并输出带阶段耗时的加权排序结果。

## 项目范围

当前仓库已实现：

- 通过 `src.engine.PersonalRecSys` 暴露公开推荐 API
- 基于多向量 `VectorCloud` 的隐式画像
- 基于 `UserExplicitProfile` 与 `ProfileExtractor` 的可选显式画像
- 基于向量相似度与标签规则的召回打分
- 基于归一化加权融合与预设策略的排序
- 面向 LM Studio 的 embedding / LLM 辅助能力
- `example_usage.py` 与 `run_real_data.py` 两个脚本化演示（标准入口位于 `scripts/demo/`，顶层文件保留兼容包装）

当前代码库未实现：

- 桌面 GUI
- 打包或安装器流程
- Python 进程之外的服务编排
- 自动把爬虫模块接入主推荐链路

以上边界来自当前源码树与导入关系，而不是历史文档描述。

## 架构概览

当前主运行流程是：

1. `src.engine.PersonalRecSys` 持有状态并暴露公开 API。
2. `src.pipeline.orchestrator.PipelineOrchestrator` 负责执行阶段化流程。
3. `src.services.*` 适配画像构建、召回聚合、排序和可选 rerank。
4. `src.profiling`、`src.retrieval`、`src.ranking` 提供领域逻辑。
5. `src.contracts` 提供共享配置、接口和阶段间数据结构。
6. `src.utils` 提供 embedding、LM Studio 客户端和数据加载辅助能力。

`PipelineOrchestrator` 当前的阶段顺序：

1. 构建 `ProfileContext`
2. 用 `RetrievalManager` 产出召回分数
3. 用 `DefaultRanker` 做全量粗排
4. 可选地执行 `LLMReranker`
5. 做最终排序并返回 `RecommendationResult`

## Package 职责图

| Package | 职责 | 主要类 / 函数 |
| --- | --- | --- |
| `src.engine` | 公开 API、引擎状态、缓存保存/加载 | `PersonalRecSys`、`CandidateItem`、`RecommendationResult` |
| `src.pipeline` | 阶段编排 | `PipelineOrchestrator` |
| `src.contracts` | 配置、抽象接口、阶段契约 | `PipelineConfig`、`BaseProfileBuilder`、`BaseRetriever`、`BaseRanker`、`ProfileContext` |
| `src.services` | 具体服务适配层 | `DefaultProfileBuilder`、`RetrievalManager`、`DefaultRanker`、`LLMReranker` |
| `src.profiling` | 用户画像构建与持久化 | `VectorCloud`、`UserExplicitProfile`、`ProfileExtractor` |
| `src.retrieval` | 候选打分逻辑 | `I2IMatcher`、`BatchI2IMatcher`、`TagMatcher` |
| `src.ranking` | 分数归一化与融合 | `ScoreComponent`、`WeightedScorer`、`ConfigurableScorer`、`RankedItem` |
| `src.utils` | Embedding、LM Studio 客户端、数据加载辅助 | `get_embedder`、`LMStudioLLMClient`、`load_zhihu_items`、`compute_popularity` |

## 公开 API

`PersonalRecSys` 是主入口。

核心方法：

- `build_profile_from_collection(collection_items, llm_client=None, max_items=50)`
- `add_candidates(items)`
- `embed_candidates(batch_size=32)`
- `recommend(top_k=20, preset="balanced", custom_weights=None, min_score=None)`
- `save(path)` / `load(path, embedder=None)`

主要运行时数据结构：

- `CandidateItem`
- `RecommendationResult`
- `RankedItem`

最小使用示例：

```python
from src.engine import PersonalRecSys, CandidateItem
from src.utils.embeddings import get_embedder

recsys = PersonalRecSys(
    embedder=get_embedder("mock", dim=128),
    embedding_dim=128,
)

recsys.build_profile_from_collection([
    {"title": "Example", "content": "Profile source text"}
])

recsys.add_candidates([
    CandidateItem(item_id="a", title="Candidate A", content="...", tags=["tag1"])
])
recsys.embed_candidates()
results = recsys.recommend(top_k=5, preset="balanced")
```

## 已验证的运行行为

- `recommend()` 依赖“候选池 + 隐式画像”同时存在，否则会抛出 `ValueError`。
- `build_profile_from_collection(..., llm_client=None)` 只会构建隐式画像。
- 没有显式画像时，`TagRetriever` 会把所有候选的标签分统一回退为 `0.5`。
- 默认主流程中，流行度只来自 `candidate.metadata["popularity"]`。
- `ScoreComponent.RECENCY` 与 `ScoreComponent.DIVERSITY` 虽然定义了，但默认引擎不会产出对应分数。
- `save()` / `load()` 会持久化画像文件和 `meta.json`，不会恢复候选池。
- `embed_candidates()` 会对 `title + content` 拼接后的文本做 embedding，并截断到 2000 字符。
- `filter_count` 当前通过 `tag == 0.0` 统计得到，并不是单独的“负向硬过滤命中数”。

## 配置说明

`PipelineConfig` 是统一的运行时配置容器，但当前调用链并不是每个字段都完全打通。

- `top_k`、`preset`、`custom_weights` 会作为 orchestrator 默认值使用。
- `embedder_type` 及相关字段不会自动实例化 embedder；`PersonalRecSys` 仍优先使用显式传入的 `embedder`，否则回退到 mock embedder。
- `min_score` 虽然定义在 `PipelineConfig` 里，但当前 `recommend()` 路径在缺省时不会自动回退到 `config.min_score`。

## Embedding 与 LLM 后端

`src/utils/embeddings.py` 中可用的 embedder：

- `mock`
- `openai`
- `local`
- `lmstudio`

基于代码可验证的依赖说明：

- 当前 `requirements.txt` 只声明了 `numpy`。
- `OpenAIEmbedder` 需要安装 `openai`。
- `LocalEmbedder` 需要安装 `sentence-transformers`。
- `VectorCloud.get_clusters()` 会懒加载 `sklearn.cluster.KMeans`，但 `requirements.txt` 没有声明 `scikit-learn`。
- LM Studio 集成使用标准库 `urllib`，但要求本地 LM Studio 服务提供 OpenAI 兼容接口。

## 可选 Rerank

`src/services/reranker.py` 实现了 `LLMReranker`，`PipelineOrchestrator` 也支持 `set_reranker(...)`。

需要注意：

- `PersonalRecSys` 当前没有提供专门的公开便捷方法来启用 reranker。
- 默认示例没有把 reranker 接到高层引擎流程中。
- `docs/reranker_prompts.py` 和 `docs/reranker_prompts_v2.py` 只是参考材料；当前真正使用的 prompt 构建逻辑写在 `src/services/reranker.py` 里。

## 仓库结构

```text
personal-recsys/
├── src/                    # 运行时推荐引擎
├── experiments/            # 实验与评测实现
├── scripts/                # 标准脚本入口
├── tests/                  # 脚本式验证
├── research/               # 研究笔记
├── docs/                   # 补充文档与 prompt 参考
├── data/                   # 本地数据 / 缓存目录
├── datacrawl/              # 独立的数据采集工作区
├── example_usage.py        # 顶层兼容包装
├── run_real_data.py        # 顶层兼容包装
└── requirements.txt
```

`docs/` 很适合做补充上下文，但它并不会被运行时主引擎导入。`scripts/` 是新的标准入口目录，顶层 `run_*.py` / `example_usage.py` 仅保留兼容用途。

## 本地 MVP CLI

仓库现在还包含一个不依赖 LLM 的本地 MVP CLI，用来跑最小单用户推荐工作流：

```bash
python3 scripts/product/run_mvp.py \
  --collection path/to/collection.json \
  --collection-format zhihu \
  --candidates path/to/candidates.json \
  --candidates-format zhihu
```

第一版特性：

- 单命令工作流
- 只使用隐式画像
- 不启用显式画像和 rerank
- 支持 `zhihu` 与 `generic` 两种 JSON 输入
- 输出 `run_config.json`、`input_summary.json`、`recommendations.json`、`engine_meta.json`

`generic` JSON 第一版要求每个 item 都包含：

- `id`
- `title`
- `content`
- `tags`
- `metadata`

## 一键从爬虫到推荐

仓库现在还包含一个总编排入口，可以把现有知乎爬虫和本地推荐 MVP 串成一条命令：

```bash
python3 scripts/product/run_end_to_end.py \
  --favorites-user cjm926 \
  --author-id some-author-id
```

如果你省略 `--favorites-user`、`--author-id`、`--pages` 或 `--top-k`，同一个入口现在会退回到交互式产品提示，先补全缺失参数再开始执行。

第一版约束：

- 直接复用 `datacrawl/zhihu_crawler`
- 默认总是现抓，不复用旧 JSON
- 候选池默认使用作者全部内容（回答 + 文章）
- 默认无头运行，但要求 `datacrawl/zhihu_crawler/data/cookies.json` 已存在
- 首次登录不在这条命令里完成

这条命令会额外写出：

- `crawler_run_config.json`
- `crawler_output_summary.json`
- `end_to_end_run_config.json`

交互式示例：

```bash
python3 scripts/product/run_end_to_end.py
```

## 快速开始

安装当前最小依赖：

```bash
python3 -m pip install -r requirements.txt
```

运行轻量示例：

```bash
python3 scripts/demo/example_usage.py
```

运行脚本式检查：

```bash
python3 tests/test_basic.py
```

## 真实数据演示

`scripts/demo/run_real_data.py` 演示了以下组合：

- 通过 `src/utils/data_loader.py` 加载知乎风格 JSON
- 使用 LM Studio 生成 embedding 与显式画像
- 根据 `voteup_count` 与 `comment_count` 计算流行度

脚本当前默认要求：

- 本地 LM Studio 服务运行在 `http://localhost:1234/v1`
- JSON 文件位于 `datacrawl/zhihu_crawler/data`

运行方式：

```bash
python3 scripts/demo/run_real_data.py
```

## Simulator 实验

仓库中还包含一套离线 `user simulator` 实验，用来比较 `fulltext` 与 `adaptive compressed` 两种文章视图下的 pairwise Glicko2 排名。它产出的是 `simulator ranking`，不是真人偏好的 ground truth。

重要 caveat：`compressed` 通道评估的是结构化证据表示上的 simulator preference，不是完整文章本体的偏好。详见 [docs/simulator_glicko_experiment.md](docs/simulator_glicko_experiment.md) 中的表示层 caveats。

请参见 [docs/simulator_glicko_experiment.md](docs/simulator_glicko_experiment.md)，运行方式：

```bash
python3 scripts/experiments/run_simulator_glicko_experiment.py
```

## 产品路线图

仓库现在也包含一份长期产品路线图，用来说明如何把当前引擎逐步演进成一个**本地单用户、可交互、推荐质量达标**的产品。

这份路线图与运行时说明文档的角色不同：

- `README_ZH.md` 描述当前代码事实
- `docs/PROJECT_STATUS.md` 描述当前实现状态
- [docs/product_roadmap_zh.md](docs/product_roadmap_zh.md) 描述后续建设顺序和产品优先级

当前路线图中的优先级顺序是：

1. 补强主链推荐质量
2. 产品化通用 rerank 插槽
3. 把评测体系沉淀为产品研发基础设施
4. 增加本地交互闭环
5. 做产品级工程打磨

## 持久化

当设置 `cache_dir` 时，引擎会读写：

- `vector_cloud.json`
- `explicit_profile.json`

`save(path)` 还会写入：

- `meta.json`

`load(path)` 会恢复画像状态和 embedding 维度，但在再次 `recommend()` 前仍需要重新注入候选池。

## 开发说明

- `tests/test_basic.py` 是带断言和标准输出的脚本，不是完整 pytest 套件。
- `example_usage.py` 在构建隐式画像后手动注入了显式画像，这是示例层行为，不是引擎自动行为。
- `src/contracts/types.py` 中虽然定义了 `RecommendRequest` 和 `RecommendResponse`，但当前公开 `PersonalRecSys.recommend()` 仍使用直接参数并返回 `RecommendationResult`。

## License 状态

仓库根目录当前没有 `LICENSE` 文件。
