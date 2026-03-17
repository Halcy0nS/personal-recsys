# AGENTS.md

适用范围：`/Users/salmon/Documents/python/personal-recsys`。  
若子目录存在更深层的 `AGENTS.md`，以更深层文件为准。

## 1. Ground Truth

- 以源码实现为准，优先阅读：
  - `src/`
  - `example_usage.py`
  - `tests/test_basic.py`
  - `run_real_data.py`
- `docs/` 是补充文档与历史设计材料，不是运行时导入模块。
- `datacrawl/` 与其他爬虫/采集工作区不属于当前推荐引擎主执行路径；不要把它们当成 `src` 的运行时依赖来描述。
- 文档、说明、评审结论必须严格基于当前可读代码，不允许补写未实现能力。

## 2. 项目边界

当前仓库中“可运行的推荐核心”位于 `src/`，对外入口是 `src.engine.PersonalRecSys`。

已实现范围：

- 从用户收藏构建隐式画像（向量云）
- 可选地用 LLM 提取显式画像
- 对候选内容执行向量召回与标签匹配
- 对多维分数做归一化与加权融合
- 保存/加载画像缓存与引擎元数据

不应擅自宣称为已实现的范围：

- 桌面 GUI
- 服务编排/多进程壳层
- 自动接入 `datacrawl*` 目录的采集流程
- 完整的 pytest 套件或打包发布流程

## 3. 架构总览

当前主调用链是：

1. 外部调用方使用 `src.engine.PersonalRecSys`
2. `PersonalRecSys` 持有状态，并把主流程委托给 `src.pipeline.orchestrator.PipelineOrchestrator`
3. `PipelineOrchestrator` 组合 `src.services.*` 中的具体服务
4. `src.services.*` 再调用 `src.profiling`、`src.retrieval`、`src.ranking` 中的领域逻辑
5. `src.contracts` 提供配置、接口与阶段间数据契约
6. `src.utils` 提供 embedding、LM Studio 客户端与数据加载辅助能力

## 4. Package 职责与关系

### 4.1 `src.engine`

- `PersonalRecSys` 是公开 API 外观层，负责：
  - 初始化 embedder、配置和 orchestrator
  - 持有 `vector_cloud`、`explicit_profile`、`candidates`、`candidate_embeddings`
  - 暴露 `build_profile_from_collection()`、`add_candidates()`、`embed_candidates()`、`recommend()`、`save()`、`load()`
- `CandidateItem` 是候选内容数据结构。
- `RecommendationResult` 是推荐结果数据结构。

### 4.2 `src.pipeline`

- `PipelineOrchestrator` 负责编排阶段顺序，不持有长期业务状态。
- 当前顺序是：
  - `ProfileBuilder`
  - `RetrievalManager`
  - 粗排 `DefaultRanker`
  - 可选 `LLMReranker`
  - 最终 `DefaultRanker`

### 4.3 `src.contracts`

- `config.py`：
  - `PipelineConfig` 统一保存运行参数。
- `interfaces.py`：
  - 定义 `BaseProfileBuilder`、`BaseRetriever`、`BaseRanker` 抽象接口。
- `types.py`：
  - 定义 `ProfileContext`、`ScoreMap`、`RecommendRequest`、`RecommendResponse`。
- 注意：
  - 当前主引擎实际使用的是 `ProfileContext` 与 `ScoreMap`。
  - `RecommendRequest` / `RecommendResponse` 已定义，但不是 `PersonalRecSys.recommend()` 当前直接使用的公开返回契约。

### 4.4 `src.services`

- `profile_builder.py`：
  - `DefaultProfileBuilder` 封装隐式画像与显式画像构建逻辑。
- `retrieval_manager.py`：
  - `RetrievalManager` 聚合多个召回器输出为统一 `ScoreMap`。
  - `I2IRetriever` 适配 `I2IMatcher`。
  - `TagRetriever` 适配 `TagMatcher`。
- `ranker_adapter.py`：
  - `DefaultRanker` 负责把字符串分数组件转换为 `ScoreComponent`，再调用 `ConfigurableScorer`。
- `reranker.py`：
  - `LLMReranker` 提供点式 LLM rerank 服务。
  - 当前它是可选能力，需要显式注入到 `PipelineOrchestrator`；`PersonalRecSys` 没有公开的便捷 setter。

### 4.5 `src.profiling`

- `implicit_profile.py`：
  - `VectorCloud` 保存归一化向量和元数据。
  - 支持 `find_closest_in_cloud()`、`get_clusters()`、`save()`、`load()`。
- `explicit_profile.py`：
  - `UserExplicitProfile` 是可持久化、可编辑的显式画像 schema。
  - `ProfileExtractor` 负责采样收藏内容、构建 prompt、调用 LLM、解析 JSON。

### 4.6 `src.retrieval`

- `i2i_matcher.py`：
  - `I2IMatcher` 计算候选向量与向量云中 top-k 收藏向量的平均相似度。
  - `BatchI2IMatcher` 提供批量包装。
- `tag_matcher.py`：
  - `TagMatcher` 对正负标签做规则匹配。
  - 可从 `title/content` 中抽词扩充标签集合。
  - 可对命中负向标签的内容执行硬过滤。

### 4.7 `src.ranking`

- `scorer.py`：
  - `ScoreComponent` 定义打分维度枚举。
  - `WeightedScorer` 执行分量归一化和加权融合。
  - `ConfigurableScorer` 提供 `balanced` / `exploration` / `precision` / `quality` 预设。
  - `RankedItem` 保存最终排序结果。

### 4.8 `src.utils`

- `embeddings.py`：
  - `MockEmbedder`
  - `OpenAIEmbedder`
  - `LocalEmbedder`
  - `LMStudioEmbedder`
  - `get_embedder()`
- `lm_studio_client.py`：
  - `LMStudioLLMClient`，提供 OpenAI 兼容的 `chat()` 封装。
- `data_loader.py`：
  - 提供知乎 JSON 到标准条目的加载、收藏/候选切分、流行度计算。
  - 它处理的是已存在的数据文件，不代表爬虫模块是推荐引擎运行时依赖。

## 5. 关键实现事实

- `recommend()` 之前必须已有：
  - 候选池（`add_candidates()`）
  - 隐式画像（`build_profile_from_collection()`）
- `build_profile_from_collection(..., llm_client=None)` 只会构建隐式画像。
- `ProfileExtractor` 自身支持 mock 响应兜底，但 `DefaultProfileBuilder.build_explicit()` 在 `llm_client is None` 时会直接返回 `None`。
- `TagRetriever` 在没有显式画像时，会把所有候选的标签分统一回退为 `0.5`。
- 默认排序只读取 `candidate.metadata["popularity"]` 作为流行度分；`likes`、`author` 等字段不会自动参与主排序。
- `ScoreComponent.RECENCY` 与 `ScoreComponent.DIVERSITY` 已定义，但默认主引擎不会产出这两类分数。
- `filter_count` 当前是通过 `tag == 0.0` 统计得到，不等同于“严格命中负向硬过滤的数量”。
- `save()` / `load()` 只保存与恢复画像和 `meta.json`，不会恢复候选池。
- `embed_candidates()` 会对 `title + content` 拼接文本做 embedding，并把文本截断到 2000 字符。
- `VectorCloud.get_clusters()` 懒加载 `sklearn.cluster.KMeans`；仓库根 `requirements.txt` 没有声明 `scikit-learn`。

## 6. 配置与能力边界

- `PipelineConfig` 是统一配置容器，但不要假设所有字段都已完全打通：
  - `top_k`、`preset`、`custom_weights` 会作为 orchestrator 默认值使用。
  - `min_score` 定义在配置中，但当前调用链不会在缺省时自动从 `config.min_score` 回退。
  - `embedder_type` / `embedder_kwargs` 存在于配置中，但 `PersonalRecSys` 仍以显式传入的 `embedder` 为准；未传入时会默认使用 `mock` embedder。
- `LLMReranker` 已实现，但不属于默认高层 API 流程；不要把它描述成“开箱即用的默认步骤”。
- `docs/reranker_prompts*.py` 是补充材料；当前 `LLMReranker` 的 prompt 构建逻辑写在 `src/services/reranker.py` 内。

## 7. 开发与验证

推荐命令：

```bash
python3 -m pip install -r requirements.txt
python3 example_usage.py
python3 tests/test_basic.py
```

可选演示：

```bash
python3 run_real_data.py
```

附加说明：

- `run_real_data.py` 依赖本地 LM Studio 服务与现成 JSON 数据文件。
- 当前测试是脚本式断言，不是完整 pytest 套件。

## 8. 文档维护规则

- 文档必须以代码事实为准；当代码和既有文档冲突时，以代码为准并更新文档。
- README 双语文件必须互相提供语言切换入口：
  - `README.md` -> `README_ZH.md`
  - `README_ZH.md` -> `README.md`
- 更新文档时优先同步这些内容：
  - 公开 API
  - package 职责与调用关系
  - 已实现能力与未实现边界
  - 可复现的运行/验证命令
  - 依赖与前置条件

## 9. 禁止事项

- 不要把 `docs/` 或历史重构文档当成当前运行事实。
- 不要把 `datacrawl/`、`datacrawl-refactor/` 自动写成推荐引擎的运行依赖。
- 不要宣称存在 GUI、服务编排、自动化调度、线上部署能力，除非代码中出现了对应实现。
- 不要在文档任务中顺带修改业务代码。
