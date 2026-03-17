# 05 - Tech Stack and Project Structure

## 1. Technology Choices (Keep Current Core)

Primary stack remains unchanged for MVP refactor prep:

- Python runtime: existing local runtime (`python3`).
- Numerical ops: `numpy` (already required).
- Embedding providers: existing `BaseEmbedder` family (`mock/openai/local`).
- Retrieval strategy: current `I2IMatcher` + `TagMatcher`.
- Ranking strategy: current `ConfigurableScorer` + `WeightedScorer`.

Rationale:

- preserves existing behavior and tests.
- minimizes migration risk before structural refactor.
- keeps extension points where they already exist (embedders, score components, presets).

## 2. Target Internal Structure (Refactor-Ready)

Target structure for implementation phase (behavior-preserving):

```text
src/
  engine.py                    # external facade remains
  contracts/
    config.py                  # PipelineConfig and config defaults
    types.py                   # RecommendRequest/Response/ProfileContext/ScoreMap
    interfaces.py              # ProfileBuilder/Retriever/Ranker contracts
  pipeline/
    orchestrator.py            # stage orchestration and timing
  services/
    profile_builder.py         # wraps existing profiling logic
    retrieval_manager.py       # aggregates retriever outputs
    ranker_adapter.py          # wraps scorer behavior
  profiling/                   # existing implementations retained
  retrieval/                   # existing implementations retained
  ranking/                     # existing implementations retained
  utils/                       # existing implementations retained
```

Note:

- This is a target decomposition for coding phase.
- No business behavior changes are introduced by this structure itself.

## 3. Dependency Direction

Dependency rules (to enforce in implementation):

1. `contracts/*` has no dependency on business modules.
2. `profiling/retrieval/ranking` depend on contracts only when required.
3. `pipeline/orchestrator` depends on contracts + services.
4. `engine.py` depends on orchestrator/services as facade; external callers continue using `PersonalRecSys`.

Forbidden coupling:

- retrievers calling ranker internals directly.
- ranking layer reading profile objects directly (must receive normalized score map + metadata).
- contracts importing concrete implementations.

## 4. Extension Point Rules

Profile extension:

- New profile strategies must satisfy `ProfileBuilder` contract.

Retriever extension:

- New retriever returns `Dict[item_id, float]` under a unique component name.
- Aggregator is responsible for merge defaults and collision handling.

Ranker extension:

- Ranker accepts unified `ScoreMap` and metadata only.
- Ranker output must preserve explainability fields (`component_scores`).

## 5. Backward Compatibility Policy

- `PersonalRecSys` public methods remain source-compatible.
- Existing defaults are preserved unless explicitly approved:
  - `top_k=20`, `preset="balanced"`, `min_score=None`.
- Preset names and meaning are stable through this refactor cycle.
