# AI Coding Workflow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a language-agnostic, Skill-driven `spec -> plan -> implement -> verify` workflow with recoverable local state and a Git-native, human-reviewed LLM Wiki.

**Architecture:** Codex and Claude Code invoke a thin canonical Skill, while a Python 3.11+ CLI owns all deterministic workflow and Wiki mutations. Workflow state is stored in YAML plus an append-only JSONL event log; approved and candidate knowledge is stored as Markdown with YAML front matter and retrieved through deterministic scope and keyword matching.

**Tech Stack:** Python 3.11+, `argparse`, `dataclasses`, `pathlib`, `hashlib`, `json`, `PyYAML>=6.0,<7`, `pytest>=8,<9`, Git, Markdown, YAML.

## Global Constraints

- The core must run on Python 3.11 or newer.
- `PyYAML>=6.0,<7` is the only runtime dependency in the MVP.
- No vector search, network service, web UI, multi-tenant authorization, or cross-machine scheduler.
- Only the Python CLI may modify workflow state or Wiki lifecycle fields.
- Agents may create candidate knowledge only; promotion and rejection require explicit human commands.
- All CLI commands return a stable JSON envelope and use non-zero exit status for errors.
- Git Markdown/YAML files are authoritative; every future index must be rebuildable.
- Tests must not depend on network access.
- Implement each task with TDD and commit only after its focused and regression tests pass.

---

## Target File Map

```text
ai-coding-workflow/
├── pyproject.toml                       # package metadata, dependencies, CLI entry point, pytest config
├── README.md                            # installation and first-run guide
├── src/ai_workflow/
│   ├── __init__.py                      # package version
│   ├── cli.py                           # argparse command tree and JSON envelope boundary
│   ├── errors.py                        # typed user-facing errors and exit codes
│   ├── config.py                        # .ai-workflow.yaml loading and validation
│   ├── contracts/
│   │   ├── artifacts.py                 # artifact and child-result contracts
│   │   └── packets.py                   # phase and knowledge packet contracts
│   ├── workflow/
│   │   ├── models.py                    # run, node, and attempt domain models
│   │   ├── store.py                     # atomic YAML state and JSONL event persistence
│   │   ├── machine.py                   # legal state transitions and phase order
│   │   └── service.py                   # workflow use cases exposed to CLI
│   └── wiki/
│       ├── models.py                    # knowledge metadata and lifecycle models
│       ├── repository.py                # Markdown/front-matter IO and atomic moves
│       ├── search.py                    # deterministic filter, match, and ranking
│       └── service.py                   # lint, packet, propose, promote, reject, archive
├── skills/ai-workflow/
│   ├── SKILL.md                         # canonical portable orchestration Skill
│   └── references/
│       ├── phase-contracts.md            # Agent inputs/outputs for four phases
│       └── client-adapters.md            # Codex and Claude Code adaptation rules
├── wiki/
│   ├── approved/.gitkeep
│   ├── candidates/.gitkeep
│   ├── archive/.gitkeep
│   └── taxonomy.yaml
├── examples/language-neutral/
│   ├── .ai-workflow.yaml
│   ├── README.md
│   └── verify.sh
└── tests/
    ├── conftest.py
    ├── unit/
    ├── contract/
    └── e2e/
```

---

### Task 1: Package, JSON CLI Envelope, and Repository Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `src/ai_workflow/__init__.py`
- Create: `src/ai_workflow/errors.py`
- Create: `src/ai_workflow/config.py`
- Create: `src/ai_workflow/cli.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/contract/test_cli_envelope.py`

**Interfaces:**
- Produces: `RepositoryConfig.load(repo_root: Path) -> RepositoryConfig`
- Produces: `AppError(code: str, message: str, exit_status: int, details: dict[str, object])`
- Produces: `main(argv: Sequence[str] | None = None) -> int`
- Produces JSON envelopes: `{"ok": true, "data": ...}` and `{"ok": false, "error": {"code": ..., "message": ..., "details": ...}}`

- [ ] **Step 1: Write failing configuration and CLI contract tests**

```python
# tests/unit/test_config.py
from pathlib import Path

import pytest

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError


def test_loads_language_neutral_repository_config(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        """
schema_version: 1
repository: demo
services: [payments]
wiki_path: ../team-wiki
commands:
  build: [python, -m, compileall, src]
  test: [pytest, -q]
max_attempts: 3
review_mode: human
knowledge:
  max_entries: 8
  max_characters: 12000
protected_paths: [.git/**, .ai-workflow/**]
""".strip(),
        encoding="utf-8",
    )

    config = RepositoryConfig.load(tmp_path)

    assert config.repository == "demo"
    assert config.commands["test"] == ("pytest", "-q")
    assert config.wiki_path == (tmp_path / "../team-wiki").resolve()


def test_rejects_shell_string_commands(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "schema_version: 1\nrepository: demo\ncommands:\n  test: pytest -q\n",
        encoding="utf-8",
    )

    with pytest.raises(AppError, match="commands.test must be a list"):
        RepositoryConfig.load(tmp_path)
```

```python
# tests/contract/test_cli_envelope.py
import json

from ai_workflow.cli import main


def test_cli_errors_use_stable_json_envelope(capsys) -> None:
    status = main(["config", "show", "--repo", "/missing"])
    payload = json.loads(capsys.readouterr().out)

    assert status != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_not_found"
```

- [ ] **Step 2: Run the tests and verify the imports fail**

Run: `python -m pytest tests/unit/test_config.py tests/contract/test_cli_envelope.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ai_workflow'`.

- [ ] **Step 3: Add package metadata and minimal implementations**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-coding-workflow"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6.0,<7"]

[project.optional-dependencies]
dev = ["pytest>=8,<9"]

[project.scripts]
ai-workflow = "ai_workflow.cli:entrypoint"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

```python
# src/ai_workflow/errors.py
from dataclasses import dataclass, field


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    exit_status: int = 2
    details: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message
```

```python
# src/ai_workflow/config.py
from dataclasses import dataclass
from pathlib import Path

import yaml

from ai_workflow.errors import AppError


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    repository: str
    services: tuple[str, ...]
    wiki_path: Path
    commands: dict[str, tuple[str, ...]]
    max_attempts: int
    review_mode: str
    max_knowledge_entries: int
    max_knowledge_characters: int
    protected_paths: tuple[str, ...]

    @classmethod
    def load(cls, repo_root: Path) -> "RepositoryConfig":
        path = repo_root / ".ai-workflow.yaml"
        if not path.is_file():
            raise AppError("config_not_found", f"configuration not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        commands: dict[str, tuple[str, ...]] = {}
        for name, value in (raw.get("commands") or {}).items():
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise AppError("config_invalid", f"commands.{name} must be a list of strings")
            commands[name] = tuple(value)
        knowledge = raw.get("knowledge") or {}
        return cls(
            repository=str(raw["repository"]),
            services=tuple(raw.get("services") or ()),
            wiki_path=(repo_root / raw.get("wiki_path", "wiki")).resolve(),
            commands=commands,
            max_attempts=int(raw.get("max_attempts", 3)),
            review_mode=str(raw.get("review_mode", "human")),
            max_knowledge_entries=int(knowledge.get("max_entries", 8)),
            max_knowledge_characters=int(knowledge.get("max_characters", 12000)),
            protected_paths=tuple(raw.get("protected_paths") or ()),
        )
```

Implement `cli.py` with `argparse`, a `config show` command, and exactly one top-level JSON print. Catch `AppError` in `main`, serialize the error envelope, and return `error.exit_status`. `entrypoint()` must raise `SystemExit(main())`.

- [ ] **Step 4: Run focused tests and the installed CLI**

Run: `python -m pip install -e '.[dev]'`

Expected: installation succeeds.

Run: `python -m pytest tests/unit/test_config.py tests/contract/test_cli_envelope.py -q`

Expected: `3 passed`.

Run: `ai-workflow config show --repo examples/language-neutral`

Expected at this task: a JSON `config_not_found` error because the example config is created in Task 9.

- [ ] **Step 5: Commit the package and CLI boundary**

```bash
git add pyproject.toml src tests
git commit -m "feat: add workflow package and CLI envelope"
```

---

### Task 2: Workflow Domain Model and Atomic State Store

**Files:**
- Create: `src/ai_workflow/workflow/models.py`
- Create: `src/ai_workflow/workflow/store.py`
- Create: `tests/unit/workflow/test_models.py`
- Create: `tests/unit/workflow/test_store.py`

**Interfaces:**
- Produces: `Phase` enum with `SPEC`, `PLAN`, `IMPLEMENT`, `VERIFY`
- Produces: `NodeStatus` enum with `PENDING`, `RUNNING`, `VALID`, `RERUN`, `BLOCKED`
- Produces: `RunState.new(run_id: str, source_revision: str) -> RunState`
- Produces: `StateStore.create(state: RunState)`, `load() -> RunState`, `save(expected_version: int, state: RunState, event: Event)`
- Consumes: `AppError` from Task 1

- [ ] **Step 1: Write state round-trip, atomicity, and stale-write tests**

```python
# tests/unit/workflow/test_store.py
from pathlib import Path

import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import RunState
from ai_workflow.workflow.store import Event, StateStore


def test_state_round_trip_and_event_append(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = RunState.new("RUN-001", "abc123")
    store.create(state)

    loaded = store.load()
    loaded.status = "running"
    store.save(
        expected_version=0,
        state=loaded,
        event=Event(type="run_started", data={"phase": "spec"}),
    )

    assert store.load().version == 1
    assert '"type":"run_started"' in (store.run_dir / "events.jsonl").read_text()


def test_rejects_stale_state_write(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    store.create(RunState.new("RUN-001", "abc123"))
    current = store.load()
    store.save(0, current, Event(type="first", data={}))

    with pytest.raises(AppError, match="state version changed"):
        store.save(0, current, Event(type="stale", data={}))
```

- [ ] **Step 2: Verify the missing workflow modules fail**

Run: `python -m pytest tests/unit/workflow/test_models.py tests/unit/workflow/test_store.py -q`

Expected: FAIL with missing `ai_workflow.workflow` modules.

- [ ] **Step 3: Implement serializable models and atomic persistence**

Use string enums and dataclasses. `RunState` must contain `schema_version`, `run_id`, `version`, `status`, `current_phase`, `source_revision`, `nodes`, and `artifacts`. Create one node per formal phase.

```python
# src/ai_workflow/workflow/store.py
@dataclass(frozen=True, slots=True)
class Event:
    type: str
    data: dict[str, object]


class StateStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "state.yaml"
        self.events_path = run_dir / "events.jsonl"

    def save(self, expected_version: int, state: RunState, event: Event) -> None:
        current = self.load()
        if current.version != expected_version:
            raise AppError("stale_state", "state version changed; reload before writing", exit_status=4)
        state.version = expected_version + 1
        temporary = self.state_path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(state.to_dict(), sort_keys=False), encoding="utf-8")
        temporary.replace(self.state_path)
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": event.type, "version": state.version, "data": event.data}, separators=(",", ":")) + "\n")
```

Add explicit `to_dict` and `from_dict` methods; do not use unsafe YAML object serialization. `create` must fail if state already exists and must create an empty event log atomically.

- [ ] **Step 4: Run workflow model and persistence tests**

Run: `python -m pytest tests/unit/workflow/test_models.py tests/unit/workflow/test_store.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit workflow persistence**

```bash
git add src/ai_workflow/workflow tests/unit/workflow
git commit -m "feat: add recoverable workflow state store"
```

---

### Task 3: Workflow State Machine and Lifecycle Commands

**Files:**
- Create: `src/ai_workflow/workflow/machine.py`
- Create: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `tests/unit/workflow/test_machine.py`
- Create: `tests/contract/test_workflow_cli.py`

**Interfaces:**
- Produces: `WorkflowService.init(repo_root: Path, source_revision: str) -> RunState`
- Produces: `WorkflowService.begin(run_id: str, phase: Phase) -> Attempt`
- Produces: `WorkflowService.transition(run_id: str, accepted: bool, reruns: dict[Phase, str]) -> RunState`
- Produces: `WorkflowService.block(run_id: str, reason: str)`, `resume(run_id: str)`, `abort(run_id: str)`
- Consumes: `RepositoryConfig`, `StateStore`, `RunState`, `AppError`

- [ ] **Step 1: Write failing transition and CLI tests**

```python
# tests/unit/workflow/test_machine.py
import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.machine import StateMachine
from ai_workflow.workflow.models import Phase, RunState


def test_advances_only_after_current_node_is_valid() -> None:
    state = RunState.new("RUN-001", "abc123")
    machine = StateMachine()

    with pytest.raises(AppError, match="current node is not valid"):
        machine.advance(state)

    state.nodes[Phase.SPEC.value].status = "valid"
    machine.advance(state)
    assert state.current_phase == Phase.PLAN.value


def test_rerun_moves_back_to_earliest_invalid_phase() -> None:
    state = RunState.new("RUN-001", "abc123")
    for node in state.nodes.values():
        node.status = "valid"
    machine.apply_reruns(state, {Phase.IMPLEMENT: "verification found missing branch"})

    assert state.current_phase == Phase.IMPLEMENT.value
    assert state.nodes["implement"].status == "rerun"
```

- [ ] **Step 2: Run tests and verify the state-machine import fails**

Run: `python -m pytest tests/unit/workflow/test_machine.py tests/contract/test_workflow_cli.py -q`

Expected: FAIL with missing `StateMachine` or workflow CLI commands.

- [ ] **Step 3: Implement legal transitions and CLI commands**

`StateMachine.advance` must implement only this order:

```python
PHASE_ORDER = (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT, Phase.VERIFY)
```

It must reject advancing a non-valid node, advancing from `blocked`, skipping phases, and changing a terminal run. `apply_reruns` requires a non-empty reason for every target and selects the earliest target phase.

Add CLI commands:

```text
ai-workflow workflow init --repo PATH --source-revision SHA
ai-workflow workflow status --repo PATH --run-id ID
ai-workflow workflow begin --repo PATH --run-id ID --phase PHASE
ai-workflow workflow transition --repo PATH --run-id ID --accept
ai-workflow workflow block --repo PATH --run-id ID --reason TEXT
ai-workflow workflow resume --repo PATH --run-id ID
ai-workflow workflow abort --repo PATH --run-id ID
```

Run IDs use `RUN-YYYYMMDD-HHMMSS-<6 hex chars>`. Tests inject a clock and ID factory into `WorkflowService` so expected values remain deterministic.

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest tests/unit/workflow tests/contract/test_workflow_cli.py -q`

Expected: all workflow and CLI contract tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the state machine**

```bash
git add src/ai_workflow tests
git commit -m "feat: add workflow lifecycle state machine"
```

---

### Task 4: Artifact Contracts, Result Submission, and Recovery

**Files:**
- Create: `src/ai_workflow/contracts/artifacts.py`
- Create: `src/ai_workflow/contracts/packets.py`
- Create: `src/ai_workflow/workflow/runner.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `tests/unit/contracts/test_artifacts.py`
- Create: `tests/unit/workflow/test_runner.py`
- Create: `tests/unit/workflow/test_submission.py`
- Create: `tests/e2e/test_workflow_recovery.py`

**Interfaces:**
- Produces: `ArtifactRef(path: str, sha256: str, schema_version: int, phase: Phase, source_revision: str)`
- Produces: `ChildResult(status: Literal["completed", "unable_to_complete"], summary: str, artifact: ArtifactRef | None, findings: tuple[Finding, ...])`
- Produces: `PhasePacket(run_id, phase, attempt_id, source_revision, knowledge_packet, prior_artifacts, rerun_reason)`
- Produces: `WorkflowService.submit(run_id: str, attempt_id: str, result_path: Path) -> RunState`
- Produces: `CommandRunner.run(argv: tuple[str, ...], cwd: Path, timeout_seconds: int) -> CommandEvidence`
- Produces: `WorkflowService.summary(run_id: str) -> RunSummary`

- [ ] **Step 1: Write failing artifact and idempotency tests**

```python
# tests/unit/workflow/test_submission.py
def test_submit_accepts_matching_artifact_digest(service, run, tmp_path) -> None:
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path / "technical-spec.md"
    artifact.write_text("# Spec\n\nAcceptance: command exits zero.\n", encoding="utf-8")
    result_path = write_child_result(tmp_path, attempt, artifact, status="completed")

    first = service.submit(run.run_id, attempt.attempt_id, result_path)
    second = service.submit(run.run_id, attempt.attempt_id, result_path)

    assert first.nodes["spec"].status == "valid"
    assert second.version == first.version


def test_submit_rejects_changed_artifact(service, run, tmp_path) -> None:
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path / "technical-spec.md"
    artifact.write_text("original", encoding="utf-8")
    result_path = write_child_result(tmp_path, attempt, artifact, status="completed")
    artifact.write_text("changed after result", encoding="utf-8")

    with pytest.raises(AppError, match="artifact digest does not match"):
        service.submit(run.run_id, attempt.attempt_id, result_path)
```

```python
# tests/unit/workflow/test_runner.py
def test_command_runner_uses_argv_without_shell_and_bounds_output(tmp_path) -> None:
    evidence = CommandRunner(max_output_characters=20).run(
        (sys.executable, "-c", "print('x' * 100)"),
        cwd=tmp_path,
        timeout_seconds=5,
    )

    assert evidence.argv[0] == sys.executable
    assert evidence.exit_status == 0
    assert len(evidence.output) == 20
    assert evidence.output_truncated is True
```

- [ ] **Step 2: Verify submission tests fail**

Run: `python -m pytest tests/unit/contracts tests/unit/workflow/test_submission.py tests/unit/workflow/test_runner.py tests/e2e/test_workflow_recovery.py -q`

Expected: FAIL because artifact contracts and `submit` do not exist.

- [ ] **Step 3: Implement versioned contracts and idempotent submission**

Use JSON files for `PhasePacket` and `ChildResult`. Validate required keys and reject unknown `schema_version` values. Compute artifact digests by streaming file bytes through `hashlib.sha256`.

`submit` must:

1. load the current attempt and reject a different owner;
2. parse and validate the result contract;
3. validate artifact path, phase, source revision, and digest;
4. return the existing state without writing an event when the same digest was already accepted;
5. mark `completed` as `valid`;
6. mark `unable_to_complete` as `rerun` with a non-empty result summary;
7. append `result_submitted` and register the artifact.

Add `workflow submit --result PATH` and make `workflow begin` write and return the phase packet path.

Implement `CommandRunner` with `subprocess.run(list(argv), shell=False, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds)`. Return the exact argv, working directory, exit status, duration in milliseconds, bounded combined stdout/stderr, and an `output_truncated` flag. Convert timeout into `AppError(code="command_timeout", ...)` and never interpolate command strings through a shell.

Add `workflow summary --repo PATH --run-id ID`. `WorkflowService.summary` reads `events.jsonl` and derives phase durations, attempt count, rerun count, human Review Gate decisions, and cited knowledge IDs without mutating state.

- [ ] **Step 4: Prove recovery in a new service instance**

The end-to-end test must initialize a run, begin and submit Spec, discard the service object, create a new service from the repository path, load status, and begin Plan without relying on in-memory state.

Run: `python -m pytest tests/unit/contracts tests/unit/workflow/test_submission.py tests/unit/workflow/test_runner.py tests/e2e/test_workflow_recovery.py -q`

Expected: all tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit artifacts and recovery**

```bash
git add src/ai_workflow tests
git commit -m "feat: validate phase artifacts and resume runs"
```

---

### Task 5: Git Wiki Entry Schema, Repository, and Lint

**Files:**
- Create: `src/ai_workflow/wiki/models.py`
- Create: `src/ai_workflow/wiki/repository.py`
- Create: `src/ai_workflow/wiki/service.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `wiki/approved/.gitkeep`
- Create: `wiki/candidates/.gitkeep`
- Create: `wiki/archive/.gitkeep`
- Create: `wiki/taxonomy.yaml`
- Create: `tests/unit/wiki/test_models.py`
- Create: `tests/unit/wiki/test_repository.py`
- Create: `tests/contract/test_wiki_lint_cli.py`

**Interfaces:**
- Produces: `KnowledgeStatus`, `KnowledgeType`, `KnowledgeScope`, `KnowledgeEntry`
- Produces: `WikiRepository.list(status)`, `read(path)`, `write_candidate(entry)`, `move(entry_id, source, target)`
- Produces: `WikiService.lint() -> LintReport`
- Consumes: `AppError` and repository configuration

- [ ] **Step 1: Write failing schema and lint tests**

```python
# tests/unit/wiki/test_models.py
def test_rejects_approved_entry_without_reviewer() -> None:
    metadata = valid_metadata(status="approved")
    metadata["reviewers"] = []

    with pytest.raises(AppError, match="approved knowledge requires a reviewer"):
        KnowledgeEntry.from_parts(metadata, "# Rule\n\nBody")


def test_candidate_requires_run_evidence() -> None:
    metadata = valid_metadata(status="candidate")
    metadata["sources"] = []

    with pytest.raises(AppError, match="candidate knowledge requires a source"):
        KnowledgeEntry.from_parts(metadata, "# Rule\n\nBody")
```

- [ ] **Step 2: Run tests and verify Wiki imports fail**

Run: `python -m pytest tests/unit/wiki tests/contract/test_wiki_lint_cli.py -q`

Expected: FAIL with missing Wiki modules.

- [ ] **Step 3: Implement strict front-matter parsing and lint**

Parse only files beginning with `---\n`, split on the second delimiter, and use `yaml.safe_load`. Validate:

- stable ID pattern `KW-[a-z0-9-]+-[0-9]{3,}`;
- known type and status values;
- non-empty title, summary, owners, sources, and Markdown body;
- ISO dates and `review_after >= reviewed_at`;
- approved entries have reviewers and `reviewed_at`;
- candidate entries include a run or human source;
- referenced `supersedes` and `conflicts_with` IDs exist;
- IDs are unique across all lifecycle directories;
- file directory agrees with lifecycle status.

`wiki lint --wiki PATH` returns every issue in a stable list instead of stopping at the first invalid file. Exit status is zero only when `valid` is true.

Initialize `taxonomy.yaml` with allowed initial types and phases:

```yaml
schema_version: 1
types: [rule, decision, pattern, pitfall, procedure]
phases: [spec, plan, implement, verify]
```

- [ ] **Step 4: Run Wiki and full tests**

Run: `python -m pytest tests/unit/wiki tests/contract/test_wiki_lint_cli.py -q`

Expected: all tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the Git Wiki schema**

```bash
git add src/ai_workflow wiki tests
git commit -m "feat: add Git-native knowledge schema and lint"
```

---

### Task 6: Deterministic Search and Bounded Knowledge Packets

**Files:**
- Create: `src/ai_workflow/wiki/search.py`
- Modify: `src/ai_workflow/wiki/service.py`
- Modify: `src/ai_workflow/contracts/artifacts.py`
- Modify: `src/ai_workflow/contracts/packets.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `tests/unit/wiki/test_search.py`
- Create: `tests/unit/wiki/test_packets.py`
- Create: `tests/contract/test_wiki_search_cli.py`
- Create: `tests/e2e/test_phase_knowledge_packet.py`

**Interfaces:**
- Produces: `KnowledgeQuery(repository, services, paths, languages, phase, types, tags, text)`
- Produces: `SearchResult(entry, score: int, match_reasons: tuple[str, ...], warnings: tuple[str, ...])`
- Produces: `KnowledgeSearcher.search(query, limits) -> tuple[SearchResult, ...]`
- Produces: `WikiService.create_packet(query, output_path) -> KnowledgePacket`
- Produces: `ChildResult.knowledge_citations: tuple[str, ...]`
- Consumes: `KnowledgeEntry`, `KnowledgeScope`, `RepositoryConfig` knowledge limits

- [ ] **Step 1: Write failing ranking, exclusion, and size-limit tests**

```python
# tests/unit/wiki/test_search.py
def test_exact_scope_and_title_match_rank_first(entries) -> None:
    exact = entry("KW-rule-001", title="Payment retry", repos=["demo"], tags=["retry"])
    broad = entry("KW-rule-002", title="General reliability", repos=[], body="Payment retry")
    results = KnowledgeSearcher([broad, exact]).search(
        KnowledgeQuery(repository="demo", phase="implement", text="payment retry"),
        SearchLimits(max_entries=8, max_characters=12000),
    )

    assert [result.entry.id for result in results] == ["KW-rule-001", "KW-rule-002"]
    assert "repository:demo" in results[0].match_reasons


def test_candidates_are_never_returned_by_default(entries) -> None:
    candidate = entry("KW-rule-003", status="candidate", title="Payment retry")
    results = KnowledgeSearcher([candidate]).search(
        KnowledgeQuery(text="payment retry"),
        SearchLimits(max_entries=8, max_characters=12000),
    )
    assert results == ()
```

- [ ] **Step 2: Run tests and verify search is missing**

Run: `python -m pytest tests/unit/wiki/test_search.py tests/unit/wiki/test_packets.py tests/e2e/test_phase_knowledge_packet.py -q`

Expected: FAIL with missing search and packet interfaces.

- [ ] **Step 3: Implement deterministic scoring and packets**

Normalize text with Unicode case folding and whitespace tokenization. Use these fixed score components:

```text
exact repository/service/path/language/phase scope match: +40 each
tag exact match: +30
title token match: +20 per distinct query token
summary token match: +10 per distinct query token
body token match: +2 per distinct query token
broad empty scope: +1
```

Sort by descending score, then ascending knowledge ID. Exclude non-approved entries. Add warnings for `review_after` before today's injected clock date and for non-empty `conflicts_with`.

Build packets incrementally until either `max_entries` or `max_characters` would be exceeded. Serialize query, selected IDs, summaries, bounded relevant content, match reasons, warnings, paths, and a SHA-256 digest.

`workflow begin` must request a packet using repository defaults plus current phase, write it under the run's `knowledge-packets/`, and reference its path and digest from `PhasePacket`.

Extend `ChildResult` with `knowledge_citations`. Submission must reject IDs that were not present in the phase's knowledge packet, persist accepted citations in the artifact registry, and append them to the `result_submitted` event. This makes later knowledge usefulness analysis evidence-based.

- [ ] **Step 4: Run search, packet, end-to-end, and regression tests**

Run: `python -m pytest tests/unit/wiki/test_search.py tests/unit/wiki/test_packets.py tests/contract/test_wiki_search_cli.py tests/e2e/test_phase_knowledge_packet.py -q`

Expected: all tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit deterministic retrieval**

```bash
git add src/ai_workflow tests
git commit -m "feat: add cited and bounded knowledge retrieval"
```

---

### Task 7: Candidate Proposal and Human Knowledge Lifecycle

**Files:**
- Modify: `src/ai_workflow/wiki/models.py`
- Modify: `src/ai_workflow/wiki/repository.py`
- Modify: `src/ai_workflow/wiki/service.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `tests/unit/wiki/test_lifecycle.py`
- Create: `tests/contract/test_wiki_lifecycle_cli.py`
- Create: `tests/e2e/test_candidate_promotion.py`

**Interfaces:**
- Produces: `CandidateProposal.from_json(path: Path) -> CandidateProposal`
- Produces: `WikiService.propose(proposal_path: Path) -> KnowledgeEntry`
- Produces: `WikiService.promote(entry_id: str, reviewer: str, expected_digest: str) -> KnowledgeEntry`
- Produces: `WikiService.reject(entry_id: str, reviewer: str, reason: str, expected_digest: str) -> Path`
- Produces: `WikiService.archive(entry_id: str, reviewer: str, reason: str, expected_digest: str) -> Path`

- [ ] **Step 1: Write failing candidate safety and stale-approval tests**

```python
# tests/unit/wiki/test_lifecycle.py
def test_agent_proposal_is_written_only_to_candidates(service, proposal_path) -> None:
    entry = service.propose(proposal_path)
    assert entry.status == "candidate"
    assert (service.repository.candidates_dir / f"{entry.id}.md").is_file()
    assert not (service.repository.approved_dir / f"{entry.id}.md").exists()


def test_promote_rejects_stale_candidate_digest(service, candidate) -> None:
    stale_digest = candidate.digest
    candidate.path.write_text(candidate.path.read_text() + "\nchanged\n", encoding="utf-8")

    with pytest.raises(AppError, match="candidate changed since review"):
        service.promote(candidate.id, reviewer="alice", expected_digest=stale_digest)
```

- [ ] **Step 2: Run lifecycle tests and verify commands are missing**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py tests/contract/test_wiki_lifecycle_cli.py tests/e2e/test_candidate_promotion.py -q`

Expected: FAIL with missing lifecycle methods.

- [ ] **Step 3: Implement proposal, promotion, rejection, and archive**

Candidate proposal JSON must contain `schema_version`, `title`, `type`, `summary`, `body`, `scope`, `tags`, `sources`, `reuse_reason`, `confidence`, `possible_conflicts`, `suggested_owners`, and `review_after`. Reject empty evidence, raw logs over the configured size, and unsupported confidence values.

Generate candidate IDs from a normalized type/title slug plus a repository-wide sequence. `propose` always overwrites incoming status with `candidate` and writes only to `wiki/candidates`.

`promote` must verify the current digest, set status to `approved`, add reviewer and `reviewed_at`, validate all references, atomically move the file to `approved`, and return the new digest. `reject` moves the candidate to `archive` with status `archived` and an appended lifecycle note containing reviewer and reason. `archive` applies the same digest guard to approved entries.

Expose:

```text
ai-workflow wiki propose --wiki PATH --proposal FILE
ai-workflow wiki promote --wiki PATH --id ID --reviewer NAME --expected-digest SHA
ai-workflow wiki reject --wiki PATH --id ID --reviewer NAME --reason TEXT --expected-digest SHA
ai-workflow wiki archive --wiki PATH --id ID --reviewer NAME --reason TEXT --expected-digest SHA
```

- [ ] **Step 4: Run lifecycle and full regression tests**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py tests/contract/test_wiki_lifecycle_cli.py tests/e2e/test_candidate_promotion.py -q`

Expected: all tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the reviewed knowledge lifecycle**

```bash
git add src/ai_workflow tests
git commit -m "feat: add human-reviewed knowledge lifecycle"
```

---

### Task 8: Canonical Skill and Codex/Claude Contract Conformance

**Files:**
- Create: `skills/ai-workflow/SKILL.md`
- Create: `skills/ai-workflow/references/phase-contracts.md`
- Create: `skills/ai-workflow/references/client-adapters.md`
- Create: `tests/contract/fixtures/spec-result.json`
- Create: `tests/contract/fixtures/plan-result.json`
- Create: `tests/contract/fixtures/implement-result.json`
- Create: `tests/contract/fixtures/verify-result.json`
- Create: `tests/contract/test_skill_contract.py`

**Interfaces:**
- Produces: one portable `ai-workflow` Skill contract
- Produces: exact phase packet/result instructions for Codex and Claude Code
- Consumes: all CLI commands and JSON contracts from Tasks 1-7

- [ ] **Step 1: Write failing Skill conformance tests**

```python
# tests/contract/test_skill_contract.py
from pathlib import Path


def test_skill_never_instructs_agent_to_edit_state_directly() -> None:
    skill = Path("skills/ai-workflow/SKILL.md").read_text(encoding="utf-8")
    assert "Never edit state.yaml directly" in skill
    assert "ai-workflow workflow submit" in skill
    assert "ai-workflow wiki propose" in skill


def test_each_phase_fixture_parses_as_child_result() -> None:
    for path in sorted(Path("tests/contract/fixtures").glob("*-result.json")):
        result = ChildResult.from_json(path)
        assert result.status in {"completed", "unable_to_complete"}
```

- [ ] **Step 2: Run conformance tests and verify files are absent**

Run: `python -m pytest tests/contract/test_skill_contract.py -q`

Expected: FAIL with missing Skill or fixture files.

- [ ] **Step 3: Write the canonical Skill and phase contracts**

`SKILL.md` must define this exact control loop:

```text
status -> begin -> dispatch phase worker -> collect ChildResult -> submit
       -> derive rerun proposal -> human Review Gate -> transition -> status
```

It must state:

- the main Agent schedules and summarizes but does not perform phase work;
- `state.yaml` is never edited directly;
- workers receive only the generated phase packet and required artifacts;
- workers return a Child Result fixture-compatible JSON file;
- Wiki content is consumed only through packet paths;
- workers may propose candidates but never modify `wiki/approved`;
- blocked, final completion, promotion, and destructive Git actions require humans;
- a new conversation resumes by calling `workflow status` instead of reconstructing state from chat history.

`phase-contracts.md` gives exact responsibilities and artifact filenames:

```text
spec      -> technical-spec.md
plan      -> implementation-plan.md
implement -> implementation-report.md
verify    -> verification-report.md
```

`client-adapters.md` maps the common dispatch contract to Codex sub-agent calls and Claude Code task/agent calls without changing core semantics.

- [ ] **Step 4: Run Skill contract and full tests**

Run: `python -m pytest tests/contract/test_skill_contract.py -q`

Expected: all tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the Skill product surface**

```bash
git add skills tests/contract
git commit -m "feat: add portable AI workflow skill"
```

---

### Task 9: Language-neutral Example and Full MVP Acceptance Test

**Files:**
- Create: `examples/language-neutral/.ai-workflow.yaml`
- Create: `examples/language-neutral/README.md`
- Create: `examples/language-neutral/verify.sh`
- Create: `tests/e2e/fake_agent.py`
- Create: `tests/e2e/test_mvp_acceptance.py`
- Create: `README.md`

**Interfaces:**
- Produces: executable example that declares build/test commands only through configuration
- Produces: `FakeAgent.run(packet_path: Path) -> Path` for deterministic four-phase testing
- Verifies: all ten design acceptance criteria without network access

- [ ] **Step 1: Write the failing full acceptance test**

```python
# tests/e2e/test_mvp_acceptance.py
def test_complete_run_recovery_rerun_and_knowledge_growth(tmp_path, project_template) -> None:
    project = project_template.copy_to(tmp_path / "business-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)

    run = app.workflow_init(source_revision="abc123")
    for phase in ("spec", "plan", "implement"):
        packet = app.workflow_begin(run["run_id"], phase)
        app.workflow_submit(run["run_id"], agent.run(packet))
        app.workflow_transition(run["run_id"], accept=True)

    verify_packet = app.workflow_begin(run["run_id"], "verify")
    finding_result = agent.run(verify_packet, finding="implementation missing retry branch")
    app.workflow_submit(run["run_id"], finding_result)
    app.workflow_transition(
        run["run_id"],
        accept=True,
        reruns={"implement": "add the missing retry branch and tests"},
    )

    recovered = CliDriver(project).workflow_status(run["run_id"])
    assert recovered["current_phase"] == "implement"

    complete_remaining_phases(app, agent, run["run_id"])
    candidate = app.wiki_propose(agent.propose_knowledge(run["run_id"]))
    approved = app.wiki_promote(candidate["id"], candidate["digest"], reviewer="alice")
    results = app.wiki_search(text="retry branch", repository="business-repo")

    assert approved["status"] == "approved"
    assert approved["id"] in [item["id"] for item in results]
    assert app.workflow_status(run["run_id"])["status"] == "done"
```

- [ ] **Step 2: Run the acceptance test and verify missing harness helpers**

Run: `python -m pytest tests/e2e/test_mvp_acceptance.py -q`

Expected: FAIL because the example, fake Agent, and test CLI driver are not complete.

- [ ] **Step 3: Add the example, fake Agent, and user README**

Use this configuration shape:

```yaml
# examples/language-neutral/.ai-workflow.yaml
schema_version: 1
repository: language-neutral-example
services: [example]
wiki_path: ../../wiki
commands:
  build: [bash, verify.sh, build]
  test: [bash, verify.sh, test]
max_attempts: 3
review_mode: human
knowledge:
  max_entries: 8
  max_characters: 12000
protected_paths: [.git/**, .ai-workflow/**]
```

`verify.sh` accepts only `build` or `test`, performs deterministic local file checks, and exits non-zero for any other argument. `FakeAgent` reads the real phase packet and writes the corresponding real child result and Markdown artifact; it must not call an LLM.

The root README documents:

1. Python 3.11+ installation with `pip install -e '.[dev]'`;
2. copying and editing `.ai-workflow.yaml`;
3. invoking the Skill from Codex or Claude Code;
4. inspecting and resuming a Run;
5. linting and searching the Wiki;
6. reviewing and promoting a candidate with digest protection;
7. running the offline test suite.

- [ ] **Step 4: Run every acceptance and quality check**

Run: `python -m pytest tests/e2e/test_mvp_acceptance.py -q`

Expected: `1 passed`.

Run: `python -m pytest -q`

Expected: all tests pass.

Run: `ai-workflow wiki lint --wiki wiki`

Expected: JSON with `"ok": true` and `"valid": true`.

Run: `git diff --check`

Expected: no output and exit status 0.

- [ ] **Step 5: Commit the executable MVP**

```bash
git add README.md examples tests/e2e
git commit -m "test: prove AI workflow MVP end to end"
```

---

### Task 10: Final Specification Traceability and Release Verification

**Files:**
- Create: `docs/mvp-traceability.md`
- Modify: `README.md`
- Test: all files under `tests/`

**Interfaces:**
- Produces: requirement-to-test map for all ten MVP acceptance criteria
- Consumes: final CLI, Workflow, Wiki, Skill, and example interfaces

- [ ] **Step 1: Write the traceability document with exact evidence**

Create a table with columns `Criterion`, `Command or test`, and `Evidence`. Map every criterion in section 14 of the design to a named test or CLI command. Use exact test node IDs such as:

```text
tests/e2e/test_workflow_recovery.py::test_resume_from_persisted_state
tests/e2e/test_phase_knowledge_packet.py::test_phase_receives_bounded_cited_packet
tests/e2e/test_candidate_promotion.py::test_promoted_candidate_becomes_searchable
tests/e2e/test_mvp_acceptance.py::test_complete_run_recovery_rerun_and_knowledge_growth
```

- [ ] **Step 2: Run the complete release verification**

Run: `python -m pytest -q`

Expected: all tests pass with no skipped acceptance tests.

Run: `python -m compileall -q src tests/e2e/fake_agent.py`

Expected: no output and exit status 0.

Run: `ai-workflow wiki lint --wiki wiki`

Expected: JSON with `"ok": true` and `"valid": true`.

Run: `git diff --check`

Expected: no output and exit status 0.

- [ ] **Step 3: Manually verify both Skill adapters use the shared core**

Follow the Codex and Claude Code sections in `skills/ai-workflow/references/client-adapters.md`. For each client, start the language-neutral example, run through one phase, stop the conversation, open a new conversation, and call `workflow status`.

Expected for each client: the new conversation reports the persisted run ID, state version, and correct next phase without relying on chat history. Record the client version and result in `docs/mvp-traceability.md`.

- [ ] **Step 4: Update README status and run final repository inspection**

Change the README status from `Experimental design` to `MVP verified` only after Step 2 and Step 3 succeed. Then run:

Run: `git status --short`

Expected: only `README.md` and `docs/mvp-traceability.md` are modified or untracked.

- [ ] **Step 5: Commit the verified release evidence**

```bash
git add README.md docs/mvp-traceability.md
git commit -m "docs: record verified MVP acceptance"
```

---

## Completion Gate

Before declaring the MVP complete, verify all of the following:

- `python -m pytest -q` passes without network access.
- `python -m compileall -q src tests/e2e/fake_agent.py` succeeds.
- `ai-workflow wiki lint --wiki wiki` reports a valid Wiki.
- `git diff --check` produces no output.
- `docs/mvp-traceability.md` maps every design acceptance criterion to concrete evidence.
- Codex and Claude Code both resume the same protocol from persisted state.
- No Agent-facing instruction permits direct edits to `state.yaml` or `wiki/approved/`.
- The worktree contains no credentials, generated run directories, or unreviewed knowledge in `wiki/approved/`.
