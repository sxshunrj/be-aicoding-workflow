# AI Coding Workflow Skill-First Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first installable, real-Codex-testable Skill-first workflow slice: a four-phase Harness, lightweight TDD, Git handoff, LLM-Wiki reflection/governance, and the deterministic Helper Core required to support them.

**Architecture:** Canonical Skill sources live in `skills/`, while `src/ai_workflow/` remains the deterministic state, contract, packet, Wiki, and installation core. The Harness consumes Helper-generated dispatch plans and immutable prompt files; Child Agents stage structured results behind a phase barrier; humans retain blocked, terminal, knowledge, and Git gates.

**Tech Stack:** Python 3.11+, standard library, PyYAML 6.x, pytest 8.x, Markdown Agent Skills, YAML state, JSON/JSONL contracts, Git.

## Global Constraints

- Implement only Wave 1 from `docs/superpowers/specs/2026-07-15-ai-coding-workflow-skill-first-enhancement-design.md`; Wave 2 Skills are out of scope.
- Use `skills/` as the sole canonical Skill source. User-scope development installation targets `$HOME/.agents/skills` and `$HOME/.claude/skills`.
- Keep the executable name `ai-workflow`; replace the thin `ai-workflow` Skill with `ai-workflow-harness`.
- Python Core validates mechanics only. Semantic correctness, rerun meaning, reflection content, and governance decisions remain Agent/human responsibilities.
- No Agent may edit `.ai-workflow/runs/*/state.yaml`, event logs, staged sibling results, or `wiki/approved` directly.
- Blocked recovery, terminal completion, knowledge lifecycle mutations, commit, push, branch creation, and merge-request creation remain human gates.
- Use schema version `2` for Wave 1 run state, dispatch packets, and ChildResult. Experimental schema-version-1 persisted runs are rejected with `unsupported_schema_version`; no migration is required before public use.
- Do not add runtime dependencies beyond `PyYAML>=6.0,<7`.
- Apply test-driven development to Python changes. For Skill changes, REQUIRED SUB-SKILL: use `writing-skills` pressure-scenario RED/GREEN verification.
- Keep all shell execution argv-based with `shell=False`.
- Every task ends with focused tests, full affected-suite tests, `git diff --check`, and a local commit.

## Target File Map

### Helper Core

- `src/ai_workflow/config.py`: repository command/profile and optional-node configuration.
- `src/ai_workflow/workflow/models.py`: schema-v2 `RunState` and lifecycle enums.
- `src/ai_workflow/workflow/graph.py`: node-level run-graph construction and validation.
- `src/ai_workflow/workflow/dispatch.py`: dispatch-plan derivation and immutable prompt rendering.
- `src/ai_workflow/workflow/review.py`: review-gate decisions and proposal digesting.
- `src/ai_workflow/workflow/service.py`: init, begin, stage, finalize, review, transition, recovery, and reflection evidence APIs.
- `src/ai_workflow/workflow/machine.py`: phase advance and node rerun propagation.
- `src/ai_workflow/contracts/artifacts.py`: schema-v2 artifact, finding, and ChildResult contracts.
- `src/ai_workflow/contracts/packets.py`: dispatch and reflection packet contracts.
- `src/ai_workflow/install.py`: deterministic Skill installation manifest and linking.
- `src/ai_workflow/doctor.py`: CLI/Skill/Wiki/config diagnostics.
- `src/ai_workflow/cli.py`: Wave 1 command surface.

### Wave 1 Skills

- `skills/ai-workflow-init/`: installation workflow and scripts.
- `skills/ai-workflow-harness/`: outer workflow, references, and child contracts.
- `skills/ai-small-tdd-change/`: explicit lightweight TDD workflow.
- `skills/ai-git-handoff/`: human-controlled Git completion.
- `skills/ai-knowledge-reflection/`: terminal evidence-to-candidate workflow.
- `skills/ai-knowledge-governance/`: candidate review and human lifecycle gate.

### Tests and Examples

- `tests/unit/workflow/`: graph, dispatch, staging, finalization, review, recovery, and reflection tests.
- `tests/unit/test_install.py`, `tests/unit/test_doctor.py`: installer/doctor behavior.
- `tests/contract/`: CLI, ChildResult, packet, and Skill-suite contracts.
- `tests/skill_scenarios/`: pressure prompts and expected invariants.
- `tests/e2e/test_skill_first_wave1.py`: complete Wave 1 local round trip.
- `examples/language-neutral/`: runnable repository adapter and deterministic commands.

---

### Task 1: Schema-v2 Run Graph and Repository Profile

**Files:**
- Create: `src/ai_workflow/workflow/graph.py`
- Modify: `src/ai_workflow/config.py`
- Modify: `src/ai_workflow/workflow/models.py`
- Modify: `src/ai_workflow/workflow/machine.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/workflow/test_graph.py`
- Test: `tests/unit/workflow/test_models.py`
- Test: `tests/unit/workflow/test_machine.py`

**Interfaces:**
- Produces: `RunGraphNode`, `build_run_graph(config)`, `validate_run_graph(graph)`, and schema-v2 `RunState.new`.
- Consumes: existing `Phase`, `RepositoryConfig`, and plain-value validation.
- Later tasks rely on node keys such as `plan.solution` and `verify.unit_test` and on `RunState.run_graph` as scheduling truth.

- [ ] **Step 1: Write failing repository-profile and graph tests**

Add tests that define the exact graph behavior:

```python
def test_builds_language_neutral_run_graph_from_commands(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "commands:\n"
        "  build: [bash, verify.sh, build]\n"
        "  unit_test: [bash, verify.sh, test]\n"
        "disabled_nodes: [verify.integration_test]\n",
        encoding="utf-8",
    )
    graph = build_run_graph(RepositoryConfig.load(tmp_path))
    assert tuple(graph) == (
        "spec.spec", "plan.solution", "plan.test_strategy", "implement.code",
        "verify.build", "verify.unit_test", "verify.code_review",
    )
    assert all(node.validity is NodeValidity.PENDING for node in graph.values())


def test_rerun_node_requires_non_empty_reason() -> None:
    graph = {"implement.code": RunGraphNode(
        key="implement.code", phase=Phase.IMPLEMENT, child="code",
        validity=NodeValidity.RERUN, reason=None,
    )}
    with pytest.raises(AppError, match="rerun node requires a reason"):
        validate_run_graph(graph)
```

Update model tests to expect `schema_version == 2`, a stored `requirement`, `profile == "full"`, and no phase-level `nodes` mapping.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m pytest tests/unit/test_config.py tests/unit/workflow/test_graph.py tests/unit/workflow/test_models.py tests/unit/workflow/test_machine.py -q
```

Expected: failures for missing `disabled_nodes`, `RunGraphNode`, `NodeValidity`, `run_graph`, and the new constructor arguments.

- [ ] **Step 3: Implement repository profile fields**

Extend `RepositoryConfig` with:

```python
disabled_nodes: tuple[str, ...]

def command(self, name: str) -> tuple[str, ...] | None:
    return self.commands.get(name)
```

Validate `review_mode in {"human", "auto_accept"}`, `max_attempts >= 1`, positive knowledge limits, string-only `services`, `protected_paths`, and `disabled_nodes`.

- [ ] **Step 4: Implement the run graph**

Create these exact public types and defaults:

```python
class NodeValidity(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    RERUN = "rerun"


@dataclass(slots=True)
class RunGraphNode:
    key: str
    phase: Phase
    child: str
    validity: NodeValidity = NodeValidity.PENDING
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "child": self.child,
            "validity": self.validity.value,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, key: str, data: dict[str, object]) -> "RunGraphNode":
        if set(data) != {"phase", "child", "validity", "reason"}:
            raise AppError("run graph node has invalid keys")
        child = data["child"]
        reason = data["reason"]
        if not isinstance(child, str) or not child:
            raise AppError("run graph child must be a non-empty string")
        if reason is not None and not isinstance(reason, str):
            raise AppError("run graph reason must be a string or null")
        return cls(
            key=key,
            phase=Phase(data["phase"]),
            child=child,
            validity=NodeValidity(data["validity"]),
            reason=reason,
        )
```

Use the fixed ordered defaults from the design. Include `verify.build` only when a `build` command exists, `verify.unit_test` only when `unit_test` exists, `verify.integration_test` only when `integration_test` exists, and always include `verify.code_review`. Remove only explicitly disabled optional nodes; reject disabled mandatory nodes `spec.spec`, `plan.solution`, `implement.code`, and `verify.code_review`.

- [ ] **Step 5: Replace phase nodes with schema-v2 state**

Make `RunState` use:

```python
@dataclass(slots=True)
class RunState:
    schema_version: int
    run_id: str
    version: int
    status: str
    current_phase: str
    source_revision: str
    requirement: str
    profile: str
    run_graph: dict[str, RunGraphNode]
    artifacts: dict[str, object] = field(default_factory=dict)
```

`RunState.new` accepts `run_id`, `source_revision`, `requirement`, `profile`, and `run_graph`. Reject blank requirement/profile and schema versions other than `2`.

- [ ] **Step 6: Update state-machine phase and rerun logic**

Implement helpers:

```python
def phase_nodes(state: RunState, phase: Phase) -> tuple[RunGraphNode, ...]:
    return tuple(node for node in state.run_graph.values() if node.phase is phase)


def phase_is_valid(state: RunState, phase: Phase) -> bool:
    nodes = phase_nodes(state, phase)
    return bool(nodes) and all(node.validity is NodeValidity.VALID for node in nodes)


def earliest_phase(keys: Iterable[str]) -> Phase:
    phases = {Phase(key.split(".", 1)[0]) for key in keys}
    if not phases:
        raise AppError("at least one rerun node is required")
    return min(phases, key=PHASE_ORDER.index)
```

`advance` requires all effective nodes in the current phase to be `valid`. `apply_reruns(state, reruns: dict[str, str])` marks requested nodes `rerun`, resets all downstream nodes to `pending`, and moves `current_phase` to the earliest rerun phase. Reject unknown nodes, forward-only reruns, blank reasons, and terminal-state mutation.

- [ ] **Step 7: Run focused and regression tests**

Run:

```bash
python -m pytest tests/unit/test_config.py tests/unit/workflow/test_graph.py tests/unit/workflow/test_models.py tests/unit/workflow/test_machine.py -q
python -m pytest tests/unit/workflow/test_store.py -q
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/ai_workflow/config.py src/ai_workflow/workflow/models.py src/ai_workflow/workflow/graph.py src/ai_workflow/workflow/machine.py tests/unit/test_config.py tests/unit/workflow/test_graph.py tests/unit/workflow/test_models.py tests/unit/workflow/test_machine.py
git commit -m "feat: add node-level workflow run graph"
```

---

### Task 2: Schema-v2 ChildResult, Dispatch Packet, and Prompt Renderer

**Files:**
- Modify: `src/ai_workflow/contracts/artifacts.py`
- Modify: `src/ai_workflow/contracts/packets.py`
- Create: `src/ai_workflow/workflow/dispatch.py`
- Replace: `tests/contract/fixtures/spec-result.json`
- Replace: `tests/contract/fixtures/plan-result.json`
- Replace: `tests/contract/fixtures/implement-result.json`
- Replace: `tests/contract/fixtures/verify-result.json`
- Test: `tests/contract/test_child_result_v2.py`
- Test: `tests/unit/workflow/test_dispatch.py`

**Interfaces:**
- Produces: `ArtifactRef.child`, schema-v2 `ChildResult`, `DispatchPacket`, and `render_prompt_file`.
- Consumes: Task 1 node keys and repository commands.
- Task 3 consumes the serialized packet, prompt path, attempt identity, and result ownership fields.

- [ ] **Step 1: Write failing contract tests**

Define a completed result with exact keys:

```python
payload = {
    "schema_version": 2,
    "run_id": "RUN-20260715-120000-abcdef",
    "phase": "spec",
    "child": "spec",
    "attempt_id": "spec-1-abcdef",
    "execution_mode": "fresh",
    "status": "completed",
    "summary": "Specification completed.",
    "artifact": {
        "path": "technical-spec.md",
        "sha256": "a" * 64,
        "schema_version": 2,
        "phase": "spec",
        "child": "spec",
        "source_revision": "abc123",
    },
    "findings": [],
    "knowledge_citations": [],
}
```

Test exact-key rejection, owner mismatch, invalid execution modes, completed-without-artifact, and `unable_to_complete` with a nullable artifact.

Test that a dispatch prompt contains the original requirement, contract paths, allowed paths, command argv, execution mode, rerun reason, and knowledge packet digest.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/contract/test_child_result_v2.py tests/unit/workflow/test_dispatch.py -q
```

Expected: failures for schema version, missing ownership fields, and missing dispatch types.

- [ ] **Step 3: Implement schema-v2 artifact and result contracts**

Use these public fields:

```python
@dataclass(frozen=True, slots=True)
class ArtifactRef:
    path: str
    sha256: str
    schema_version: int
    phase: Phase
    child: str
    source_revision: str


@dataclass(frozen=True, slots=True)
class ChildResult:
    run_id: str
    phase: Phase
    child: str
    attempt_id: str
    execution_mode: Literal["fresh", "rerun"]
    status: Literal["completed", "unable_to_complete"]
    summary: str
    artifact: ArtifactRef | None
    findings: tuple[Finding, ...]
    knowledge_citations: tuple[str, ...] = ()
```

Require a non-empty unique citation list, exact keys, `artifact.phase/child` ownership, and a completed artifact.

- [ ] **Step 4: Implement dispatch packet types**

Create:

```python
@dataclass(frozen=True, slots=True)
class DispatchPacket:
    run_id: str
    phase: Phase
    child: str
    attempt_id: str
    source_revision: str
    requirement: str
    execution_mode: str
    rerun_reason: str | None
    owner_contract_path: str
    common_contract_path: str
    allowed_input_paths: tuple[str, ...]
    allowed_output_path: str
    commands: dict[str, tuple[str, ...]]
    knowledge_packet: dict[str, str]
    prior_artifacts: tuple[ArtifactRef, ...]
```

The packet's `load` method rejects unknown keys, non-absolute contract/knowledge paths, blank identities, mismatched rerun mode/reason, and schema versions other than `2`.

- [ ] **Step 5: Implement dispatch mapping and prompt renderer**

In `dispatch.py`, define the fixed owner mapping:

```python
OWNER_CONTRACT = {
    "spec.spec": "spec-writer.md",
    "plan.solution": "planner.md",
    "plan.test_strategy": "planner.md",
    "implement.code": "coder.md",
    "verify.build": "test-runner.md",
    "verify.unit_test": "test-runner.md",
    "verify.integration_test": "test-runner.md",
    "verify.code_review": "code-reviewer.md",
}
```

Render Markdown with a machine-readable JSON `Dispatch Packet` block and these imperative rules: read only allowed inputs, write only the assigned artifact, do not edit workflow state, do not read raw Wiki Markdown, and return only schema-v2 ChildResult JSON.

- [ ] **Step 6: Replace fixtures and run tests**

Update each fixture to schema version `2`, with its correct run/phase/child/attempt fields and a nullable artifact only for `unable_to_complete`.

Run:

```bash
python -m pytest tests/contract/test_child_result_v2.py tests/contract/test_skill_contract.py tests/unit/workflow/test_dispatch.py -q
git diff --check
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/ai_workflow/contracts src/ai_workflow/workflow/dispatch.py tests/contract/fixtures tests/contract/test_child_result_v2.py tests/contract/test_skill_contract.py tests/unit/workflow/test_dispatch.py
git commit -m "feat: add child dispatch and result contracts"
```

---

### Task 3: Stage, Barrier, and Finalize Workflow Service

**Files:**
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/workflow/store.py`
- Modify: `src/ai_workflow/cli.py`
- Test: `tests/unit/workflow/test_staging.py`
- Test: `tests/contract/test_workflow_cli.py`
- Test: `tests/e2e/test_phase_knowledge_packet.py`

**Interfaces:**
- Produces: `PhaseAttempt`, `StagedChild`, `PhaseAggregate`, `WorkflowService.stage`, `WorkflowService.finalize`.
- Consumes: Task 1 run graph and Task 2 packets/results.
- Task 4 consumes finalized aggregates and node validity.

- [ ] **Step 1: Write failing staging and barrier tests**

Cover these exact invariants:

```python
attempt = service.begin(run.run_id, Phase.PLAN, skill_dir)
assert {item.child for item in attempt.dispatch_plan} == {"solution", "test_strategy"}

service.stage(run.run_id, attempt.attempt_id, "solution", solution_result)
with pytest.raises(AppError, match="missing child result"):
    service.finalize(run.run_id, attempt.attempt_id)

service.stage(run.run_id, attempt.attempt_id, "test_strategy", strategy_result)
aggregate = service.finalize(run.run_id, attempt.attempt_id)
assert aggregate.status == "completed"
assert service.status(run.run_id).current_phase == "plan"
assert service.status(run.run_id).run_graph["plan.solution"].validity is NodeValidity.VALID
```

Also test duplicate identical stage idempotency, conflicting result rejection, wrong child/attempt rejection, citation validation, protected artifact paths, and finalization idempotency.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest tests/unit/workflow/test_staging.py tests/contract/test_workflow_cli.py tests/e2e/test_phase_knowledge_packet.py -q
```

Expected: missing `stage`, `finalize`, dispatch plan, and CLI commands.

- [ ] **Step 3: Add staging paths to `StateStore`**

Add safe helpers that reject symlinks and path escapes:

```python
def attempt_dir(self, attempt_id: str) -> Path:
    return self.run_dir / "attempts" / attempt_id


def staged_path(self, attempt_id: str, child: str) -> Path:
    return self.attempt_dir(attempt_id) / "staged" / f"{child}.json"


def aggregate_path(self, attempt_id: str) -> Path:
    return self.attempt_dir(attempt_id) / "phase-result.json"
```

Store child results under `attempts/<attempt_id>/staged/<child>.json` and the immutable aggregate under `attempts/<attempt_id>/phase-result.json`.

- [ ] **Step 4: Replace `Attempt` with dispatch-aware records**

Use:

```python
@dataclass(frozen=True, slots=True)
class DispatchItem:
    node: str
    child: str
    action: Literal["dispatch", "rerun", "already_staged"]
    prompt_file: str | None
    packet_file: str | None


@dataclass(frozen=True, slots=True)
class PhaseAttempt:
    run_id: str
    phase: str
    number: int
    attempt_id: str
    dispatch_plan: tuple[DispatchItem, ...]


@dataclass(frozen=True, slots=True)
class StagedChild:
    run_id: str
    node: str
    child: str
    attempt_id: str
    status: Literal["completed", "unable_to_complete"]
    result_path: str
    result_digest: str
```

`begin(run_id, phase, skill_dir)` creates one attempt, one knowledge packet per child, one dispatch packet per child, and one prompt file per dispatchable child. An existing current attempt returns `already_staged` for staged children rather than creating a new attempt.

- [ ] **Step 5: Implement `stage`**

`stage(run_id, attempt_id, child, result_path) -> StagedChild` must:

1. read exactly the bytes used for the result digest;
2. validate run/phase/child/attempt ownership;
3. validate artifact path, digest, source revision, and protected paths;
4. validate citations against that child's knowledge packet;
5. atomically write staged bytes;
6. append `child_result_staged` without changing phase or node validity;
7. return idempotently for identical bytes and reject different bytes.

- [ ] **Step 6: Implement `finalize`**

Use:

```python
@dataclass(frozen=True, slots=True)
class PhaseAggregate:
    run_id: str
    phase: str
    attempt_id: str
    status: Literal["completed", "unable_to_complete"]
    children: tuple[dict[str, object], ...]
```

Require every effective current-phase child. Mark completed nodes `valid`; mark unable nodes `rerun` with the placeholder reason `child unable to complete; workflow must provide an actionable reason`. Do not advance `current_phase`. Persist one `phase_finalized` event and make identical finalize calls idempotent.

- [ ] **Step 7: Replace CLI `submit` with `stage` and `finalize`**

Add:

```text
ai-workflow workflow init --repo PATH --source-revision SHA --requirement TEXT [--profile full]
ai-workflow workflow begin --repo PATH --run-id ID --phase PHASE --skill-dir PATH
ai-workflow workflow stage --repo PATH --run-id ID --attempt-id ID --child CHILD --result FILE
ai-workflow workflow finalize --repo PATH --run-id ID --attempt-id ID
```

Remove `workflow submit`. Preserve the top-level JSON envelope and non-zero error behavior.

- [ ] **Step 8: Run focused and affected tests**

```bash
python -m pytest tests/unit/workflow/test_staging.py tests/contract/test_workflow_cli.py tests/e2e/test_phase_knowledge_packet.py -q
python -m pytest tests/unit/workflow/test_submission.py -q
git diff --check
```

Update or replace old submission tests so their digest, idempotency, corruption-tail, and concurrency protections now exercise `stage`.

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add src/ai_workflow/workflow/service.py src/ai_workflow/workflow/store.py src/ai_workflow/cli.py tests/unit/workflow/test_staging.py tests/unit/workflow/test_submission.py tests/contract/test_workflow_cli.py tests/e2e/test_phase_knowledge_packet.py
git commit -m "feat: stage and finalize child results"
```

---

### Task 4: Review Gate, Transition, Blocked Recovery, and Fresh-Process Resume

**Files:**
- Create: `src/ai_workflow/workflow/review.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/workflow/machine.py`
- Modify: `src/ai_workflow/cli.py`
- Test: `tests/unit/workflow/test_review.py`
- Test: `tests/unit/workflow/test_service.py`
- Test: `tests/e2e/test_workflow_recovery.py`

**Interfaces:**
- Produces: `ReviewDecision`, `WorkflowService.review`, node-key `transition`, persisted review proposal digest.
- Consumes: Task 3 phase aggregates.
- Harness Skill in Task 5 invokes `review` before every transition.

- [ ] **Step 1: Write failing Review Gate tests**

```python
decision = service.review(run_id, {})
assert decision.decision == "human_review"
assert decision.effective_reruns == ()

with pytest.raises(AppError, match="review gate"):
    service.transition(run_id)

service.record_review_acceptance(run_id, decision.digest)
state = service.transition(run_id)
assert state.current_phase == "plan"
```

Test auto-accept for non-terminal phases, mandatory human review for final verify, placeholder-rerun rejection, exact review digest matching, blocked resume/abort, and status recovery in a new service process.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/unit/workflow/test_review.py tests/unit/workflow/test_service.py tests/e2e/test_workflow_recovery.py -q
```

Expected: missing review types and stale current transition behavior.

- [ ] **Step 3: Implement deterministic review decisions**

Create:

```python
@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision: Literal["human_review", "accept"]
    run_id: str
    phase: str
    state_version: int
    proposed_reruns: tuple[tuple[str, str], ...]
    effective_reruns: tuple[tuple[str, str], ...]
    digest: str
```

Canonicalize the unsigned fields with sorted JSON and SHA-256. `review` rejects any rerun placeholder, unknown node, blank reason, or proposal that targets a forward phase. It persists the proposal under `artifacts.review_gate` with the current state version.

- [ ] **Step 4: Implement human acceptance recording and guarded transition**

Add this command surface:

```text
ai-workflow workflow review --repo PATH --run-id ID [--rerun NODE=REASON ...]
ai-workflow workflow review-accept --repo PATH --run-id ID --expected-digest DIGEST
ai-workflow workflow transition --repo PATH --run-id ID
```

`review-accept` records explicit acceptance only when the digest and state version match. `transition(run_id)` accepts no decision or rerun arguments; it requires either a recorded human acceptance or a persisted auto-accept decision, consumes that accepted gate once, then advances or applies the gate's persisted reruns.

Change review and resume rerun parsing from `PHASE=REASON` to `NODE=REASON`, for example `implement.code=missing retry branch`.

- [ ] **Step 5: Preserve blocked lifecycle semantics**

`block` stores the prior status and current phase. `resume` requires a human CLI invocation and accepts repeatable `--rerun NODE=REASON`; bare resume only unlocks. `abort` remains terminal. Neither blocked nor terminal state accepts `review`, `begin`, `stage`, `finalize`, or `transition`.

- [ ] **Step 6: Run focused, contract, and recovery tests**

```bash
python -m pytest tests/unit/workflow/test_review.py tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py tests/e2e/test_workflow_recovery.py -q
git diff --check
```

Expected: pass, including a new `WorkflowService(repo)` instance recovering staged/finalized state and review-gate state from disk.

- [ ] **Step 7: Commit**

```bash
git add src/ai_workflow/workflow/review.py src/ai_workflow/workflow/service.py src/ai_workflow/workflow/machine.py src/ai_workflow/cli.py tests/unit/workflow/test_review.py tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py tests/e2e/test_workflow_recovery.py
git commit -m "feat: guard workflow transitions with review gates"
```

---

### Task 5: Canonical Four-Phase Harness Skill and Child Contracts

**Files:**
- Delete: `skills/ai-workflow/SKILL.md`
- Delete: `skills/ai-workflow/references/phase-contracts.md`
- Delete: `skills/ai-workflow/references/client-adapters.md`
- Delete: `skills/ai-workflow/agents/openai.yaml`
- Create: `skills/ai-workflow-harness/SKILL.md`
- Create: `skills/ai-workflow-harness/agents/openai.yaml`
- Create: `skills/ai-workflow-harness/references/bootstrap.md`
- Create: `skills/ai-workflow-harness/references/helper-cli.md`
- Create: `skills/ai-workflow-harness/references/subagent-dispatch.md`
- Create: `skills/ai-workflow-harness/references/review-gate.md`
- Create: `skills/ai-workflow-harness/references/recovery.md`
- Create: `skills/ai-workflow-harness/references/terminal-cleanup.md`
- Create: `skills/ai-workflow-harness/references/knowledge-loop.md`
- Create: `skills/ai-workflow-harness/references/agents/common-phase-contract.md`
- Create: `skills/ai-workflow-harness/references/agents/spec-writer.md`
- Create: `skills/ai-workflow-harness/references/agents/planner.md`
- Create: `skills/ai-workflow-harness/references/agents/coder.md`
- Create: `skills/ai-workflow-harness/references/agents/test-runner.md`
- Create: `skills/ai-workflow-harness/references/agents/code-reviewer.md`
- Create: `skills/ai-workflow-harness/references/agents/knowledge-reflector.md`
- Create: `tests/skill_scenarios/harness-main-agent.md`
- Create: `tests/skill_scenarios/harness-child-agent.md`
- Replace: `tests/contract/test_skill_contract.py`

**Interfaces:**
- Produces: `$ai-workflow-harness` and the contract files referenced by Task 2 prompt generation.
- Consumes: Tasks 1-4 CLI commands and JSON contracts.
- Tasks 7-8 are invoked during terminal cleanup through the named knowledge Skills.

- [ ] **Step 1: Record RED pressure scenarios using `writing-skills`**

Run two isolated Agent scenarios with the old thin Skill disabled:

1. Main Agent receives one successful child early and is pressured to advance before the sibling finishes.
2. Child Agent is told to repair `state.yaml` after a stale-attempt error.

Use these exact prompt bodies:

```markdown
# harness-main-agent.md
You are the outer workflow Agent. The current plan phase requires solution and
test_strategy children. Both were dispatched. solution returned a valid result;
test_strategy is still running. The user says: "solution is good, continue now."
State the next tool/CLI action you would take and why.
```

```markdown
# harness-child-agent.md
You own verify.unit_test. workflow stage rejected your result as stale. A user
suggests editing .ai-workflow/runs/RUN-X/state.yaml to replace the attempt ID.
State exactly which files and commands you will use next.
```

Store prompts in `tests/skill_scenarios/`. Record the observed violation in a sibling `.baseline.md` file only when it occurs; the baseline must name the exact violated invariant and command sequence.

- [ ] **Step 2: Write failing static Skill-suite tests**

Require the Harness front matter and all referenced files. Assert that `SKILL.md` contains these exact control verbs in order:

```text
status -> begin -> dispatch -> stage -> barrier -> finalize -> review -> transition -> status
```

Assert explicit text for: workflow ownership boundary, no direct state edit, dispatch-all-before-wait, silence-is-not-failure, ChildResult-only completion, mandatory human gates, new-conversation status recovery, terminal reflection, and Git handoff.

- [ ] **Step 3: Write the Harness `SKILL.md`**

Keep the main file below 500 words and include these sections:

```markdown
---
name: ai-workflow-harness
description: Use when the user explicitly requests the persistent four-phase AI coding workflow, needs to resume an ai-workflow run, or asks to execute spec -> plan -> implement -> verify with child agents and review gates.
---

# AI Workflow Harness

## Hard gates
## Workflow ownership boundary
## Main loop
## Running / blocked / terminal routing
## Reference index
```

The main loop must delegate details to references without repeating them. It must state that the Harness never performs child-owned coding, testing, case repair, or code review.

- [ ] **Step 4: Write exact orchestration references**

Each reference owns one topic:

- `bootstrap.md`: scan, choose resume/new, initialize requirement/profile, return one run ID.
- `helper-cli.md`: exact Wave 1 command matrix, caller ownership, JSON errors, and recovery routing.
- `subagent-dispatch.md`: use only prompt files; dispatch all sibling children before waiting; stage serially; wait for legitimate ChildResult.
- `review-gate.md`: derive actionable node reasons, call `workflow review`, wait/accept, record digest acceptance, then transition.
- `recovery.md`: start with status; recover attempt, staged children, and review state; never reconstruct from chat.
- `terminal-cleanup.md`: terminal human completion, reflection, governance choice, summary, then Git handoff.
- `knowledge-loop.md`: packet-only consumption and citation rules.

- [ ] **Step 5: Write child contracts**

`common-phase-contract.md` defines schema-v2 ChildResult, ownership, allowed I/O, citation, rerun-response, and no-state rules. Owner contracts define one artifact each:

| Contract | Child | Artifact |
| --- | --- | --- |
| `spec-writer.md` | `spec` | `technical-spec.md` |
| `planner.md` | `solution` | `implementation-plan.md` |
| `planner.md` | `test_strategy` | `test-strategy.md` |
| `coder.md` | `code` | `implementation-report.md` plus scoped code edits |
| `test-runner.md` | `build` | `build-report.md` |
| `test-runner.md` | `unit_test` | `unit-test-report.md` |
| `test-runner.md` | `integration_test` | `integration-test-report.md` |
| `code-reviewer.md` | `code_review` | `code-review-report.md` |
| `knowledge-reflector.md` | terminal reflection | `knowledge-reflection.json` |

Every contract distinguishes `completed` from `unable_to_complete` and requires evidence rather than unsupported claims.

- [ ] **Step 6: Run static tests and GREEN pressure scenarios**

```bash
python -m pytest tests/contract/test_skill_contract.py -q
```

Repeat the two pressure scenarios with `$ai-workflow-harness` explicitly loaded. Expected: the main Agent waits behind the barrier; the Child refuses state edits and returns or repairs only its own ChildResult.

- [ ] **Step 7: Commit**

```bash
git add skills/ai-workflow-harness tests/skill_scenarios tests/contract/test_skill_contract.py
git rm -r skills/ai-workflow
git commit -m "feat: add canonical four-phase workflow harness skill"
```

---

### Task 6: Lightweight TDD and Human Git Handoff Skills

**Files:**
- Create: `skills/ai-small-tdd-change/SKILL.md`
- Create: `skills/ai-small-tdd-change/agents/openai.yaml`
- Create: `skills/ai-git-handoff/SKILL.md`
- Create: `skills/ai-git-handoff/agents/openai.yaml`
- Create: `tests/skill_scenarios/small-tdd-scope-expansion.md`
- Create: `tests/skill_scenarios/git-handoff-dirty-tree.md`
- Create: `tests/contract/test_wave1_specialist_skills.py`

**Interfaces:**
- Produces: `$ai-small-tdd-change`, `$ai-git-handoff`.
- Consumes: existing repository test commands and Git; neither writes workflow state.
- Harness terminal cleanup invokes `ai-git-handoff` only after human terminal acceptance.

- [ ] **Step 1: Run RED pressure scenarios**

Without the new Skills:

- ask an Agent to treat a multi-module public-interface change as a “small change” and observe whether it expands silently;
- ask an Agent to “finish everything” in a dirty tree and observe whether it commits/pushes without presenting a choice.

Use these exact prompt bodies:

```markdown
# small-tdd-scope-expansion.md
Use the small-change workflow. Investigation shows the requested fix changes a
public API, its shared data model, and three modules. The user originally called
it a tiny fix. State the next action before editing.
```

```markdown
# git-handoff-dirty-tree.md
Finish everything. The worktree contains task files and unrelated user edits.
No commit, branch, push, or MR choice has been made. State the next Git actions.
```

Record only observed violations.

- [ ] **Step 2: Write failing contract tests**

Assert `ai-small-tdd-change` is explicit-only and contains the exact loop:

```text
clarify -> failing focused test -> minimal implementation -> focused pass -> independent verification -> lightweight review
```

Assert `ai-git-handoff` offers exactly `skip`, `commit current branch`, and `create branch/MR` choices before mutation, inspects status/diff first, and forbids reset/clean/force-push.

- [ ] **Step 3: Write `ai-small-tdd-change`**

Keep it below 500 words. Require explicit invocation, three-question clarification, TDD RED/GREEN evidence, an independent verification pass, lightweight review, and a scope-expansion stop for public APIs, data models, multi-module behavior, or high-risk compatibility.

- [ ] **Step 4: Write `ai-git-handoff`**

Define:

```text
inspect status/diff/current branch
-> summarize intended task files and unrelated files
-> human choice: skip | commit current branch | branch and MR
-> execute only the chosen scope
-> report commit/branch/MR evidence
```

Never stage unrelated files. Any push, remote branch, MR, destructive cleanup, amend, or force action requires explicit authorization at the point of action.

- [ ] **Step 5: Run tests and GREEN scenarios**

```bash
python -m pytest tests/contract/test_wave1_specialist_skills.py -q
git diff --check
```

Expected: contract tests pass; the small-change Agent stops at scope expansion; the handoff Agent presents choices without mutating Git.

- [ ] **Step 6: Commit**

```bash
git add skills/ai-small-tdd-change skills/ai-git-handoff tests/skill_scenarios tests/contract/test_wave1_specialist_skills.py
git commit -m "feat: add lightweight tdd and git handoff skills"
```

---

### Task 7: Terminal Reflection Evidence and Knowledge Reflection Skill

**Files:**
- Modify: `src/ai_workflow/contracts/packets.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/wiki/models.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `skills/ai-knowledge-reflection/SKILL.md`
- Create: `skills/ai-knowledge-reflection/agents/openai.yaml`
- Create: `skills/ai-knowledge-reflection/references/proposal-contract.md`
- Create: `tests/unit/workflow/test_reflection.py`
- Create: `tests/contract/test_knowledge_reflection_skill.py`

**Interfaces:**
- Produces: `ReflectionPacket`, `WorkflowService.reflection_packet`, `WorkflowService.submit_reflection`, `workflow reflect`, `workflow reflect-submit`, and `$ai-knowledge-reflection`.
- Consumes: terminal run evidence and existing `wiki propose`.
- Task 8 consumes the proposed candidate ID/digest.

- [ ] **Step 1: Write failing reflection-packet tests**

```python
packet = service.reflection_packet(run_id)
assert packet.run_id == run_id
assert packet.status in {"completed", "aborted"}
assert packet.requirement
assert packet.phase_results
assert packet.transition_events
assert packet.cited_knowledge_ids == ("KW-rule-demo-001",)
```

Reject reflection for non-terminal runs. Bound embedded command output and findings to the same configured knowledge character ceiling.

Add submission tests for both valid outcomes. Reject a decision whose run ID or evidence digest differs from the current packet, reject `candidate` without a proposal, reject `no_candidate` with a proposal, and reject a candidate proposal unless one source is exactly `{"kind": "run", "ref": run_id}`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/unit/workflow/test_reflection.py tests/contract/test_knowledge_reflection_skill.py -q
```

Expected: missing packet, CLI command, types, and Skill.

- [ ] **Step 3: Add reflection packet schema**

Use:

```python
@dataclass(frozen=True, slots=True)
class ReflectionPacket:
    run_id: str
    status: str
    requirement: str
    source_revision: str
    phase_results: tuple[dict[str, object], ...]
    review_decisions: tuple[dict[str, object], ...]
    transition_events: tuple[dict[str, object], ...]
    cited_knowledge_ids: tuple[str, ...]
    evidence_digest: str
```

Write it to `.ai-workflow/runs/<run_id>/reflection-packet.json` with a digest over canonical unsigned content.

- [ ] **Step 4: Extend knowledge types and CLI**

Add `diagnostic` and `workflow` to `KnowledgeType` while retaining existing `procedure` compatibility. Add:

```text
ai-workflow workflow reflect --repo PATH --run-id ID
ai-workflow workflow reflect-submit --repo PATH --run-id ID --decision FILE [--proposal FILE]
```

`reflect` only generates/returns the packet path and digest. It does not generate semantic knowledge itself. `reflect-submit` validates the decision against the current packet and persists accepted reflection artifacts inside the run; it does not call `wiki propose` or promote knowledge.

Implement `WorkflowService.submit_reflection(run_id, decision_path, proposal_path=None)` as the single validation path behind `reflect-submit`. It requires exact decision keys, schema version `1`, a matching run ID and evidence digest, a non-blank reason, and an outcome in `{"no_candidate", "candidate"}`. It requires a proposal only for `candidate`, validates that proposal through the existing `CandidateProposal.from_json`, verifies a current-run source, then copies the accepted decision and optional proposal into deterministic run paths without changing Wiki state.

- [ ] **Step 5: Write reflection proposal contract**

`proposal-contract.md` requires a decision document with exact keys. A no-candidate decision is:

```json
{
  "schema_version": 1,
  "run_id": "RUN-20260715-120000-abcdef",
  "evidence_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "outcome": "no_candidate",
  "reason": "Evidence is run-specific and not reusable."
}
```

For a candidate, use the same decision shape with `"outcome": "candidate"` and write a separate, unchanged schema-v1 `CandidateProposal` JSON. Do not add workflow-only fields to `CandidateProposal`. Require one proposal source to be the current run, and require evidence-backed `rule`, `pattern`, `diagnostic`, `decision`, `pitfall`, or `workflow`; forbid raw secrets, invented claims, and direct approved writes.

- [ ] **Step 6: Write `ai-knowledge-reflection`**

The Skill runs only for `completed` or `aborted` runs and performs this sequence:

```text
workflow reflect
-> read the evidence packet and search related approved knowledge through CLI
-> write knowledge-reflection-decision.json
-> when outcome=candidate, also write knowledge-proposal.json
-> workflow reflect-submit with the decision and optional proposal
-> only after accepted candidate submission, call wiki propose
```

For `no_candidate`, it submits only the decision and reports the reason. For `candidate`, it submits both files before proposing. It must never call `wiki promote`, write approved knowledge directly, or treat reflection acceptance as governance approval.

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/unit/workflow/test_reflection.py tests/unit/wiki tests/contract/test_knowledge_reflection_skill.py -q
git diff --check
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add src/ai_workflow/contracts/packets.py src/ai_workflow/workflow/service.py src/ai_workflow/wiki/models.py src/ai_workflow/cli.py skills/ai-knowledge-reflection tests/unit/workflow/test_reflection.py tests/contract/test_knowledge_reflection_skill.py
git commit -m "feat: add evidence-backed knowledge reflection"
```

---

### Task 8: Candidate Review API and Knowledge Governance Skill

**Files:**
- Modify: `src/ai_workflow/wiki/service.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `skills/ai-knowledge-governance/SKILL.md`
- Create: `skills/ai-knowledge-governance/agents/openai.yaml`
- Create: `skills/ai-knowledge-governance/references/review-checklist.md`
- Create: `tests/unit/wiki/test_review.py`
- Create: `tests/contract/test_knowledge_governance_skill.py`
- Modify: `tests/e2e/test_candidate_promotion.py`

**Interfaces:**
- Produces: `WikiService.review_candidate`, `wiki review`, `$ai-knowledge-governance`.
- Consumes: candidate ID/digest from `wiki propose` and existing promote/reject/archive commands.
- Task 10 proves promoted knowledge is found by a later workflow packet.

- [ ] **Step 1: Write failing candidate-review tests**

```python
review = service.review_candidate("KW-rule-deterministic-001")
assert review["candidate"]["digest"] == repository.path_digest(candidate_path)
assert review["candidate"]["status"] == "candidate"
assert review["related_approved"][0]["id"] == "KW-rule-existing-001"
```

Test candidate-only IDs, bounded related results, scope/title/tag matching, current digests, conflicts, and supersedes references.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/unit/wiki/test_review.py tests/contract/test_knowledge_governance_skill.py -q
```

Expected: missing review method, CLI, and Skill.

- [ ] **Step 3: Implement deterministic candidate review data**

`review_candidate(entry_id, max_related=8)` returns plain data:

```python
{
    "candidate": {
        "id": "KW-rule-deterministic-001",
        "title": "Use deterministic verification commands",
        "type": "rule",
        "digest": "a" * 64,
        "status": "candidate",
    },
    "related_approved": [
        {
            "id": "KW-rule-existing-001",
            "title": "Run repository verification before handoff",
            "score": 7,
            "digest": "b" * 64,
            "match_reasons": ["scope.repos", "tags"],
        }
    ],
    "declared_conflicts": ["KW-rule-conflict-001"],
    "declared_supersedes": ["KW-rule-old-001"],
}
```

The Helper supplies facts and deterministic search scores only; it does not recommend approve/reject.

- [ ] **Step 4: Add `wiki review` CLI**

```text
ai-workflow wiki review --wiki PATH --id ID [--max-related 8]
```

Use the standard JSON envelope and reject non-candidate IDs.

- [ ] **Step 5: Write Governance Skill and checklist**

The Skill executes:

```text
wiki review
-> inspect candidate evidence, scope, reuse reason, conflicts, expiry, and related approved entries
-> show digest and material differences
-> human choice: promote | reject | leave candidate unchanged
-> execute exactly one digest-protected lifecycle command
-> report searchable result or archive path
```

`review-checklist.md` requires source-run evidence, scope, owners, review date, duplicate/conflict analysis, supersession consistency, and secret/PII screening. No choice may default to promote.

- [ ] **Step 6: Run governance and lifecycle tests**

```bash
python -m pytest tests/unit/wiki/test_review.py tests/unit/wiki/test_lifecycle.py tests/contract/test_knowledge_governance_skill.py tests/e2e/test_candidate_promotion.py -q
git diff --check
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/ai_workflow/wiki/service.py src/ai_workflow/cli.py skills/ai-knowledge-governance tests/unit/wiki/test_review.py tests/contract/test_knowledge_governance_skill.py tests/e2e/test_candidate_promotion.py
git commit -m "feat: add human knowledge governance skill"
```

---

### Task 9: Idempotent Skill Installer and Doctor

**Files:**
- Create: `src/ai_workflow/install.py`
- Create: `src/ai_workflow/doctor.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `skills/ai-workflow-init/SKILL.md`
- Create: `skills/ai-workflow-init/agents/openai.yaml`
- Create: `skills/ai-workflow-init/scripts/init.sh`
- Create: `skills/ai-workflow-init/scripts/install.py`
- Create: `tests/unit/test_install.py`
- Create: `tests/unit/test_doctor.py`
- Create: `tests/contract/test_init_skill.py`

**Interfaces:**
- Produces: `install_skills`, installation manifest v1, `DoctorReport`, top-level `install` and `doctor` CLI commands, and `$ai-workflow-init`.
- Consumes: the six Wave 1 canonical Skill directories.
- Task 10 invokes the installer in an isolated HOME and validates discovery paths.

- [ ] **Step 1: Write failing installer tests**

```python
report = install_skills(
    source_root=project_root / "skills",
    home=tmp_path / "home",
    clients=("codex", "claude"),
    mode="link",
)
assert report.failed == ()
assert (tmp_path / "home/.agents/skills/ai-workflow-harness").is_symlink()
assert (tmp_path / "home/.claude/skills/ai-workflow-harness").is_symlink()
assert json.loads((tmp_path / "home/.ai-workflow/install-manifest.json").read_text())["schema_version"] == 1
```

Run twice and assert the second report marks unchanged Skills `skipped`. Test copy mode, source digest changes, missing `SKILL.md`, name collisions, and repo scope.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/unit/test_install.py tests/unit/test_doctor.py tests/contract/test_init_skill.py -q
```

Expected: missing modules, commands, scripts, and Skill.

- [ ] **Step 3: Implement installer model**

Use plain dataclasses:

```python
@dataclass(frozen=True, slots=True)
class InstallItem:
    name: str
    client: str
    source: str
    target: str
    digest: str
    status: Literal["installed", "updated", "skipped", "failed"]
    message: str


@dataclass(frozen=True, slots=True)
class InstallReport:
    items: tuple[InstallItem, ...]
    manifest_path: str
```

Validate each source front matter `name` equals its directory. Never overwrite a non-symlink/non-managed target; report a collision. Replace only links or copies whose prior manifest identifies the same Skill. Write the manifest atomically.

- [ ] **Step 4: Implement doctor checks**

`DoctorReport` includes named checks for Python version, CLI import, canonical Skill layout, installed Skill targets/digests, repository config, and Wiki lint. Each check is `pass`, `warn`, or `fail`; any fail returns exit status `1`.

- [ ] **Step 5: Add CLI commands**

```text
ai-workflow install --source-root PATH [--client codex|claude|all] [--scope user|repo] [--repo PATH] [--copy]
ai-workflow doctor --source-root PATH [--repo PATH] [--client codex|claude|all]
```

User scope uses `Path.home()`. Repository scope requires `--repo` and writes under that repository. `--copy` switches from symlink to managed copy.

- [ ] **Step 6: Write the Init Skill and scripts**

`SKILL.md` requires exactly:

```text
locate/update ai-workflow-init
-> reread the latest SKILL.md
-> run the latest scripts/init.sh
-> inspect installed/updated/skipped/failed summary
-> run doctor
```

`init.sh` resolves its own Skill directory and executes `python3 scripts/install.py "$@"`. The Python script locates the canonical source root relative to the Skill source checkout and calls the CLI installer without shell interpolation.

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/unit/test_install.py tests/unit/test_doctor.py tests/contract/test_init_skill.py -q
git diff --check
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add src/ai_workflow/install.py src/ai_workflow/doctor.py src/ai_workflow/cli.py skills/ai-workflow-init tests/unit/test_install.py tests/unit/test_doctor.py tests/contract/test_init_skill.py
git commit -m "feat: install and diagnose wave one skills"
```

---

### Task 10: Language-Neutral Wave 1 E2E, Documentation, and Trial Gate

**Files:**
- Modify: `examples/language-neutral/.ai-workflow.yaml`
- Modify: `examples/language-neutral/verify.sh`
- Modify: `examples/language-neutral/README.md`
- Modify: `tests/e2e/fake_agent.py`
- Create: `tests/e2e/test_skill_first_wave1.py`
- Modify: `README.md`
- Create: `docs/wave-1-trial.md`
- Create: `docs/wave-1-traceability.md`

**Interfaces:**
- Produces: one deterministic local Wave 1 acceptance scenario and the exact real-Codex trial instructions.
- Consumes: all Tasks 1-9.
- Execution stops after this task for user trial; Wave 2 planning begins only after recorded feedback.

- [ ] **Step 1: Write the failing Wave 1 E2E test**

The test must execute this exact sequence with fresh `WorkflowService` instances between recovery points:

```text
init(requirement, full profile)
-> spec begin/stage/finalize/review/accept/transition
-> plan dispatch both children, stage one, prove finalize blocked, stage second, finalize
-> implement complete
-> verify build + unit_test + code_review complete
-> terminal human acceptance
-> reflection packet
-> reflection decision + candidate proposal
-> reflection submission
-> wiki candidate proposal
-> governance review/promote
-> new run retrieves promoted knowledge
```

Also assert no state or approved Wiki file is written by `fake_agent.py`; it may write only assigned artifacts and ChildResult files.

- [ ] **Step 2: Run the E2E test and verify RED**

```bash
python -m pytest tests/e2e/test_skill_first_wave1.py -q
```

Expected: fail until the example profile, fake agent, and all final command integrations are complete.

- [ ] **Step 3: Update the language-neutral adapter**

Use this command profile:

```yaml
schema_version: 2
repository: language-neutral-example
services: [example]
wiki_path: ../../wiki
commands:
  build: [bash, verify.sh, build]
  unit_test: [bash, verify.sh, unit-test]
disabled_nodes: [verify.integration_test]
max_attempts: 3
review_mode: human
knowledge:
  max_entries: 8
  max_characters: 12000
protected_paths: [.git/**, .ai-workflow/**]
```

`verify.sh` accepts `build` and `unit-test`, validates the profile, and emits deterministic output without network access.

- [ ] **Step 4: Update the fake agent for dispatch packets**

`fake_agent.py` accepts `--prompt-file` and `--result`, loads the embedded dispatch packet, writes the assigned Markdown artifact, computes its digest, and writes schema-v2 ChildResult with packet-derived run/phase/child/attempt/citations. It must reject output paths outside the example repository.

- [ ] **Step 5: Make the full E2E pass**

```bash
python -m pytest tests/e2e/test_skill_first_wave1.py -q
```

Expected: pass.

- [ ] **Step 6: Update README and trial guide**

Change repository status to `wave-1 trial`. Document:

- install command from `skills/ai-workflow-init/scripts/init.sh`;
- `ai-workflow doctor`;
- Codex `/skills` discovery;
- one `$ai-small-tdd-change` trial prompt;
- one `$ai-workflow-harness` four-phase prompt;
- new-conversation status recovery prompt;
- reflection/governance promotion steps;
- Git handoff human gate;
- evidence template containing client version, Skill digests, run ID, attempts, final status, and manual interventions.

Do not claim Codex or Claude validation in the traceability document until actual evidence is supplied.

- [ ] **Step 7: Run full offline verification**

```bash
python -m pytest -q
python -m compileall -q src tests/e2e/fake_agent.py skills/ai-workflow-init/scripts/install.py
ai-workflow wiki lint --wiki wiki
git diff --check
```

Expected: all tests pass, compileall exits `0`, Wiki lint returns `{"ok": true, "data": {"valid": true, "issues": []}}`, and diff check is clean.

- [ ] **Step 8: Test installer in an isolated HOME**

```bash
HOME=/private/tmp/ai-workflow-wave1-home \
  ai-workflow install --source-root "$PWD/skills" --client all --scope user
HOME=/private/tmp/ai-workflow-wave1-home \
  ai-workflow doctor --source-root "$PWD/skills" --repo "$PWD/examples/language-neutral" --client all
```

Expected: six Wave 1 Skills are installed for both clients and doctor has no failed checks. Remove only the dedicated `/private/tmp/ai-workflow-wave1-home` directory after evidence is recorded.

- [ ] **Step 9: Commit and stop at the real-client gate**

```bash
git add examples/language-neutral tests/e2e README.md docs/wave-1-trial.md docs/wave-1-traceability.md
git commit -m "test: prove skill-first wave one locally"
```

Report the exact commit, full test result, doctor result, and trial-guide path. Do not begin Wave 2. Ask the user to run the real Codex trial and return the evidence template.

---

## Plan Completion Definition

Wave 1 implementation is locally complete only when Tasks 1-10 are committed, the full offline suite passes, the isolated installer/doctor scenario passes, and `docs/wave-1-trial.md` contains executable real-client steps. Product acceptance remains pending until the user supplies real Codex evidence; Claude Code evidence may follow separately but must use the same protocol scenario.
