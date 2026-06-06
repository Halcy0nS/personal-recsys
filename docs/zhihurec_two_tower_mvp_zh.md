# ZhihuRec 双塔语义协同检索 MVP 方案

Last updated: 2026-03-23

## 1. TL;DR

“用 ZhihuRec 训练一个双塔检索模型，把协同信号和内容信号炼到一起”这个方向是对的，但它不能被直接表述成：

- 拿开源 ZhihuRec
- 微调一个通用中文 `sentence-transformers`
- 然后无缝替换当前仓库里的 raw-text embedding

原因很简单：

1. ZhihuRec 开源版不提供原始文章文本，只提供匿名 `token IDs`
2. `info_token.csv` 提供的是 `64d word2vec`，不是可逆的中文文本词表
3. 当前仓库主运行链路处理的是 `title/content` 原始文本，而不是 ZhihuRec 的匿名 token 序列

所以，一个更现实、也更稳的路线是：

1. 把 ZhihuRec 双塔定义为一个独立的“研究型召回基线”
2. 先在 ZhihuRec 自身模态上把序列建模、hard negative、离线评测做扎实
3. 再决定是否把它蒸馏或桥接到当前 raw-text 推荐系统

结论：

- 这条路值得做
- 但它更适合作为 `Phase 2` 的坚实底座，而不是当前项目的第一步替换方案

## 2. 当前仓库的现实约束

基于当前源码，主推荐引擎是一个“原始文本 -> embedding -> 候选向量检索/融合排序”的系统：

- `PersonalRecSys` 持有状态并暴露公开 API
- `embed_candidates()` 会对 `title + content` 拼接文本做 embedding
- `I2IRetriever` 直接消费候选向量做召回
- `TagRetriever` 和 `DefaultRanker` 在其后做规则匹配与加权融合

对应代码入口：

- `src/engine.py`
- `src/services/retrieval_manager.py`
- `src/retrieval/i2i_matcher.py`
- `src/ranking/scorer.py`

这意味着当前运行时默认假设是：

- 我们手里有原始标题和正文
- 我们可以对任意新候选实时编码
- 用户画像也来自同一语义空间中的文本向量

ZhihuRec 并不天然满足这三个假设。

## 3. ZhihuRec 能提供什么，不能提供什么

根据公开 README，ZhihuRec-100M 包含：

- `inter_impression.csv`: 用户、答案、曝光时间、点击时间
- `inter_query.csv`: 用户、query token IDs、query 时间
- `info_answer.csv`: answer 的统计特征、topic IDs、token IDs
- `info_question.csv`: question 的统计特征、topic IDs、token IDs
- `info_author.csv`: author 统计特征
- `info_token.csv`: token ID 对应的 64 维 word2vec

但它明确不提供：

- token 对应的原始文本
- 可直接输入 `bert-base-chinese` 的中文句子
- 你当前项目那种 `title/content` 形式的开放文本字段

这决定了我们不能把 ZhihuRec MVP 写成“中文文本双塔”。更准确的表述应该是：

- **ZhihuRec token-space 双塔协同检索模型**

## 4. 推荐的 MVP 定位

### 4.1 目标

做一个严肃的、高质量的、能吃下真实交互日志的召回基线，用来回答：

- 协同日志是否能显著优于当前通用 embedding 基线？
- 用户短期行为序列是否能比静态画像更强？
- 暴露未点击样本作为 hard negatives 后，召回质量能否明显提升？

### 4.2 非目标

本阶段不追求：

- 直接替换当前仓库里的 raw-text embedding
- 一步到位接入生成式 LLM 做在线大模型重排
- 把 ZhihuRec 训练结果直接泛化到任意知乎 raw text 候选

### 4.3 成功标准

在严格的时间切分评测下，相比简单 baseline，双塔在离线指标上稳定提升：

- Recall@50
- Recall@100
- NDCG@50
- MRR@50

同时给出一组可复现的训练与评测脚本，而不是只给模型口号。

## 5. 改写后的三阶段蓝图

## Phase 1: 先做一个可复现的 ZhihuRec 离线基线

### 目标

先把数据切分、样本构造、评测协议做对，避免后续所有模型都在错误地比较。

### 数据切分

采用按时间切分，而不是随机切分：

- 训练集：前 7 天
- 验证集：第 8-9 天
- 测试集：第 10 天

每个用户只用“当前时刻之前”的行为构建 query，避免时间泄漏。

### 样本构造

对每个有点击的 impression 事件构造一条训练样本：

- `query`: 用户在该点击前的短期行为上下文
- `positive_item`: 本次点击的 answer
- `hard_negatives`: 同一时间窗内曝光但未点击的 answer

推荐的 query 组成：

- 最近 `K` 次点击的 answer token IDs
- 最近 `M` 条 query token IDs
- 最近点击 answer 的 topic IDs

不建议只拼“最近 3 篇文章”，因为 ZhihuRec 还有 query log，这个信号很宝贵。

### baseline

至少保留三组 baseline：

1. popularity baseline
2. item-based 协同 baseline
3. mean-pooled token embedding baseline

没有这三组对照，双塔提升很难说明问题。

## Phase 2: 训练一个真正吃协同信号的双塔模型

### 用户塔

输入不是原始中文文本，而是离散特征序列：

- recent clicked answer tokens
- recent query tokens
- recent topic IDs

推荐一个小而稳的结构：

- `token embedding`: 初始化为 `info_token.csv` 的 64 维向量
- `topic embedding`: 可训练
- `type embedding`: 区分 answer/query/topic 片段
- `encoder`: 2-layer Transformer 或轻量 GRU
- `pooling`: attention pooling 或 mean pooling
- 输出 `user embedding`

### 物品塔

输入使用 answer 侧公开特征：

- answer token IDs
- answer topic IDs
- question ID / question topic IDs
- author ID 或 author side stats
- answer 的基础统计量，如 likes/comments/collections

推荐结构：

- token/topic 嵌入层
- 一层轻量序列编码
- 数值特征 MLP
- 拼接后投影到统一向量空间

### 训练目标

不要只用纯 in-batch negative。

推荐组合：

- 主损失：InfoNCE / sampled softmax
- 负样本：batch 内随机负样本
- 强负样本：同曝光未点击 answer

这比单纯 `MultipleNegativesRankingLoss` 更符合 ZhihuRec 的曝光日志结构。

### 采样策略

建议控制样本复杂度：

- 每个正样本最多采 `N=5~20` 个 hard negatives
- 用户行为历史截断到最近 `20~50` 条
- token 序列长度单独截断，避免显存爆炸

### 为什么这是“协同 + 语义同炉”

因为模型不是只靠答案 ID 做 CF，也不是只靠通用语义做文本匹配：

- token/topic 序列让它看到内容结构
- 用户序列和点击日志让它学到共同行为模式
- 曝光未点击让它学会“看起来相关但用户没点”的边界

## Phase 3: 决定如何桥接到当前仓库

这是最容易被说大话、也最需要谨慎的阶段。

### 方案 A: 研究轨与产品轨分离

最稳妥的做法是：

- ZhihuRec 双塔只作为离线研究基线存在
- 当前产品链路继续使用 raw-text embedder + I2I + tag + rerank

适用场景：

- 我们还没有稳定的原始文本互动数据
- 还不确定领域专用召回到底能提升多少

### 方案 B: 蒸馏到 raw-text encoder

如果后续想让当前项目真正吃到 ZhihuRec 学到的偏好结构，可以考虑蒸馏：

1. 先训练 ZhihuRec token-space teacher
2. 再用本地 raw text 候选构造 student 数据
3. 让 raw-text student 去拟合 teacher 的相对相似度或检索排序

这样才有机会把“匿名 token 空间里的群体规律”搬到当前系统的原始文本空间。

### 方案 C: 仅迁移训练方法，不迁移权重

也可以只迁移方法论：

- 保留当前 raw-text 输入
- 学 ZhihuRec 双塔的训练范式
- 用你自己的收藏/点击/停留日志重训 raw-text 双塔

这往往比“硬搬 ZhihuRec 权重”更现实。

## 6. 针对当前仓库的最小接入建议

如果未来真的要落地到这个仓库，建议按最小侵入方式推进。

### 6.1 不先改公开 API

保留：

- `build_profile_from_collection()`
- `add_candidates()`
- `embed_candidates()`
- `recommend()`

第一阶段只新增实验脚本和离线模块，不破坏现有入口。

### 6.2 新增而不是替换

建议新增模块，而不是直接改现有召回逻辑：

- `src/experiments/zhihurec/`
- `src/experiments/zhihurec/data.py`
- `src/experiments/zhihurec/model.py`
- `src/experiments/zhihurec/train.py`
- `src/experiments/zhihurec/eval.py`

原因：

- 当前仓库主链路依赖 raw-text 候选
- ZhihuRec 轨道依赖匿名 token 特征
- 两者在输入模态上并不相同

### 6.3 等研究结论稳定后，再决定 runtime integration

如果离线结果稳定优于当前通用 embedding 基线，再讨论：

- 是否增加新的 embedder 类型
- 是否增加新的 retriever
- 是否把双塔结果作为 `ScoreComponent` 之一接入排序

## 7. 一个更贴地的 MVP 版本

如果只允许做一个“2-3 周内可交付”的 MVP，我建议缩成下面这版：

### 里程碑 M1

- 读入 ZhihuRec-1M
- 做时间切分
- 产出标准训练样本和评测样本
- 跑通 popularity / mean-pooled token baseline

### 里程碑 M2

- 训练轻量双塔
- 加入 exposed-not-clicked hard negatives
- 在 ZhihuRec-1M 上完成离线评测

### 里程碑 M3

- 扩展到 ZhihuRec-20M
- 做消融实验：
  - 去掉 query 特征
  - 去掉 topic 特征
  - 去掉 hard negatives
  - 去掉行为序列，只保留最近点击

### 里程碑 M4

- 根据结果决定是否桥接到当前项目
- 如果桥接，优先做“训练范式迁移”或“蒸馏”，不要直接承诺权重复用

## 8. 我对原始计划的改写版

可以把原始计划改写成下面这段更准确的话：

> 我们不把 ZhihuRec 当成一个“能直接微调中文句向量模型的原始文本数据集”，而是把它当成一个“大规模匿名交互日志 + token/topic 特征数据集”。在这个前提下，我们先训练一个基于 token-space 的双塔协同检索模型，让用户行为序列、查询日志、答案 token 和 topic 特征在同一个向量空间里对齐。这个模型的第一职责是成为一个高质量的离线召回基线，用来验证协同行为和内容结构能否共同提升推荐质量。只有在这个基线被严格评测证明有效后，我们才进一步考虑把它蒸馏或迁移到当前 raw-text 推荐系统中。

## 9. 最后结论

如果问题是：

- “双塔协同语义检索，值不值得做？”

答案是：值得。

如果问题是：

- “能不能直接用开源 ZhihuRec 微调一个中文句向量模型，然后替换当前仓库的 embedding？”

答案是：不能这么表述，也不应该这么规划。

更好的说法是：

- ZhihuRec 双塔是一个强研究基线
- 当前 raw-text 系统是另一个运行轨道
- 两者之间需要一个明确的桥接阶段，而不是一句“训完就能上”
