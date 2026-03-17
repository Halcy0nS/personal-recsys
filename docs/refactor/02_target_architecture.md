# 02 - Target Architecture

## 1. Design Goals

- Keep current recommendation behavior and public APIs stable.
- Make retrieval/ranking/profile stages explicitly replaceable.
- Centralize runtime settings into one config contract.
- Enable implementation phase without architecture-level decisions.

## 2. Target Layers

1. `PipelineOrchestrator`
   - composes builders/retrievers/ranker.
   - owns stage execution order and timing collection.
2. `ProfileBuilder` layer
   - implicit profile build path.
   - explicit profile build path.
3. `Retriever` layer
   - pluggable retrievers (I2I, Tag, future retrievers).
   - unified score output contract.
4. `Ranker` layer
   - consumes unified score contract.
   - outputs ordered items with component-level explainability.

## 3. Interface Contracts

## 3.1 PipelineConfig

Single config object with at least:

- `embedding_dim: int`
- `max_profile_items: int`
- `top_k: int`
- `preset: str`
- `custom_weights: Optional[Dict]`
- `min_score: Optional[float]`
- `batch_size: int`

Config precedence during implementation:

1. per-call explicit args
2. `PipelineConfig` defaults
3. module defaults

## 3.2 ProfileBuilder

Required contract:

- `build_implicit(collection_items) -> VectorCloud`
- `build_explicit(collection_items, llm_client) -> UserExplicitProfile | None`
- `summarize(vector_cloud, explicit_profile) -> Dict`

## 3.3 Retriever

Required contract:

- `name() -> str`
- `score(candidates, profile_ctx) -> Dict[item_id, float]`

Aggregator contract:

- `retrieve_all(...) -> Dict[item_id, Dict[component_name, score]]`
- missing scores default to `0.0`, except existing tag-fallback behavior when explicit profile absent.

## 3.4 Ranker

Required contract:

- `rank(item_scores, item_metadata, rank_config) -> List[RankedItem]`
- preserve component scores for explainability.

## 4. Public API Compatibility

`PersonalRecSys` remains external facade in implementation phase:

- same method names and required arguments.
- internal delegation is allowed, signature changes are not.
- return type of `recommend()` remains `RecommendationResult`.

## 5. Non-Goals in This Refactor Prep

- No LLM rerank/listwise ranking.
- No crawler-module changes.
- No feature-level behavior changes beyond structural decomposition.
