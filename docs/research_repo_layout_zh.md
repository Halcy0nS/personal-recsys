# 研究型仓库整理建议

这份建议只基于当前仓库可见文件与导入关系，目标是先把“主线代码”和“实验噪音”分开，而不是一次性大迁移。

## 现在最混乱的边界

当前顶层同时混着四类东西：

- `src/`：真正的运行时推荐核心
- `run_*.py`：脚本入口，但其中有的偏主线演示，有的偏离线实验
- `docs/`、`research_zhihurec/`：文档与研究笔记
- `data/`、`_archive/`：本地输出、缓存和历史快照

最容易让仓库失控的不是“文件太多”，而是：

- 主线引擎和离线实验共享顶层可见度
- 研究笔记没有稳定落点，容易临时新建 `research_xxx/`
- 数据、缓存、实验结果都进了 `data/`，但没有固定分层

## 这类仓库里，哪些应该留在顶层

建议长期保留在顶层的只有这些：

- `src/`
- `tests/`
- `docs/`
- `scripts/`
- `research/`
- `data/`
- `config/`
- `README.md` / `README_ZH.md`
- `requirements.txt`

另外，只有“对外最主要的一个演示入口”值得留在顶层。基于当前代码，`example_usage.py` 可以继续留顶层，因为它是最轻量的公开示例。

## 哪些东西适合挪走

这些建议是按低风险优先排序的：

- `research_zhihurec/` -> `research/zhihurec/`
- `run_simulator_glicko_experiment.py` -> `scripts/experiments/`
- `run_rag_rerank_experiment.py` -> `scripts/experiments/`
- `run_fetch_full_favorites.py` -> `scripts/data/`
- `run_real_data.py`：如果你把它视为“真实数据 demo”，可先保留顶层；如果你把它视为实验脚本，再移到 `scripts/demo/`
- `_archive/`：继续保留，但明确只存冻结快照，不放当前可执行脚本

当前不建议马上移动 `run_simulator_glicko_experiment.py`，因为 [`tests/test_basic.py`](/Users/salmon/Documents/python/personal-recsys/tests/test_basic.py#L41) 直接导入了它。

## `data/` 建议怎么分

结合你现在已有内容，推荐固定成下面四层：

```text
data/
├── raw/           # 外部原始数据，只做最小必要处理
├── processed/     # 可复现处理中间产物
├── cache/         # 可丢弃缓存，如 embedding / profile cache
└── experiments/   # 每次实验的输出与结果
```

映射到当前仓库：

- `data/raw/`：放 `ZhihuRec`、导出的知乎 JSON 等原始输入
- `data/real_data_cache/`：建议后续改名到 `data/cache/real_data/`
- `data/simulator_glicko/runs/`：建议后续归到 `data/experiments/simulator_glicko/`
- `data/merged_content_inventory/`：如果它来自原始数据融合，建议后续归到 `data/processed/`

## 最小改动、低风险重组方案

第一阶段先做命名和落点统一，不大量搬文件：

1. 新增并固定使用 `scripts/`、`research/`、`data/raw/zhihurec/`
2. 新实验一律不再落顶层，统一放进 `scripts/experiments/` 或 `research/<topic>/`
3. 新研究笔记不再建 `research_xxx/`，统一放 `research/<topic>/`
4. 新实验结果不再自定义路径，统一放 `data/experiments/<experiment_name>/`

第二阶段再处理历史文件：

1. 把不被测试直接导入的 `run_*.py` 逐步迁到 `scripts/`
2. 给仍留在顶层的入口脚本加一句注释，说明它属于 `demo` 还是 `experiment`
3. 等测试不再直接导入顶层实验脚本后，再移动 `run_simulator_glicko_experiment.py`

## 一个判断标准

以后每新增一个文件，先问自己一句：

- 这是运行时能力吗？放 `src/`
- 这是一次性或多次性脚本吗？放 `scripts/`
- 这是研究笔记或调研结论吗？放 `research/`
- 这是原始数据 / 处理中间结果 / 缓存 / 实验输出吗？放 `data/` 对应层

如果一个文件回答不了这四个问题，通常就是它不该在顶层。
