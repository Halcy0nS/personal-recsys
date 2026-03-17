# 07 - Implementation Path (Equivalence-First)

## 1. Delivery Principle

- Refactor sequence is contract-first and behavior-preserving.
- Each phase is shippable and revertible.
- No feature uplift work until equivalence gates pass.

## 2. Milestones

## M0 - Baseline Freeze

Deliverables:

- approved docs `00` through `07`.
- baseline command outputs captured:
  - `python3 tests/test_basic.py`
  - `python3 example_usage.py`
- fixed eval split artifact created and versioned (for NDCG/HitRate regression checks).

Exit criteria:

- baseline metrics and outputs are recorded as comparison anchor.

## M1 - Contract Scaffolding

Deliverables:

- add contract modules (`PipelineConfig`, interfaces, normalized type aliases).
- add adapter shims so existing code path remains active.
- no external API changes.

Exit criteria:

- all baseline commands pass with no behavior drift.

## M2 - Orchestration Decomposition

Deliverables:

- `PersonalRecSys` delegates profile/retrieval/ranking through orchestrator/services.
- `ScoreMap` is canonical intermediate format between retrieval and ranking.
- timing/reporting fields remain unchanged.

Exit criteria:

- public signatures remain compatible.
- compatibility invariants pass (fallback/preset/popularity-source checks).

## M3 - Config Centralization

Deliverables:

- route defaults through `PipelineConfig`.
- document precedence:
  1. per-call arg
  2. config value
  3. module default

Exit criteria:

- same results on fixed eval split within accepted tolerance.

## M4 - Hardening and Cleanup

Deliverables:

- remove dead duplicate logic introduced during migration.
- contract-level regression tests added for required invariants.
- update docs to reflect final internal architecture.

Exit criteria:

- all acceptance criteria in `04_acceptance_criteria.md` satisfied.

## 3. Risk and Rollback

Primary risks:

- subtle score drift from refactor-induced ordering/normalization differences.
- hidden default-value changes.
- compatibility breaks in user-facing method signatures.

Risk controls:

- phase-by-phase comparison against M0 baseline.
- mandatory compatibility checks:
  - tag fallback `0.5` when explicit profile missing.
  - preset compatibility.
  - popularity metadata source compatibility.

Rollback policy:

- one commit per milestone.
- if milestone gate fails, revert that milestone commit only.
- keep previous milestone artifacts and docs untouched.

## 4. Implementation Readiness Checklist

- contracts are decision-complete in docs.
- fixed eval split and baseline metrics are versioned.
- migration tasks are milestone-tagged before coding starts.
- no unresolved design decisions remain for implementers.
