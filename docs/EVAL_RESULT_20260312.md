# Pairwise Evaluation Result - 2026-03-12

## Summary

As of March 12, 2026, the current manual pairwise evaluation does **not** support replacing the baseline ranker with the current LLM reranker.

Current overall result:

- baseline wins more often than rerank
- rerank still shows useful upside on a small set of strong items
- the current reranker should be treated as an experimental enhancer, not the default main ranking policy

Short version:

- **overall stability:** baseline is better
- **best-case upside:** rerank is competitive, and sometimes better
- **current decision:** keep baseline as the safer default

## Evaluation Setup

This round used the blind comparison artifacts generated from the real-data run under `data/real_data_cache/`.

Compared systems:

- baseline ranking
- pointwise LLM rerank ranking

Evaluation method:

- manual pairwise preference judgment
- blind item presentation with title, summary, and URL
- result storage in:
  - `pairwise_decisions.json`
  - `pairwise_report.json`
  - `glicko2_ratings.json`

Important note:

This result set contains two pairwise protocols mixed together:

- `cross_system_full`: `99` comparisons
- `rank_aligned`: `10` comparisons

So the current report is a valid directional signal, but not yet a fully clean single-protocol benchmark.

## Main Result

From `pairwise_report.json`:

- total pairs decided: `109`
- baseline wins: `61`
- rerank wins: `46`
- ties: `2`
- rerank win rate: `0.4299`

Interpretation:

- rerank loses overall
- the gap is meaningful, but not so large that rerank is useless
- the system is not in a "rerank obviously improves everything" state

## Glicko-2 View

From `glicko2_ratings.json`, aggregated by source system:

### Baseline

- item count: `10`
- average rating: `1559.03`
- top-3 average rating: `1753.53`
- median-like score: `1539.34`

### Rerank

- item count: `10`
- average rating: `1432.45`
- top-3 average rating: `1779.76`
- median-like score: `1342.63`

Interpretation:

- baseline is stronger on average
- baseline is stronger in the middle of the ranked list
- rerank has a slightly higher top-end ceiling

This suggests the reranker is currently:

- capable of surfacing some very strong items
- but too unstable to improve the whole list consistently

## What This Probably Means

The current reranker is not failing because it never finds good articles.

It is failing because:

- it appears to over-promote some items based on shallow preference matches
- it lacks enough consistency across the whole ranked list
- it likely has a better upside than baseline on a few cases, but a worse average outcome

In practice, the current behavior looks like:

- **baseline:** lower variance, safer
- **rerank:** higher variance, occasionally better, often less reliable

## What This Evaluation Does Not Prove

This round does **not** prove any of the following:

- that LLM reranking is fundamentally bad for this project
- that the reranker prompt is already close to optimal
- that the LLM itself is the only bottleneck
- that Glicko-2 article ratings are already stable enough to be treated as long-term ground truth

This round only supports a narrower conclusion:

- **the current rerank implementation is not yet better than baseline in manual preference testing**

## Current Risks and Caveats

### Mixed evaluation protocol

The dataset contains both:

- old rank-aligned comparisons
- newer cross-system full comparisons

Future reporting should separate these or reset to a clean single protocol.

### Sparse notes

Most decisions were recorded without detailed notes.

This is fine for win/loss analysis, but it limits error taxonomy work:

- we know which side won
- we do not yet have enough structured evidence for why specific rerank failures happened

### Single-user evaluation

All judgments are from one user and reflect one real preference profile.

That is appropriate for this project, but the conclusion is necessarily personalized rather than population-level.

## Recommended Next Step

The next step should **not** be "replace baseline with rerank".

The next step should be:

1. keep baseline as the default output policy
2. treat rerank as an experimental module
3. run the next evaluation round under a clean single protocol
4. investigate why rerank has high upside but poor average consistency

Best immediate follow-up work:

- separate or reset the pairwise evaluation set so only `cross_system_full` results are counted
- collect a small number of high-quality notes on obvious rerank mistakes
- compare baseline vs rerank failure cases, not just final win rate
- test whether stronger candidate-aware evidence reduces rerank volatility

## Bottom Line

Current recommendation status on March 12, 2026:

- **baseline is the better default ranker**
- **rerank has promise, but is not ready to lead the final ranking**
- **the main open problem is quality consistency, not pipeline availability**
