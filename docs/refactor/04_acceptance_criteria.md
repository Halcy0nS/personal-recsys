# 04 - Acceptance Criteria

## 1. Environment and Workspace

- `datacrawl-refactor` is no longer under `personal-recsys/`.
- Git worktree still tracks `codex/zhihu-crawler-refactor`.
- `personal-recsys/datacrawl/` is untouched.

## 2. Cleanup Acceptance

- Archive exists at:
  - `/Users/salmon/Documents/python/personal-recsys/_archive/pre_refactor_<timestamp>/`
- `manifest.json` exists and includes:
  - source path
  - archived path
  - size
  - sha256 (for files)
  - archive timestamp
- Removed from recommendation core workspace:
  - `demo_cache/`
  - `demo_profile.json`
  - listed `__pycache__` directories
  - `.DS_Store` and `src/.DS_Store`

## 3. Regression Acceptance

Required commands must succeed:

- `python3 tests/test_basic.py`
- `python3 example_usage.py`

Behavior checks:

- `recommend()` returns ranked items and timing data.
- `PersonalRecSys` public method signatures remain compatible.
- Existing preset names remain usable.

## 4. MVP Acceptance (TopN Recommendation)

MVP scenario checks:

- Input from collection + candidate pool produces explainable TopN output.
- Output includes ranking scores, component breakdown, profile summary, and timing.
- API mode remains Python library first (no HTTP dependency required).

Offline quality gates on fixed eval split:

- `NDCG@10 >= baseline - 0.01`
- `HitRate@10 >= baseline - 0.01`

Behavior consistency gates:

- tag fallback is `0.5` when explicit profile is absent.
- popularity score source remains `candidate.metadata["popularity"]`.
- preset compatibility remains:
  - `balanced`
  - `precision`
  - `exploration`
  - `quality`

## 5. Contract Consistency Acceptance

Documented contracts must be complete and implementation-ready:

- `RecommendRequest`
- `RecommendResponse`
- `ProfileContext`
- `ScoreMap`

Compatibility requirement:

- `PersonalRecSys` method names/signatures are unchanged.
- internals may delegate via adapters/orchestrator only.

## 6. Refactor-Prep Docs Acceptance

All files exist under `docs/refactor/`:

- `00_mvp_definition.md`
- `01_current_state.md`
- `02_target_architecture.md`
- `03_migration_plan.md`
- `04_acceptance_criteria.md`
- `05_tech_stack_and_structure.md`
- `06_data_and_api_contract.md`
- `07_implementation_path.md`

Each must include:

- explicit contracts or behavioral baselines
- no unresolved architecture decisions for implementation
- rollback approach for migration work

## 7. Ignore Rules Acceptance

Repository-local ignore rules in `personal-recsys/.gitignore` include at least:

- `__pycache__/`
- `*.pyc`
- `.DS_Store`
- `demo_cache/`
- `demo_profile.json`
