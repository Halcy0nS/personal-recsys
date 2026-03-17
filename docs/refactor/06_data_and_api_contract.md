# 06 - Data and API Contract (Library-First)

## 1. Contract Scope

This document freezes data/API contracts for refactor implementation.

- API style: Python library API first.
- External facade remains `PersonalRecSys`.
- Contracts here define the normalized internal boundary for decomposition.

## 2. Core Contract Types

## 2.1 RecommendRequest

Logical request contract for recommendation call:

```python
RecommendRequest = {
  "top_k": int,                       # default 20
  "preset": str,                      # default "balanced"
  "custom_weights": Optional[Dict],   # default None
  "min_score": Optional[float],       # default None
}
```

Constraints:

- `top_k > 0`.
- `preset` must be one of existing preset names unless `custom_weights` is supplied.

## 2.2 RecommendResponse

Logical response contract aligned with `RecommendationResult`:

```python
RecommendResponse = {
  "ranked_items": List[RankedItem],
  "total_candidates": int,
  "filter_count": int,
  "profile_summary": Dict,
  "timing": Dict[str, float],
}
```

`ranked_items[i]` must include:

- `item_id: str`
- `final_score: float`
- `component_scores: Dict[str, float]`
- `rank: int`
- `metadata: Dict`

## 2.3 ProfileContext

Unified profile context passed between stages:

```python
ProfileContext = {
  "vector_cloud": Optional[VectorCloud],
  "explicit_profile": Optional[UserExplicitProfile],
  "summary": Dict,
}
```

## 2.4 ScoreMap

Unified score container for ranking:

```python
ScoreMap = Dict[str, Dict[str, float]]
# item_id -> {component_name -> score}
```

Rules:

- Missing component scores default to `0.0`.
- Exception: when explicit profile is absent, tag fallback remains `0.5` by existing behavior.

## 3. Existing API Mapping (Compatibility Bridge)

| Existing method | Logical contract mapping |
| --- | --- |
| `build_profile_from_collection(collection_items, llm_client, max_items)` | produces `ProfileContext` |
| `add_candidates(items)` + `embed_candidates(batch_size)` | prepares candidate feature source |
| `recommend(top_k, preset, custom_weights, min_score)` | consumes `RecommendRequest`, returns `RecommendResponse` |
| `save(path)` / `load(path)` | persistence of profile/cache metadata |

Compatibility policy:

- method names and required params stay unchanged.
- internal implementation can delegate through contract adapters.

## 4. Error Model

Expected errors to preserve:

- `ValueError` when collection items are empty.
- `ValueError` when recommendation runs without candidates.
- `ValueError` when recommendation runs without implicit profile.
- `ValueError` for unknown preset.
- `TypeError` in matcher when invalid profile object type is passed.

Error handling policy in refactor:

- preserve error types and trigger conditions unless explicitly approved.

## 5. Default Behavior Contract

Defaults to preserve:

- `recommend`: `top_k=20`, `preset="balanced"`, `custom_weights=None`, `min_score=None`
- `build_profile_from_collection`: `max_items=50`
- I2I matcher default inside engine path: `top_k=3`, `metric="cosine"`
- tag matcher default in engine path:
  - `positive_weight=1.0`
  - `negative_weight=-2.0`
  - `hard_filter_negative=True`

Data source contract:

- popularity score is read from `candidate.metadata["popularity"]` only.
