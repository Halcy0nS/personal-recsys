# Personal RecSys - Current Project Status

Last updated: 2026-03-11

## 1. TL;DR

The project has moved past the prototype-only stage and now has a runnable end-to-end pipeline on real data:

- collection -> profile building -> coarse retrieval/ranking -> optional LLM rerank -> final output
- full candidate set is now supported in the real-data script
- candidate embeddings are cached to disk
- baseline vs rerank outputs can be exported for blind manual comparison

At the same time, the first real run shows that the main bottleneck is no longer "can the pipeline run", but "can the reranker actually understand user preference well enough to improve recommendation quality".

The current answer is: **not proven yet**.

## 2. What Is Implemented and Verified

### Runtime architecture

The current runnable chain is:

1. `PersonalRecSys` keeps public API stable
2. `PipelineOrchestrator` runs the stages
3. `DefaultProfileBuilder` builds:
   - implicit profile (`VectorCloud`)
   - explicit profile (`UserExplicitProfile`)
4. `RetrievalManager` aggregates:
   - `I2IRetriever -> I2IMatcher`
   - `TagRetriever -> TagMatcher`
5. `LLMReranker` can rerank coarse-ranked Top-N candidates
6. `DefaultRanker` performs final weighted fusion

### M5 capabilities now in place

- Reranker is integrated into the main pipeline through config
- `ScoreComponent.RERANK` is a first-class scoring component
- `run_real_data.py` no longer hard-limits candidates to 200
- candidate embeddings are cached in `data/real_data_cache/candidate_embeddings.npz`
- blind comparison artifacts are exported for manual evaluation

### Verified by local artifacts

The first full run produced these files under `data/real_data_cache/`:

- `vector_cloud.json`
- `explicit_profile.json`
- `candidate_embeddings.npz`
- `blind_comparison.json`
- `blind_comparison_answer_key.json`
- `comparison_report.json`
- `meta.json`

This confirms that the profile, full candidate embedding cache, and baseline/rerank comparison flow all completed at least once.

## 3. What the First Real Run Tells Us

### Data scale reached in the first run

Based on generated artifacts:

- implicit profile vector count: `50`
- profile embedding dimension: `1024`
- cached candidate embedding count: `1871`
- candidate count recorded in `meta.json`: `1871`

This means the current real-data script is already operating on the full deduplicated candidate pool, not the earlier capped subset.

### Explicit profile extracted in the first run

Current explicit profile snapshot:

- core topics:
  - `认知心理学`
  - `分布式系统`
  - `个人效率`
- writing style:
  - `深度长文`
  - `逻辑严密`
  - `案例丰富`
- negative tags:
  - `情绪输出`
  - `标题党`
  - `软广`

This profile is clean and plausible, but it is also clearly **compressed**. It captures part of the user's taste, not the full preference space.

### Baseline vs rerank behavior

From the exported comparison data:

- baseline Top-10 and rerank Top-10 overlap on only `3` items
- baseline-only items: `7`
- rerank-only items: `7`

This means reranking is not making small local adjustments. It is materially changing the final ranking.

That is useful, but it also means the reranker is strong enough to reshape outcomes before its quality is validated.

### Manual evaluation status

Current `comparison_report.json` says:

- total manual decisions: `0`
- conclusion: `No manual decisions recorded yet`

So the project has **comparison infrastructure**, but it does **not yet have evidence** that rerank is better than baseline.

## 4. Current Diagnosis

### What is working

- the engineering pipeline is now coherent
- the system can process the full candidate pool
- repeated runs should benefit from embedding cache reuse
- baseline and rerank outputs can be compared side by side

### What is not yet solved

The core unresolved problem is **recommendation judgment quality**, especially inside the reranker.

The main risk exposed by the first run is:

- the explicit profile is narrower than the user's actual preference space
- the reranker sees a compressed profile plus limited few-shot evidence
- as a result, it may perform shallow topic matching instead of true preference understanding

In practice, this means the system may incorrectly down-rank articles the user actually likes, especially when those articles match the user's deeper taste in:

- analysis style
- problem framing
- social/systemic reasoning
- intellectual tone

but do not directly match the small set of extracted `core_topics`

### Important interpretation

The current system should be described as:

- **content-based retrieval + profile-conditioned LLM rerank**

It should **not** be described as a mature RAG recommender, and it should not yet be described as a validated personalized ranking system.

The current reranker is also being used through a chat-style JSON scoring loop, not through a separately validated recommendation-specific evaluation setup.

## 5. What We Know About Product Readiness

### Ready enough for

- architecture iteration
- prompt iteration
- qualitative recommendation analysis
- blind comparison setup
- small-scale manual evaluation

### Not ready yet for

- claiming rerank improves recommendation quality
- claiming the LLM reliably understands user preference
- treating the current explicit profile as a complete representation of the user
- formal offline benchmark conclusions

## 6. Immediate Next Questions

The next stage should focus on research and validation, not just more pipeline wiring.

Highest-value questions:

1. Is the current failure mainly caused by weak user-preference representation?
2. Or is the LLM itself not strong enough at this kind of personalized ranking task?
3. Does candidate-aware evidence help more than better prompt wording?
4. In this project, should the LLM rank, summarize preference, or only explain results?

## 7. Recommended Next Step

The project is in a good state to begin a focused research phase:

- review LLM4Rec / LLM-as-a-Recommender literature
- use the exported blind comparison workflow to collect real manual judgments
- compare:
  - baseline ranking
  - current pointwise rerank
  - future candidate-aware rerank

The key goal is no longer "make rerank run". That goal has been met.

The key goal is now:

- **determine whether the LLM can actually serve as a reliable preference judge in this recommendation setting**
