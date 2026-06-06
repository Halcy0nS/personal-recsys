# 全文 vs 自适应压缩文本 Glicko2 实验

## 目的

这套实验框架用于评估 `user simulator` 在推荐场景中的离线稳定性，而不是把 LLM 输出定义为真人真值。

实验会从本地全文池中固定随机抽取 100 篇文章，分别构造两种输入视图：

- `fulltext`: 原始正文视图
- `compressed`: 自适应结构化压缩视图

随后使用同一套 pairwise simulator prompt 对两种视图分别执行 Glicko2 对局，输出独立排名、独立稳定性指标和成本统计。

在文档和报告中，应统一使用以下措辞：

- `simulator preference`
- `simulator ranking`
- `simulator win-rate`

不要把结果写成 `human preference ground truth`。

## 默认数据来源

默认样本池：

- `data/merged_content_inventory/fulltext_answers_merged_dedup.json`

这份文件是当前仓库中最稳定的全文候选池，包含去重后的长答案，适合做全文与压缩文本对照实验。

默认用户画像来源：

- `data/real_data_cache/explicit_profile.json`
- `datacrawl/zhihu_crawler/data/favorites_cjm926_all_20260305_150447.json`

这两份文件只用于构造 simulator persona，不用于样本抽样或标签对齐。

历史手工 Glicko 记录：

- 仅保留为历史背景
- 不参与这一轮 100 篇实验的样本选择
- 不与 simulator 对局结果混写

## 实验协议

### 1. 固定随机抽样

运行器会使用固定 seed 从默认样本池中抽取 100 篇文章，并把稳定快照保存到：

- `data/simulator_glicko/samples/sample_seed{seed}_n{size}.json`

快照会保留：

- `id`
- `title`
- `content`
- `url`
- `content_type`
- `voteup_count`
- `comment_count`

### 2. 自适应压缩缓存

每篇文章都会先经过一轮 `adaptive extraction`，产出结构化 JSON：

- `genre`
- `info_density`
- `compression_strategy`
- `core_claim`
- `key_points`
- `style_signals`
- `noise_level`

压缩缓存会按 `prompt version + extractor model + sample pool path` 做隔离，保存在：

- `data/simulator_glicko/compression_cache/<cache_key>/`

因此同配置重跑会命中缓存，不同配置不会 silently 覆盖旧结果。

### 3. Pairwise simulator

Pairwise judge 使用统一 persona 和统一输出协议。

两种视图的唯一差异是候选内容表示：

- `fulltext` 直接展示正文
- `compressed` 展示结构化压缩结果

judge 输出固定为一行 JSON：

```json
{
  "preferred": "A|B|tie",
  "confidence": 0.0,
  "reason": "20字内"
}
```

每场对局默认执行：

- `A/B`
- `B/A`

用于检测顺序偏差。若两次判断无法解析成同一胜者，则该场会被记为 `unstable`，不会写入 Glicko2 评分。

### 4. Glicko2 采样策略

运行器分两阶段调度：

第一阶段：`initial cover`

- 固定轮数随机覆盖
- 默认 `2` 轮
- 目标是让每篇文章至少获得基础曝光

第二阶段：`adaptive swiss`

- 优先选择 `RD` 高的文章
- 在候选对手中优先选择 rating 接近的文章
- 限制同一 pair 的重复次数

默认停止条件：

- 达到 `max_effective_matches`
- 或达到 `max_total_attempts`
- 或所有文章都达到最小曝光，且当前 `RD` 全部低于阈值

### 5. 报告与产物

每次运行会在：

- `data/simulator_glicko/runs/<run_name>/`

输出完整离线实验目录。核心文件包括：

- `config.json`
- `sample_snapshot.json`
- `adaptive_compressions.json`
- `fulltext/pairwise_matches.json`
- `fulltext/glicko2_ratings.json`
- `fulltext/report.json`
- `compressed/pairwise_matches.json`
- `compressed/glicko2_ratings.json`
- `compressed/report.json`
- `summary.json`

`summary.json` 应直接回答：

- 哪条路更稳定
- 哪条路 token 成本更低
- 两条路的 `top-k` 重叠有多少
- 是否有明显顺序偏差或解析失败

## Representation Caveats

`compressed` 视图不是文章本体，而是抽取后的结构化证据集合。

这意味着：

- `fulltext` 评估的是完整文章视图上的 simulator preference
- `compressed` 评估的是结构化证据视图上的 simulator preference

`compressed` 会天然削弱以下“文章性”因素：

- 文风
- 叙事节奏
- 全文结构感
- 情绪强度
- 行文张力

同时，它也可能引入新的表示偏差：

- 放大高信息密度文章的优势
- 低估依赖完整阅读体验的文章
- 继承 extractor 本身的抽取偏差

因此：

- 不应把 `compressed` 结果解释成完整文章偏好
- `fulltext` 与 `compressed` 的差异，应被解释为“表示变化导致的排序偏移”
- `summary.json` 中的 divergence 指标只用于描述两种视图之间的偏移，不表示哪条路更接近真人

推荐阅读顺序是：

1. 看各自视图下的 `report.json`
2. 再看总览 `summary.json` 中的 `top_k_overlap_rate`、`top_k_jaccard`、`shared_item_rank_gap_mean`
3. 最后结合 token 成本与 order flip rate 判断这条表示是否值得保留

## 运行方式

```bash
python3 run_simulator_glicko_experiment.py
```

常用参数示例：

```bash
python3 run_simulator_glicko_experiment.py \
  --sample-size 100 \
  --sample-seed 20260319 \
  --initial-cover-rounds 2 \
  --max-effective-matches 400 \
  --max-total-attempts 800
```

## 结果解释边界

这套框架适合用来：

- 比较 `fulltext` 与 `compressed` 哪种输入视图更稳定
- 粗筛不同 simulator prompt 或模型家族
- 做误差分析和压力测试

不适合直接用来证明：

- 某条排序就是用户真实偏好
- LLM 可以替代真人成为长期 ground truth
- 某种 rerank 策略已经在线上对真人更优
- `compressed` 比 `fulltext` 更“真实”

推荐做法是：

- 把这套结果当 `simulator arena`
- 在需要的时候，再用小规模真人锚点单独校验
