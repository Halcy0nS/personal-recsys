# 00 - MVP Definition (TopN Recommendation)

## 1. Real-World Scenario

Target scenario for MVP:

- Input A: user collection articles (already saved by existing upstream processes).
- Input B: candidate recommendation pool for the same domain.
- Output: TopN ranked recommendations with explainable component scores.

Operational assumption:

- This MVP is a Python library workflow, not a service endpoint.
- Crawler modules (`datacrawl/`) are out of scope and remain unchanged.

## 2. User Stories

- As a product owner, I can generate a stable TopN recommendation list from collection + candidate pool.
- As an algorithm engineer, I can inspect per-item `i2i/tag/popularity` component scores.
- As a maintainer, I can refactor internals without breaking `PersonalRecSys` public methods.

## 3. Input/Output Boundaries

## 3.1 Required Inputs

- `collection_items: List[Dict]`
  - expected keys from current implementation: `title`, `content`, optional `url`, `source`, `timestamp`.
- `candidates: List[CandidateItem]`
  - required fields: `item_id`, `title`, `content`
  - optional: `tags`, `embedding`, `metadata`
- recommendation params:
  - `top_k`
  - `preset`
  - `custom_weights`
  - `min_score`

## 3.2 Required Outputs

- ranked result list (`RankedItem`) with:
  - `item_id`
  - `final_score`
  - `component_scores`
  - `rank`
- result metadata:
  - `total_candidates`
  - `filter_count`
  - `profile_summary`
  - `timing`

## 4. MVP In / Out

In scope:

- current dual-profile mechanism (implicit + optional explicit).
- current retrieval strategy (I2I + Tag).
- current ranking strategy (weighted presets).
- cache/load/save behavior already present in `PersonalRecSys`.
- regression baseline and acceptance docs for safe refactor.

Out of scope:

- LLM rerank/listwise ranking.
- HTTP service/API gateway.
- online feedback loop or reinforcement updates.
- crawler-side ingestion changes.

## 5. Success Criteria

## 5.1 Functional

- End-to-end flow runs with:
  - `python3 tests/test_basic.py`
  - `python3 example_usage.py`
- `PersonalRecSys` public signatures remain compatible.

## 5.2 Quality (Offline)

- Fixed eval split is required before implementation starts.
- Refactor target thresholds on fixed split:
  - `NDCG@10 >= baseline - 0.01`
  - `HitRate@10 >= baseline - 0.01`

## 5.3 Behavior Compatibility

- Required invariants:
  - no explicit profile -> tag fallback score `0.5`.
  - popularity source remains `metadata["popularity"]`.
  - preset names remain unchanged (`balanced/precision/exploration/quality`).
- Top10 stability check on fixed split:
  - Top10 overlap with baseline >= 90% unless documented by approved design change.

## 6. Non-Goals for This Phase

- No algorithmic uplift target in this phase (equivalence-first refactor prep).
- No new recommendation signals beyond currently implemented components.
