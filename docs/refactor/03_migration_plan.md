# 03 - Migration Plan

## 1. Strategy

Migration is **equivalence-first**:

1. extract contracts
2. move logic behind contracts
3. preserve old facade
4. verify parity at each step

No behavior-tuning work is included in this migration plan.

## 2. Execution Phases

## Phase A: Contract Introduction

- Add runtime config contract (`PipelineConfig`) and stage interfaces.
- Keep current code paths active; new contracts are introduced as wrappers/adapters.
- No output changes expected.

## Phase B: Internal Delegation

- Refactor `PersonalRecSys` internals to delegate:
  - profile build -> `ProfileBuilder`
  - retrieval -> retriever aggregator
  - ranking -> `Ranker` adapter
- Keep existing public methods unchanged.
- Expected output change: none.

## Phase C: Config Centralization

- Route existing defaults and per-call params through config precedence.
- Keep fallback behaviors identical to baseline.
- Expected output change: none.

## Phase D: Cleanup and Hardening

- Remove dead internal duplication once parity passes.
- Keep explainability fields and timing fields intact.

## 3. Rollback Plan

- Each phase lands in a separate commit.
- If parity fails in phase N:
  - rollback to previous phase commit.
  - retain docs and tests created before phase N.
- No schema/data migration is required; rollback is code-only.

## 4. Risk Controls

- Guard rails to preserve behavior:
  - explicit test for tag fallback (`0.5`) when explicit profile absent.
  - explicit test for popularity key source (`metadata[\"popularity\"]`).
  - explicit test for preset compatibility.
- Keep trace-level timing comparison before/after for smoke datasets.

## 5. Definition of Ready (Before Coding)

- Current-state, target-architecture, and acceptance docs approved.
- Baseline commands pass in current branch:
  - `python3 tests/test_basic.py`
  - `python3 example_usage.py`
- Cleanup and archive completed with restorable manifest.
