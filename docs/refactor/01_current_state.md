# 01 - Current State

## 1. Runtime Pipeline (As-Is)

Current execution path is centered in `PersonalRecSys` (`src/engine.py`):

1. `build_profile_from_collection()`
2. `add_candidates()` + `embed_candidates()`
3. `recommend()`
   - `_compute_i2i_scores()` via `I2IMatcher`
   - `_compute_tag_scores()` via `TagMatcher`
   - weighted fusion via `ConfigurableScorer` + `WeightedScorer`
4. optional `save()/load()`

## 2. Module Responsibilities (As-Is)

- `src/profiling/implicit_profile.py`
  - `VectorCloud`: normalized vector storage, top-k similarity helper, JSON persistence.
- `src/profiling/explicit_profile.py`
  - `UserExplicitProfile`: explicit user preference schema.
  - `ProfileExtractor`: LLM-driven extraction with `chat()/complete()` client contract.
- `src/retrieval/i2i_matcher.py`
  - candidate-to-user-vector-cloud similarity scoring.
- `src/retrieval/tag_matcher.py`
  - positive/negative tag matching and hard-negative filtering.
- `src/ranking/scorer.py`
  - score normalization, weighted ranking, preset management.
- `src/utils/embeddings.py`
  - embedder factory (`mock/openai/local`), model-specific wrappers.

## 3. Coupling and Pain Points

- Orchestration, policy, and defaults are all inside `PersonalRecSys`; extension points are implicit.
- Config is spread across method params and constructor defaults; no single typed runtime config object.
- Retrieval outputs are produced in heterogeneous ways before ranking fusion.
- Ranking input shape is stable but not explicitly documented as a formal contract.
- Tests are script-style (`tests/test_basic.py`) and do not define contract-level regression assertions.

## 4. Behavioral Baselines to Preserve

- Public API surface of `PersonalRecSys` remains backward-compatible:
  - `build_profile_from_collection`
  - `add_candidates`
  - `embed_candidates`
  - `recommend`
  - `save`
  - `load`
- If explicit profile is missing, tag score falls back to `0.5`.
- Popularity score source remains `candidate.metadata["popularity"]`.
- Preset names and semantics remain:
  - `balanced`, `precision`, `exploration`, `quality`.
