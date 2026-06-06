# ZhihuRec-1M 三步实验

## 目标

这组实验只回答三个问题：

1. 简单内容匹配是否已经足够有用
2. 历史序列建模是不是主矛盾
3. 两阶段精排是否值得继续重投入

## 口径

- 数据：`data/raw/zhihurec/1m/`
- 切分：按点击时间全局排序 `80/10/10`
- 主指标：`NDCG@10`、`Recall@10`
- masking：评测时屏蔽用户在训练集中已点击过的物品，但不屏蔽当前 target
- 模态：固定使用 `ZhihuRec` 原生 token-space，不假设有原始中文正文

## 实验

### Exp0

- 名称：`popularity`
- 作用：超弱对照，判断 Exp1 是否真的有增益

### Exp1

- 名称：`mean-pool`
- 物品表示：`info_answer.csv` token IDs -> `info_token.csv` 64d 词向量 -> mean pooling
- 用户表示：最近 20 次点击 answer embedding 的 mean pooling

### Exp2

- 名称：`SASRec`
- 输入：用户点击过的 answer ID 序列
- 目标：next-item prediction

### Exp3

- 名称：`two-stage`
- 一阶段：Exp2 的 `SASRec top50`
- 二阶段：轻量 `MLP reranker`
- 特征：`SASRec score`、`Exp1 cosine`、answer 基础统计量、topic overlap、candidate rank

## 入口

```bash
python3 scripts/experiments/zhihurec/prepare_split.py
python3 scripts/experiments/zhihurec/run_exp1_mean_pool.py
python3 scripts/experiments/zhihurec/run_exp2_sasrec.py
python3 scripts/experiments/zhihurec/run_exp3_two_stage.py
python3 scripts/experiments/zhihurec/report_summary.py
```

## 产物

统一写到 `data/experiments/zhihurec/`：

- `split_manifest.json`
- `splits/train.jsonl`
- `splits/val.jsonl`
- `splits/test.jsonl`
- `exp0_popularity/metrics.json`
- `exp1_mean_pool/metrics.json`
- `exp2_sasrec/metrics.json`
- `exp3_two_stage/metrics.json`
- `comparison_summary.json`

## 解释规则

- `Exp1 - Exp0`：内容表示是否有价值
- `Exp2 - Exp1`：历史序列建模是否关键
- `Exp3 - Exp2`：精排是否值得继续做重
