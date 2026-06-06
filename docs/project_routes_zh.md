# 项目路线盘点

这份文档的目标不是给功能排期，而是回答一个更基础的问题：

- 这个仓库现在到底有多少条路线
- 哪些是主线，哪些是支撑线
- 新工作应该落到哪条线上

这份盘点严格基于当前代码和目录事实，不把未实现能力算进来。

## 一句话结论

当前仓库可以收束成 4 条路线：

1. 轻量个性化推荐主线
2. 公开数据集研究验证线
3. LLM 排序与评测方法线
4. 真实数据导入与个人闭环线

如果再往上压一层，其实只有 2 个大方向：

- 产品方向：把本地单用户推荐系统做出来
- 研究方向：搞清楚推荐质量最值得投哪一层

其中：

- 路线 1 和路线 2 是主线
- 路线 3 和路线 4 是支撑线

## 顶层目录归属

如果只看仓库顶层，可以先这样理解：

### 主要属于路线 1：轻量个性化推荐主线

- `src/`
- `config/`
- `example_usage.py`
- `run_real_data.py`

说明：

- 这些目录和入口主要服务“主推荐系统今天怎么跑起来、怎么更稳定”
- 其中顶层 `example_usage.py`、`run_real_data.py` 目前仍是兼容入口，正式位置已经转到 `scripts/demo/`

### 主要属于路线 2：公开数据集研究验证线

- `experiments/zhihurec/`
- `research/zhihurec/`
- `scripts/experiments/zhihurec/`
- `scripts/zhihurec/`

说明：

- 这条线主要围绕 `ZhihuRec` 数据和离线研究实验展开
- 目标是回答“主系统最值得重投哪一层”，不是直接形成产品运行时能力

### 主要属于路线 3：LLM 排序与评测方法线

- `experiments/` 中除 `zhihurec/`、`common/real_data.py` 之外的评测模块
- `scripts/experiments/`
- `run_llm_pairwise_experiment.py`
- `run_order_instability_attribution_experiment.py`
- `run_pairwise_eval.py`
- `run_rag_rerank_experiment.py`
- `run_reranker_stability_experiment.py`
- `run_simulator_glicko_experiment.py`

说明：

- 这条线负责回答“排序评测是否可靠、LLM rerank 是否稳定”
- 顶层 `run_*.py` 当前主要是兼容 wrapper，正式入口在 `scripts/experiments/`

### 主要属于路线 4：真实数据导入与个人闭环线

- `data/`
- `scripts/demo/`
- `scripts/data/`
- `run_fetch_full_favorites.py`

说明：

- 这条线负责原始输入、处理中间结果、实验产物和真实数据工作流
- 它和路线 1 有强耦合，但关注点更偏“数据怎么进系统、产物怎么落地”

### 不直接属于四条路线本身，但服务所有路线

- `docs/`
- `tests/`
- `README.md`
- `README_ZH.md`
- `requirements.txt`
- `.venv/`
- `_archive/`

说明：

- 这些是横切层
- 它们不是单独的一条产品/研究路线，但会为所有路线提供文档、验证、环境或历史快照支撑

## 路线 1：轻量个性化推荐主线

### 目标

把当前已经存在的推荐引擎，逐步做成一个本地单用户、可解释、可重复运行的推荐系统。

### 主要代码落点

- `src/`
- `src.engine.PersonalRecSys`
- `src.pipeline.orchestrator.PipelineOrchestrator`
- `scripts/demo/example_usage.py`
- `scripts/demo/run_real_data.py`

### 当前已经具备的东西

- 从收藏内容构建隐式画像
- 可选地构建显式画像
- 基于向量和标签做召回
- 统一分数归一化与融合排序
- 保存和加载画像缓存

### 这条线回答的问题

- 用户历史怎么变成可用的画像
- 候选内容怎么召回和排序
- 什么样的轻量系统能先跑通真实闭环

### 当前最值得继续做的事

- 补强主链排序特征和解释能力
- 把 rerank 变成正式运行时插槽，而不是只停留在实验语义里
- 让真实数据 demo 更稳定、更容易重复运行

## 路线 2：公开数据集研究验证线

### 目标

用公开推荐数据集回答“未来主系统最该重投哪一层”，而不是直接追求论文分数。

### 主要代码落点

- `experiments/zhihurec/`
- `scripts/experiments/zhihurec/`
- `research/zhihurec/`
- `docs/zhihurec_three_step_experiment_zh.md`

### 当前已经具备的东西

- `ZhihuRec-1M` 数据准备脚本
- `Exp0 popularity`
- `Exp1 mean-pool`
- `Exp2 SASRec`
- `Exp3 SASRec -> MLP rerank`

### 这条线回答的问题

- 简单内容匹配够不够
- 序列建模是不是主矛盾
- 两阶段精排值不值得重投入

### 当前最值得继续做的事

- 用同口径结果持续比较一阶段方案
- 补更强的一阶段 baseline，而不是过早扩 reranker
- 把结论迁回主系统设计，而不是长期停留在公开数据集里

## 路线 3：LLM 排序与评测方法线

### 目标

研究如何更稳定地使用 LLM 做 rerank、pairwise judge 和排序质量分析。

### 主要代码落点

- `experiments/llm_pairwise.py`
- `experiments/pairwise.py`
- `experiments/reranker_stability.py`
- `experiments/order_instability_attribution.py`
- `experiments/simulator_glicko.py`
- 对应的 `scripts/experiments/run_*.py`

### 当前已经具备的东西

- pairwise 评测
- reranker 稳定性分析
- order instability attribution
- simulator + Glicko2 校准
- candidate-aware RAG rerank 实验

### 这条线回答的问题

- LLM rerank 到底稳不稳
- 排序提升是真的，还是 prompt 抖动或 judge 偏差
- 什么样的评测方式更适合支持产品迭代

### 当前最值得继续做的事

- 让这些评测更标准化，服务主产品改动
- 把经过验证的 rerank 抽象回流到运行时主链
- 避免继续把它扩张成与主项目脱节的独立大分支

## 路线 4：真实数据导入与个人闭环线

### 目标

把个人收藏、候选池和本地数据准备过程，逐步组织成一个真实可用的输入闭环。

### 主要代码落点

- `src/utils/data_loader.py`
- `experiments/common/real_data.py`
- `scripts/demo/run_real_data.py`
- `scripts/zhihurec/prepare.py`
- `data/raw/`
- `data/experiments/`

### 当前已经具备的东西

- 真实数据 demo 入口
- 知乎数据加载与切分辅助能力
- `ZhihuRec` 原始数据与实验产物落点

### 这条线回答的问题

- 真实用户数据怎么进入系统
- 原始数据、处理中间产物、实验结果怎么组织
- 如何形成“导入历史 -> 构建画像 -> 运行推荐 -> 比较结果”的最小闭环

### 当前最值得继续做的事

- 继续清理数据目录规范
- 把真实数据 demo 和研究实验的输入输出边界分清
- 让本地复现实验和真实数据运行共享更稳定的准备逻辑

## 哪两条是主线

如果你接下来要强行收缩精力，建议只把下面两条当主线：

1. 路线 1：轻量个性化推荐主线
2. 路线 2：公开数据集研究验证线

原因很简单：

- 路线 1 负责把系统做出来
- 路线 2 负责告诉你系统该往哪一层投入

路线 3 和路线 4 都重要，但更适合作为支撑线存在：

- 路线 3 提供评测和方法学证据
- 路线 4 提供真实数据闭环和工程落点

## 以后怎么判断新工作属于哪条线

每次新增一个想法或文件，先问自己它是在回答哪一个问题：

- 如果它在回答“推荐系统今天怎么跑得更好”，归路线 1
- 如果它在回答“哪种建模方式更值得继续投”，归路线 2
- 如果它在回答“评测或 judge 靠不靠谱”，归路线 3
- 如果它在回答“真实数据怎么进系统”，归路线 4

如果一个新东西回答不了这 4 类问题，通常它不是一条新路线，而只是一个暂时还没归类的实验碎片。

## 当前建议的优先顺序

1. 先稳住路线 1 的主推荐链路
2. 同时用路线 2 给路线 1 提供研究证据
3. 让路线 3 成为路线 1 的评测工具箱
4. 让路线 4 成为路线 1 的真实输入闭环

也就是说，后面最好的项目叙事不是“我有很多实验”，而是：

- 我有一个主产品方向
- 我有一条研究线帮它判断方向
- 我有一套评测线帮它验证改动
- 我有一条数据线把真实输入接进来

## 关于开发规则文档

当前更推荐把规则写在“最相关的现有文档”里，而不是立刻新建 `docs/dev_rules_zh.md`。

原因是：

- 现在仓库已经有路线文档、产品路线图、仓库整理建议
- 如果再单独新开一份开发规则，短期内很容易和这些文档重叠
- 对你这种研究型项目，最重要的是先把“规则跟上下文绑在一起”，而不是再多一个总纲文件

所以建议是：

- 路线归属、主线/支撑线判断，写在本文档
- 仓库目录整理规则，写在 `docs/research_repo_layout_zh.md`
- 产品推进顺序，写在 `docs/product_roadmap_zh.md`

只有当你后面真的积累出一套稳定、跨所有路线都通用的日常开发约定时，再单独抽出 `docs/dev_rules_zh.md` 更合适。
