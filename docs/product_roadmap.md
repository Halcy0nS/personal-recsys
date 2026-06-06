# Product Roadmap

[简体中文](product_roadmap_zh.md)

## Purpose

This document is a long-term product roadmap for turning the current repository into a **local, single-user, interactive recommendation product**.

It is intentionally different from runtime documentation:

- `README.md` describes what the codebase can do today.
- `docs/PROJECT_STATUS.md` describes the current implementation and research status.
- This roadmap describes what we plan to build next, in what order, and why.

The roadmap is anchored in current code facts:

- the runtime recommendation core lives in `src/`
- the public engine entry point is `src.engine.PersonalRecSys`
- reranking and simulator evaluation capabilities already exist, but are still split across runtime code and evaluation utilities

## Product Goal

The long-term goal is not to accumulate more experiment scripts. It is to evolve the repository into a product with:

- a strong recommendation-quality core
- explainable results
- reusable rerank capabilities
- a local interactive workflow for a single user
- product-grade reliability for repeated use

The default planning assumptions are:

- local single-user first
- recommendation quality first
- interaction layer after the ranking core is credible
- no early commitment to multi-user service orchestration

## Guiding Principles

1. Product quality starts from recommendation quality.
2. Runtime capabilities should live in `src/`, not remain trapped in `src/evaluation`.
3. Evaluation tools stay valuable, but they serve product iteration rather than define the product itself.
4. Public APIs should evolve by additive changes whenever possible.
5. Documentation must distinguish clearly between current implementation and planned work.

## Phase 1: Recommendation Core Quality Foundation

Goal: make the main recommendation path a complete, stable, and explainable engine.

Primary work:

- align config priority and actual call-path behavior
- define the formal runtime boundaries of `recommend()`
- wire existing signals such as `min_score`, `popularity`, and candidate metadata more consistently
- implement real `RECENCY` and `DIVERSITY` scoring instead of leaving them as enum-only placeholders
- improve result explainability so each ranked item exposes a stable score breakdown

Success criteria:

- the main recommendation path runs end-to-end without depending on `src/evaluation`
- recommendation behavior is explainable and configuration changes are predictable
- script-based tests cover the dominant runtime behaviors

## Phase 2: Productize a General Rerank Slot

Goal: turn reranking into a first-class runtime extension point.

Primary work:

- define a general reranker abstraction in `src/contracts`
- standardize rerank result structures so pointwise and future RAG rerankers can share a runtime contract
- keep `PipelineOrchestrator` as the orchestration center
- let `PersonalRecSys` support additive reranker injection, switching, and debug inspection
- migrate verified rerank implementations from evaluation-oriented placement into runtime-appropriate modules

Success criteria:

- the default pointwise reranker can be enabled through the main engine path
- a candidate-aware RAG reranker can be plugged into the same runtime slot
- experiment scripts are no longer required just to attach reranking to the engine

## Phase 3: Turn Evaluation into Product R&D Infrastructure

Goal: keep research tools, but make them systematically useful for product iteration.

Primary work:

- keep and improve:
  - reranker stability analysis
  - order instability attribution
  - simulator Glicko2 and fixed-pair calibration
- make runtime outputs and evaluation inputs more compatible
- use evaluation outputs to answer product questions such as:
  - is a ranking change genuinely better?
  - is a new reranker unstable?
  - is an observed gain just judge noise?

Success criteria:

- major ranking changes can be compared with repeatable internal evaluation runs
- the team can distinguish quality gains from randomness or judge bias
- simulator outputs remain clearly labeled as internal synthetic evaluation artifacts

## Phase 4: Build the Single-User Interaction Loop

Goal: expose the recommendation engine through a real local workflow.

Primary work:

- support the key user loop:
  - import favorites
  - build and inspect profile
  - import candidate content
  - run recommendation
  - inspect recommendation explanations
  - optionally compare baseline vs reranked results
- start with a lightweight local interaction layer if needed
- optimize for clarity of user workflow, not for research-script flexibility

Success criteria:

- a non-developer can complete one full recommendation cycle without editing source files
- recommendation results and profile summaries are directly inspectable
- the product surface reflects real user tasks rather than experiment internals

## Phase 5: Product-Grade Reliability and UX Polish

Goal: make the local product stable, understandable, and repeatable.

Primary work:

- configuration management
- cache consistency
- progress visibility for long-running tasks
- logging and failure recovery
- clearer local data and artifact layout
- stronger setup and environment validation
- ongoing README and docs maintenance

Success criteria:

- cold start, repeat runs, and restart flows are reliable
- users can understand common failures without reading source code
- the repository docs describe both current behavior and supported workflows accurately

## Architecture Direction

The planned architecture direction is:

- `src.engine.PersonalRecSys` remains the main public entry point
- `src.pipeline.orchestrator.PipelineOrchestrator` remains the runtime orchestration hub
- `src.contracts` grows into a real contract layer for runtime requests, responses, and rerank abstractions
- `src/evaluation` remains an internal evaluation toolbox and should not become a runtime dependency for the product path

This means productizing validated ideas by moving or abstracting them into runtime code, instead of bypassing the engine with more one-off scripts.

## Near-Term Execution Priority

The roadmap order is intentional:

1. strengthen the recommendation core
2. productize rerank integration
3. standardize evaluation as product R&D support
4. add the local interaction loop
5. harden the product experience

If tradeoffs are needed, recommendation quality wins before UI polish, and runtime productization wins before broader experiment sprawl.
