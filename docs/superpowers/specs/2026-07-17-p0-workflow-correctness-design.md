# P0 Workflow Correctness and Checkpoint Design

**Date:** 2026-07-17  
**Status:** Approved design, pending written-spec review  
**Scope:** Profile-aware Grill execution, node-level recovery, immutable local Git checkpoints, repository-config versioning, and path authorization

## 1. Purpose

The repository already has a deterministic four-phase workflow core, immutable evidence, node-level rerun state, and human Review Gates. The highest-priority remaining gaps are correctness gaps rather than additional product surface:

- the `grill` profile is persisted but does not change the graph or starting phase;
- verification is not anchored to an immutable implementation snapshot;
- repository configuration declares a schema version that is not validated;
- protected-path matching is applied only to top-level names, so patterns such as `.git/**` do not exclude `.git`;
- Wave 2 conformance currently proves Skill installation and documentation, not the real three-phase lifecycle.

This design closes those gaps without embedding billing, Java, ByteDance CI, or Lark-specific behavior in the generic core.

## 2. Goals

1. Make `workflow init --profile full|grill` select a persisted graph and starting phase.
2. Make recovery restart at the earliest affected node rather than restarting the run.
3. Create an immutable local Git checkpoint after an accepted implementation result without moving `HEAD`, updating the business branch, modifying the user's index, or pushing.
4. Require every verification dispatch and result to reference the active checkpoint.
5. Validate repository configuration schema version and provide an explicit v1/missing-version to v2 migration command.
6. Enforce protected and adapter paths mechanically in dispatch authorization.
7. Prove the behavior through unit, contract, and end-to-end tests.

## 3. Non-Goals

- Do not add CI-provider, whitebox, Java, Maven, or Lark telemetry implementations in this batch.
- Do not change the user-visible business branch or push checkpoint refs.
- Do not include `.ai-workflow`, workflow artifacts, reports, logs, Git metadata, or unrelated pre-existing changes in checkpoint trees.
- Do not silently restart a run after state, schema, or checkpoint corruption.
- Do not refactor the complete `WorkflowService`; only extract the new checkpoint responsibility.
- Do not claim real-client reference parity until Codex and Claude Code trial evidence exists.

## 4. Profile-Aware Run Graph

The only supported profiles are `full` and `grill`. Unknown profiles fail with `invalid_profile`.

### 4.1 Full profile

The `full` profile keeps the current lifecycle and graph:

```text
spec.spec
-> plan.solution + plan.test_strategy
-> implement.code
-> verify.build + verify.unit_test + verify.integration_test + verify.code_review
```

Its initial phase is `spec`.

### 4.2 Grill profile

The `grill` profile uses this graph:

```text
plan.prd
-> implement.code
-> verify.build + verify.unit_test + verify.integration_test + verify.code_review
```

Its initial phase is `plan`. `plan.prd` is workflow-owned: the main Agent asks one question at a time and creates the PRD, while the Helper remains the only writer of persisted run evidence.

`workflow begin` reports `execution_kind=workflow_owned` for `plan.prd` and returns its allowed artifact destination. The Agent writes a temporary PRD outside `.ai-workflow/runs/**`, then imports it with:

```text
ai-workflow workflow stage-owned --repo REPO --run-id RUN --attempt-id ATTEMPT --phase plan --child prd --artifact FILE --summary TEXT
```

The Helper validates the artifact, copies it immutably, creates the staged result, and preserves the normal finalize/review/transition protocol. The Agent never edits run state or synthesizes a ChildResult.

The PRD contract requires stable `ISSUE-001` identifiers, vertical tracer-bullet slices, acceptance criteria, non-goals, repository scope, verification commands, and resolved or explicitly blocking open questions.

### 4.3 Persisted truth

The effective graph and initial phase are written at run creation. Resume and fresh-conversation recovery use only persisted state. They never rebuild an existing run from current configuration or from chat history.

## 5. Node-Level Recovery and Invalidation

Every rerun reason belongs to a concrete graph node. The state machine moves to the earliest affected phase and applies these rules:

- unaffected upstream nodes remain `valid`;
- requested nodes become `rerun` with non-empty actionable reasons;
- nodes in later phases become `pending`;
- unaffected siblings in the same phase remain reusable when their input anchor is unchanged;
- environment, permission, or tool failures become `blocked`, not business reruns.

Examples:

| Failure | Recovery |
| --- | --- |
| Integration-test case defect | Rerun only `verify.integration_test`; reuse unaffected verification siblings if the checkpoint is unchanged. |
| Verification finds an implementation defect | Rerun `implement.code`; preserve spec/plan; create a new checkpoint; invalidate all verification results tied to the old checkpoint. |
| PRD acceptance criteria change | Rerun `plan.prd`; invalidate implementation and verification. |
| Full-profile spec changes | Rerun `spec.spec`; invalidate every downstream node. |
| Environment failure | Persist `blocked`; human resume retries from the affected node. |
| Corrupt state or incompatible schema | Persist or report a fail-closed blocker; never create a replacement run silently. |

## 6. Immutable Local Git Checkpoint

### 6.1 Component boundary

Checkpoint mechanics live in a focused `workflow/checkpoint.py` service. `WorkflowService` coordinates lifecycle calls but does not implement Git plumbing.

The checkpoint service consumes:

- repository root;
- run and implementation attempt identity;
- source revision;
- implementation-attempt baseline;
- protected paths and effective checkpoint scope.

It produces a checkpoint record containing:

- checkpoint commit SHA;
- tree SHA;
- hidden ref name;
- source revision and parent commit;
- implementation attempt ID;
- included paths;
- previous checkpoint SHA, when present;
- creation timestamp.

### 6.2 Git plumbing

After the implementation Review Gate is accepted, the Helper:

1. verifies that `HEAD` and the business branch have not been moved unexpectedly;
2. computes the implementation-attempt change set;
3. selects the active checkpoint as the base anchor for an implementation rerun, or the source revision for the first implementation;
4. creates a temporary Git index outside the user's index;
5. populates that index from the base anchor and stages only the approved checkpoint paths;
6. runs `git write-tree`;
7. creates a commit with `git commit-tree`, using the base anchor as parent;
8. writes `refs/ai-workflow/checkpoints/<run_id>/<attempt_id>` to the commit;
9. activates the record in workflow state.

This writes local Git objects and a namespaced hidden ref only. It must not run ordinary `git commit`, move `HEAD`, update the current branch, alter `.git/index`, or push.

### 6.3 Scope and dirty-worktree safety

At `begin` for `implement.code`, the Helper records a baseline relative to the active checkpoint for a rerun or the source revision for the first implementation. Checkpoint scope contains paths changed by the implementation attempt relative to that baseline. Worktree content already represented by the active checkpoint is not treated as unrelated dirt during an implementation rerun.

Pre-existing unrelated dirty paths are excluded. If the implementation modifies a path that was already dirty at attempt start, ownership is ambiguous and checkpoint creation fails with `checkpoint_scope_ambiguous`; the run enters `blocked` for human resolution. This prevents the Helper from silently capturing user work.

The following are always excluded:

- `.git/**`;
- `.ai-workflow/**`;
- workflow artifacts, result files, generated prompts, temporary logs, and reports;
- configured protected paths;
- paths outside the repository;
- symlinks that escape the repository.

An empty implementation change set cannot produce a new checkpoint unless the active implementation result explicitly represents a no-code delivery. In that case the source revision itself is recorded as the checkpoint and no hidden ref is needed.

### 6.4 Verification anchoring

Verification cannot begin without an active checkpoint. To preserve the existing schema-v2 packet and ChildResult contracts, a verification `DispatchPacket.source_revision` is the active checkpoint commit rather than the original run source revision. The verification artifact's existing `ArtifactRef.source_revision` must copy that checkpoint commit. The active and previous checkpoint records remain persisted in workflow state.

The Helper validates the checkpoint during:

- verification `begin`;
- child-result `stage`;
- phase `finalize`;
- sibling-result reuse;
- transition and recovery reconciliation.

A mismatch returns `checkpoint_mismatch`. A missing or unreachable hidden ref returns `checkpoint_unavailable`. Both fail closed. Activating a new checkpoint resets every verification node to `pending`, including previously valid siblings, because they were verified against a different tree.

## 7. Repository Configuration and Path Authorization

### 7.1 Configuration schema

`.ai-workflow.yaml` must contain `schema_version: 2`. Missing, non-integer, or unsupported versions return `unsupported_schema_version` with an actionable hint.

The explicit migration command is:

```text
ai-workflow config migrate --repo REPO --to 2 [--dry-run]
```

It supports only missing-version or version-1 repository configuration, preserves existing keys and values, and changes only the schema declaration required for v2. `--dry-run` prints the proposed YAML without writing. The write path is atomic. Unknown future versions are never rewritten.

Persisted workflow state and ChildResult remain schema v2 in this batch; their existing strict validation is unchanged.

### 7.2 Path semantics

Path authorization operates on normalized repository-relative POSIX paths, not only top-level entry names.

The Helper:

- excludes `.git` and `.ai-workflow` unconditionally;
- applies `protected_paths` to both an entry and its descendants;
- rejects absolute paths, `..` traversal, repository escapes, and escaping symlinks;
- when adapter `source_paths` or `test_paths` are configured, includes only matching repository content as ordinary readable inputs; otherwise retains the current protected top-level fallback for compatibility;
- exposes mechanical authorization for specialist Skills through `ai-workflow config authorize-path --repo REPO --kind input|generated-test|report --path PATH`;
- authorizes generated-test paths only under `generated_test_destinations`;
- authorizes report paths only under `report_paths` or the Helper-owned run artifact destination.

The workflow dispatch path uses the same input authorizer. Specialist providers added in later batches must call the generated-test/report authorizer before writing. Adapter fields therefore become enforceable authorization data rather than prompt-only guidance without changing the schema-v2 DispatchPacket shape in this batch.

## 8. Error Handling

New stable error codes are:

| Code | Meaning | Required route |
| --- | --- | --- |
| `invalid_profile` | Profile is not `full` or `grill`. | Correct caller input; do not create state. |
| `unsupported_schema_version` | Repository config version is absent, invalid, or unsupported. | Run migration for v1/missing version or update configuration manually. |
| `checkpoint_scope_ambiguous` | Implementation changed a path already dirty at attempt start. | Block and request human resolution. |
| `checkpoint_creation_failed` | Git plumbing could not create the tree, commit, or ref. | Block with command evidence. |
| `checkpoint_unavailable` | Recorded commit/ref cannot be resolved. | Block; do not dispatch verification. |
| `checkpoint_mismatch` | Verification evidence references a different checkpoint. | Reject stale evidence and recover from current state. |
| `path_not_authorized` | Input or output is outside effective adapter/protected-path policy. | Reject the operation without widening scope. |

Errors use the existing JSON envelope. Skills route by `error.code`, not message text.

## 9. Test Strategy

All production changes follow red-green-refactor. The existing suite must remain green.

### 9.1 Unit tests

- full and grill graph construction and starting phase;
- rejection of unknown profiles;
- same-phase sibling reuse and downstream invalidation;
- implementation rerun invalidating old-checkpoint verification;
- temporary-index checkpoint creation;
- hidden-ref preservation;
- unchanged `HEAD`, branch, and user index;
- dirty-baseline ambiguity detection;
- protected-path descendant matching and unconditional Git/workflow exclusion;
- config v2 validation and migration dry-run/write behavior.

### 9.2 Contract tests

- workflow-owned PRD staging contract;
- checkpoint-anchor semantics in verification dispatch and ChildResult artifacts;
- active/previous checkpoint state shape;
- exact error codes and JSON envelopes;
- Grill Skill PRD issue and recovery language;
- migration CLI surface.

### 9.3 End-to-end tests

1. A Grill run starts at `plan.prd`, imports a PRD, implements, creates a checkpoint, verifies, and completes.
2. A verification finding reruns only one verification child and reuses unaffected siblings under the same checkpoint.
3. An implementation finding returns to `implement.code`, creates a new checkpoint, and reruns all verification children.
4. A fresh process restores the active checkpoint and continues without chat history.
5. A dirty overlapping path blocks checkpoint creation without moving the branch or user index.

### 9.4 Acceptance evidence

- all pre-existing tests pass;
- all new focused and end-to-end tests pass;
- Wiki lint and `git diff --check` pass;
- test evidence proves checkpoint creation did not move `HEAD`, alter the business branch, change the user's index, or push;
- no test claims real Codex or Claude Code parity without completed trial evidence.

## 10. Delivery Boundary

This P0 batch ends when profile-aware execution, node recovery, checkpoints, config migration, path authorization, and behavioral E2E are complete. CI-provider collection, integration-test providers, external telemetry exporters, repository CI/release automation, and broader `WorkflowService` decomposition remain separate follow-up batches.
