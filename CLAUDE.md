# CLAUDE.md

本文件是当前仓库的 Claude / AI Agent 快速指引；详细规则以 `AGENTS.md` 为准。

## 1. 先看哪里

- 首先阅读：
  - `src/`
  - `example_usage.py`
  - `tests/test_basic.py`
  - `run_real_data.py`
- `docs/` 仅作补充参考，不是运行时真相来源。
- 不要把 `datacrawl/` 或其他采集目录当成当前推荐引擎主链路。

## 2. 当前真实架构

推荐核心的实际分层是：

1. `src.engine`
   - `PersonalRecSys` 公开 API 与状态容器
2. `src.pipeline`
   - `PipelineOrchestrator` 负责阶段编排
3. `src.contracts`
   - 配置、接口、阶段间数据结构
4. `src.services`
   - profile builder / retrieval manager / ranker adapter / optional reranker
5. `src.profiling`
   - `VectorCloud`
   - `UserExplicitProfile`
   - `ProfileExtractor`
6. `src.retrieval`
   - `I2IMatcher`
   - `TagMatcher`
7. `src.ranking`
   - `WeightedScorer`
   - `ConfigurableScorer`
8. `src.utils`
   - embedder、LM Studio client、数据加载辅助

## 3. 关键实现事实

- `recommend()` 前必须先有候选池和隐式画像。
- `build_profile_from_collection(..., llm_client=None)` 不会生成显式画像。
- 没有显式画像时，标签分统一回退为 `0.5`。
- 默认流行度分只读取 `candidate.metadata["popularity"]`。
- `RECENCY` / `DIVERSITY` 只定义在枚举里，默认主流程不产出。
- `save()` / `load()` 不恢复候选池。
- `LLMReranker` 是可选组件，不是默认高层 API 自动开启的步骤。
- `PipelineConfig` 并不会自动帮你实例化 embedder；未显式传入 `embedder` 时仍默认使用 `mock`。

## 4. 命令

```bash
python3 -m pip install -r requirements.txt
python3 example_usage.py
python3 tests/test_basic.py
```

可选真实数据演示：

```bash
python3 run_real_data.py
```

## 5. 文档要求

- 只写代码可验证事实，不补写未实现功能。
- README 中英双语入口必须互链：
  - `README.md` <-> `README_ZH.md`
- 文档任务只改文档与引用，不改业务代码。
