# P0 工作流正确性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 profile-aware Grill 执行、节点级恢复、不可变本地 Git checkpoint、配置 v2 迁移和机械路径授权，并以行为级 E2E 证明验证始终锚定到正确代码快照。

**Architecture:** `RepositoryConfig` 与新的 `RepositoryPathAuthorizer` 先建立统一的版本和路径策略；持久化 run graph 决定 full/grill 的有效 phase，状态机只从最早受影响节点恢复。独立的 `CheckpointService` 使用临时 Git index、`git write-tree`、`git commit-tree` 和命名空间 hidden ref 创建验证锚点，`WorkflowService` 只协调 baseline、Review Gate 激活、verification revision 和恢复校验。

**Tech Stack:** Python 3.11+、标准库、PyYAML 6.x、pytest 8.x、YAML/JSON/JSONL contracts、Git plumbing、Markdown Agent Skills。

## Global Constraints

- 以 `docs/superpowers/specs/2026-07-17-p0-workflow-correctness-design.md` 为唯一批准设计；CI provider、whitebox、Java、Maven、内部协作平台遥测和真实客户端 parity 不在本计划范围。
- 只支持 repository config `schema_version: 2`；缺失/v1 只能通过显式 migration 升级，未来版本必须 fail closed。
- Workflow state、DispatchPacket、ChildResult 和 ArtifactRef 继续使用现有 schema v2 字段集合；不得为 checkpoint 或 workflow-owned PRD 扩充这些 packet/result schema。
- 只支持 `full` 和 `grill` profile；full 从 `spec` 开始，grill 从 `plan.prd` 开始。
- Rerun 从最早受影响 phase 恢复：上游 valid 保留、目标节点 rerun、下游全部 pending、输入锚点不变的同 phase sibling 可复用。
- Checkpoint 只能写 Git object 和 `refs/ai-workflow/checkpoints/<run_id>/<attempt_id>`；不得移动 `HEAD`、更新 `refs/heads/**`、修改用户 index、执行 checkout/reset/switch、执行普通 `git commit` 或 push。
- `.git/**`、`.ai-workflow/**`、protected paths、repository escape、escaping symlink、workflow artifact/result/prompt/log/report 永远不进入 checkpoint。
- 所有 subprocess 调用使用 argv、固定 `cwd`、`shell=False` 和超时；不得拼接 shell command。
- 不增加 `PyYAML>=6.0,<7` 以外的运行时依赖，不修改 Python `>=3.11` 下限。
- Python 改动执行 red-green-refactor；Skill 改动执行 pressure/contract RED-GREEN；每个任务在 focused tests、受影响套件和 `git diff --check` 通过后单独 commit。
- 新增或修改的用户可见 Markdown 以中文叙述；CLI、字段、error code、node key 和 Git ref 等机器 contract 保持英文。
- 未完成真实 Codex/Claude Code trial evidence 前，测试、README 和 Skill 不得声明 real-client parity。

## Target File Map

### 配置与授权

- `src/ai_workflow/config.py`：repository config v2 校验、文本保持迁移和原子写入。
- `src/ai_workflow/path_authorization.py`：统一 normalized repository-relative POSIX path 授权与 internal checkpoint scope。
- `src/ai_workflow/cli.py`：`config migrate`、`config authorize-path` 和 `workflow stage-owned`。

### Graph、恢复与 staging

- `src/ai_workflow/workflow/models.py`：`WorkflowProfile` 和 profile-compatible persisted state。
- `src/ai_workflow/workflow/graph.py`：full/grill graph definition、initial phase 和 execution kind。
- `src/ai_workflow/workflow/machine.py`：effective phases、最早节点恢复和 downstream invalidation。
- `src/ai_workflow/workflow/store.py`：attempt-scoped workflow-owned artifact path。
- `src/ai_workflow/workflow/service.py`：profile init、workflow-owned PRD、checkpoint 生命周期与 phase-aware revision 协调。

### Checkpoint

- `src/ai_workflow/workflow/checkpoint.py`：baseline snapshot、临时 index、commit/ref、record reconciliation。
- `skills/ai-workflow-harness/references/agents/coder.md`：no-code delivery 保留 finding contract。

### Skill、文档与测试

- `skills/ai-workflow-harness-grill/`：真实 Grill 生命周期、PRD contract 和按节点恢复。
- `skills/ai-workflow-harness/references/helper-cli.md`：新增 Helper CLI surface。
- `skills/ai-integration-test-generator/`：三种 path authorization 的机械调用要求。
- `README.md`：full/grill、migration、checkpoint 和恢复行为。
- `tests/unit/`、`tests/contract/`、`tests/e2e/`：focused、contract 和 behavioral E2E 证据。

---

### Task 1: Repository Config v2 校验与文本保持迁移

**Files:**
- Modify: `src/ai_workflow/config.py`
- Modify: `src/ai_workflow/cli.py`
- Modify: `tests/unit/test_config.py`
- Create: `tests/contract/test_config_cli.py`
- Modify: 所有加载 `.ai-workflow.yaml` 的正常测试 fixture；仅 repository config 增加 `schema_version: 2`

**Interfaces:**
- Produces: `REPOSITORY_CONFIG_SCHEMA_VERSION = 2`、`RepositoryConfig.schema_version`、`ConfigMigrationResult`、`migrate_repository_config(repo_root: Path, to_version: int, *, dry_run: bool = False) -> ConfigMigrationResult`。
- Consumes: 现有 `AppError`、PyYAML 和 CLI JSON envelope。
- Later tasks rely on: 所有 service/config load 在进入 graph、path 或 checkpoint 逻辑前已经确认 repository config v2。

- [ ] **Step 1: 写 repository config version 与 migration 的失败测试**

在 `tests/unit/test_config.py` 增加参数化断言，正常 fixture 全部显式使用 v2：

```python
@pytest.mark.parametrize("value", [None, 1, 3, "2", 2.0, True])
def test_repository_config_rejects_missing_or_unsupported_schema_version(
    tmp_path: Path, value: object,
) -> None:
    payload: dict[str, object] = {"repository": "demo", "commands": {}}
    if value is not None:
        payload["schema_version"] = value
    (tmp_path / ".ai-workflow.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(AppError) as error:
        RepositoryConfig.load(tmp_path)
    assert error.value.code == "unsupported_schema_version"


def test_migrate_config_preserves_every_byte_except_schema_declaration(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".ai-workflow.yaml"
    original = "# repository policy\nschema_version: 1  # old\nrepository: demo\n"
    path.write_text(original, encoding="utf-8")
    result = migrate_repository_config(tmp_path, 2, dry_run=True)
    assert path.read_text(encoding="utf-8") == original
    assert result.content == original.replace("schema_version: 1", "schema_version: 2")
    assert result.written is False
```

再覆盖：缺失版本时只在文件首部插入一行；v2、未来版本和非整数来源均返回 `unsupported_schema_version` 且不写；实际迁移保留 mode 并通过同目录临时文件 `os.replace`。

- [ ] **Step 2: 运行 focused tests，确认 RED**

Run: `python -m pytest tests/unit/test_config.py -q`

Expected: FAIL，原因是 `schema_version` 未校验，且 migration API 不存在。

- [ ] **Step 3: 实现严格 v2 load 与文本保持 migration**

在 `config.py` 增加以下 public shape，并在读取 repository 字段前校验 version：

```python
REPOSITORY_CONFIG_SCHEMA_VERSION = 2

@dataclass(frozen=True, slots=True)
class ConfigMigrationResult:
    path: Path
    from_version: int | None
    to_version: int
    content: str
    written: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "from_version": self.from_version,
            "to_version": self.to_version,
            "written": self.written,
        }
```

迁移算法固定为：使用 `yaml.safe_load` 确认顶层 mapping 和来源只能为 missing 或 `type(value) is int and value == 1`；同时使用 `yaml.compose` 找到唯一顶层 `schema_version` value node 的 `start_mark.index:end_mark.index`。Missing 时保留原换行风格并在字符 0 插入 `schema_version: 2`；v1 时仅把该 source span 替换为字符 `2`，因此 key 顺序、空白、注释和其他全部字符不变。重复 schema key、非 scalar value、v2、未来版本和非整数来源返回 `unsupported_schema_version` 且不写。写入使用同目录 `NamedTemporaryFile(delete=False)`、`flush`、`os.fsync`、`os.chmod` 和 `os.replace`，`finally` 清理残留临时文件。

- [ ] **Step 4: 接入 `config migrate` 和 `config show`**

在 `_parser()` 增加精确 surface：

```python
migrate = config_commands.add_parser("migrate")
migrate.add_argument("--repo", type=Path, required=True)
migrate.add_argument("--to", type=int, choices=(2,), required=True)
migrate.add_argument("--dry-run", action="store_true")
```

`--dry-run` 成功时原样打印 `result.content` 且不包装 JSON；实际写入使用现有 success envelope。`_config_data()` 必须返回 `schema_version: 2`。

- [ ] **Step 5: 更新 repository config fixtures 并运行测试**

只更新 repository config fixture，不修改 taxonomy、proposal、state、DispatchPacket 或 ChildResult 的 schema 声明。至少覆盖：`tests/contract/test_workflow_cli.py`、`tests/e2e/test_candidate_promotion.py`、`tests/e2e/test_phase_knowledge_packet.py`、`tests/e2e/test_workflow_recovery.py`、`tests/unit/test_doctor.py` 和 `tests/unit/workflow/` 下所有 `_config` helper。

Run: `python -m pytest tests/unit/test_config.py tests/contract/test_config_cli.py tests/unit/test_doctor.py -q`

Expected: PASS。

Run: `python -m pytest -q`

Expected: PASS，证明所有真正加载 repository config 的 fixture 已显式迁移到 v2。

- [ ] **Step 6: Commit**

```bash
git add src/ai_workflow/config.py src/ai_workflow/cli.py tests/unit/test_config.py tests/unit/test_doctor.py tests/contract/test_config_cli.py tests/contract/test_wiki_search_cli.py tests/contract/test_workflow_cli.py tests/e2e/fake_agent.py tests/e2e/test_candidate_promotion.py tests/e2e/test_phase_knowledge_packet.py tests/e2e/test_workflow_recovery.py tests/unit/wiki/test_review.py tests/unit/wiki/test_search.py tests/unit/workflow/test_graph.py tests/unit/workflow/test_reflection.py tests/unit/workflow/test_review.py tests/unit/workflow/test_service.py tests/unit/workflow/test_staging.py tests/unit/workflow/test_submission.py tests/unit/workflow/test_summary.py
git diff --check
git commit -m "feat: enforce repository config schema v2"
```

---

### Task 2: 统一 Path Authorization 与 Adapter 机械执行

**Files:**
- Create: `src/ai_workflow/path_authorization.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/cli.py`
- Create: `tests/unit/test_path_authorization.py`
- Modify: `tests/unit/workflow/test_service.py`
- Modify: `tests/unit/workflow/test_staging.py`
- Modify: `tests/contract/test_config_cli.py`
- Modify: `skills/ai-integration-test-generator/SKILL.md`
- Modify: `skills/ai-integration-test-generator/references/repository-adapter.md`
- Modify: `tests/contract/test_integration_generator_skill.py`

**Interfaces:**
- Produces: `PathKind`、`CheckpointScope`、`RepositoryPathAuthorizer.authorize()`、`RepositoryPathAuthorizer.allowed_input_paths()`、`RepositoryPathAuthorizer.checkpoint_scope()`。
- Consumes: Task 1 的严格 `RepositoryConfig`，包括 `protected_paths` 和 adapter 四字段。
- Later tasks rely on: checkpoint 用同一 normalized/deny 语义构造 `CheckpointScope`，workflow dispatch 不再自行解释 patterns。

- [ ] **Step 1: 写 canonical path、deny precedence 和 adapter allowlist 的失败测试**

在新测试文件覆盖以下 table：

```python
@pytest.mark.parametrize(
    "path",
    ["", ".", "../secret", "/tmp/secret", "src//app.py", "src\\app.py"],
)
def test_authorize_rejects_noncanonical_paths(authorizer, path: str) -> None:
    with pytest.raises(AppError) as error:
        authorizer.authorize("input", path)
    assert error.value.code == "path_not_authorized"


@pytest.mark.parametrize("path", [".git", ".git/config", ".ai-workflow/state.yaml"])
def test_git_and_workflow_paths_are_always_denied(authorizer, path: str) -> None:
    with pytest.raises(AppError) as error:
        authorizer.authorize("input", path)
    assert error.value.code == "path_not_authorized"
```

另写测试证明 literal `src/private` 保护 descendants、protected deny 胜过 adapter/helper-owned allow、escaping symlink 被拒绝、generated-test/report 只能进入各自 destination。

- [ ] **Step 2: 运行 authorizer tests，确认 RED**

Run: `python -m pytest tests/unit/test_path_authorization.py -q`

Expected: FAIL with `ModuleNotFoundError: ai_workflow.path_authorization`。

- [ ] **Step 3: 实现统一 authorizer**

建立精确 public API：

```python
PathKind = Literal["input", "generated-test", "report"]

@dataclass(frozen=True, slots=True)
class CheckpointScope:
    repo_root: Path
    protected_patterns: tuple[str, ...]
    report_patterns: tuple[str, ...]

    def authorize(self, path: str) -> str:
        return _authorize_checkpoint_candidate(
            self.repo_root,
            path,
            protected_patterns=self.protected_patterns,
            report_patterns=self.report_patterns,
        )

class RepositoryPathAuthorizer:
    def __init__(self, repo_root: Path, config: RepositoryConfig) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.config = config

    def authorize(
        self,
        kind: PathKind,
        path: str,
        *,
        helper_owned_report_paths: tuple[str, ...] = (),
    ) -> str:
        normalized = self._normalize(path)
        self._require_inside_repository(normalized)
        self._require_not_denied(normalized)
        self._require_allowed_for_kind(
            kind, normalized,
            helper_owned_report_paths=helper_owned_report_paths,
        )
        return normalized

    def allowed_input_paths(
        self,
        *,
        helper_owned_input_paths: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        candidates = self._configured_or_fallback_input_candidates()
        authorized = [self.authorize("input", path) for path in candidates]
        authorized.extend(
            self._authorize_helper_owned_input(path)
            for path in helper_owned_input_paths
        )
        return tuple(sorted(set(authorized)))

    def checkpoint_scope(self) -> CheckpointScope:
        return CheckpointScope(
            repo_root=self.repo_root,
            protected_patterns=self.config.protected_paths,
            report_patterns=self.config.report_paths,
        )
```

同文件定义并单测 `_normalize()`、`_require_inside_repository()`、`_require_not_denied()`、`_require_allowed_for_kind()`、`_configured_or_fallback_input_candidates()`、`_authorize_helper_owned_input()` 和 `_authorize_checkpoint_candidate()`。先 lexical normalization，再做 resolved containment；所有拒绝统一抛出 `AppError("path_not_authorized", message)`。Pattern 匹配必须检查目标路径及其每个 ancestor，因此 literal protected entry 会保护 descendants。`source_paths`/`test_paths` 任一非空时使用 union allowlist；两者均空时枚举经过 deny 过滤的顶层内容。若父目录包含 protected child，不返回该父目录，递归下沉为安全的最小 roots，避免 packet 间接授权被保护内容。Internal checkpoint scope 允许普通 repository content，但拒绝 `.git`、`.ai-workflow`、protected patterns、configured report paths、repository escape、escaping symlink、gitlink 和特殊文件；它不暴露为第四种 CLI kind。

- [ ] **Step 4: 用 authorizer 替换 service 的手写路径逻辑**

`WorkflowService._allowed_input_paths()` 调用：

```python
return RepositoryPathAuthorizer(self.repo_root, config).allowed_input_paths(
    helper_owned_input_paths=tuple(item.path for item in prior_artifacts),
)
```

`_validate_artifact()` 继续执行 owner、exact output、revision、regular-file/O_NOFOLLOW 和 digest 校验，但 report path 由以下调用决定：

```python
RepositoryPathAuthorizer(self.repo_root, self._config()).authorize(
    "report",
    artifact.path,
    helper_owned_report_paths=(allowed_output,),
)
```

删除不再使用的 `fnmatchcase` import；不得改变 DispatchPacket shape。

- [ ] **Step 5: 增加 `config authorize-path` CLI 与 specialist contract**

CLI exact surface：

```text
ai-workflow config authorize-path --repo REPO --kind input|generated-test|report --path PATH
```

成功 data 固定为：

```json
{"authorized": true, "kind": "input", "path": "src/app.py"}
```

在 integration-test generator 的 `SKILL.md` 和 adapter reference 中要求所有读 input、写 generated test、写 report 前调用对应 kind；contract test 必须查到三条命令和 `path_not_authorized` fail-closed 路由。

- [ ] **Step 6: 运行 focused、contract 和 regression tests**

Run: `python -m pytest tests/unit/test_path_authorization.py tests/unit/workflow/test_service.py tests/unit/workflow/test_staging.py tests/contract/test_config_cli.py tests/contract/test_integration_generator_skill.py -q`

Expected: PASS；现有 protected artifact 测试的稳定 error code 更新为 `path_not_authorized`。

- [ ] **Step 7: Commit**

```bash
git add src/ai_workflow/path_authorization.py src/ai_workflow/workflow/service.py src/ai_workflow/cli.py skills/ai-integration-test-generator/SKILL.md skills/ai-integration-test-generator/references/repository-adapter.md tests/unit/test_path_authorization.py tests/unit/workflow/test_service.py tests/unit/workflow/test_staging.py tests/contract/test_config_cli.py tests/contract/test_integration_generator_skill.py
git diff --check
git commit -m "feat: enforce repository path authorization"
```

---

### Task 3: Profile-aware Persisted Run Graph

**Files:**
- Modify: `src/ai_workflow/workflow/models.py`
- Modify: `src/ai_workflow/workflow/graph.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `tests/unit/workflow/test_models.py`
- Modify: `tests/unit/workflow/test_graph.py`
- Modify: `tests/unit/workflow/test_service.py`
- Modify: `tests/contract/test_workflow_cli.py`

**Interfaces:**
- Produces: `WorkflowProfile`、`RunGraphDefinition`、`build_run_graph(config, profile)`、`validate_run_graph(graph, profile)`、`execution_kind(node)`。
- Consumes: Task 1 的 v2 config 和现有 `RunGraphNode` schema。
- Later tasks rely on: `RunState.current_phase` 与 persisted graph 是恢复真相；`plan.prd` 可机械判定为 workflow-owned。

- [ ] **Step 1: 写 full/grill graph 和 unknown profile 的失败测试**

```python
def test_builds_grill_profile_graph_with_prd_initial_phase(config) -> None:
    definition = build_run_graph(config, WorkflowProfile.GRILL)
    assert definition.initial_phase is Phase.PLAN
    assert tuple(definition.nodes) == (
        "plan.prd", "implement.code", "verify.build", "verify.unit_test",
        "verify.integration_test", "verify.code_review",
    )
    assert "spec.spec" not in definition.nodes


def test_init_rejects_unknown_profile_before_creating_run_directory(service) -> None:
    with pytest.raises(AppError) as error:
        service.init("abc123", "requirement", "unknown")
    assert error.value.code == "invalid_profile"
    assert not (service.repo_root / ".ai-workflow" / "runs").exists()
```

再覆盖 full initial phase、profile mandatory node、cross-profile graph、state round-trip 和 persisted profile/graph mismatch。

- [ ] **Step 2: 运行 graph/model tests，确认 RED**

Run: `python -m pytest tests/unit/workflow/test_graph.py tests/unit/workflow/test_models.py tests/unit/workflow/test_service.py -q`

Expected: FAIL，原因是 graph builder 不接受 profile 且 grill 仍从 spec 开始。

- [ ] **Step 3: 实现 profile types 与 graph definitions**

```python
class WorkflowProfile(StrEnum):
    FULL = "full"
    GRILL = "grill"

@dataclass(frozen=True, slots=True)
class RunGraphDefinition:
    nodes: dict[str, RunGraphNode]
    initial_phase: Phase

def build_run_graph(
    config: RepositoryConfig,
    profile: WorkflowProfile,
) -> RunGraphDefinition:
    template, initial_phase, mandatory = _PROFILE_DEFINITIONS[profile]
    nodes = _materialize_nodes(template, config)
    _require_mandatory_nodes(nodes, mandatory)
    validate_run_graph(nodes, profile)
    return RunGraphDefinition(nodes=nodes, initial_phase=initial_phase)

def execution_kind(
    node: RunGraphNode,
) -> Literal["child_backed", "workflow_owned"]:
    return "workflow_owned" if node.key == "plan.prd" else "child_backed"
```

full graph 保持现有节点；grill graph 只有 `plan.prd`、`implement.code` 和可用 verify nodes。Mandatory set 按 profile 分离，`RunGraphNode.to_dict()` 字段集合不变。

- [ ] **Step 4: 让 `RunState.new()` 接收 initial phase 并 fail closed 恢复**

```python
@classmethod
def new(
    cls,
    run_id: str,
    source_revision: str,
    requirement: str,
    profile: WorkflowProfile,
    run_graph: dict[str, RunGraphNode],
    initial_phase: Phase,
) -> "RunState":
    validate_run_graph(run_graph, profile)
    if not any(node.phase is initial_phase for node in run_graph.values()):
        raise AppError("invalid_run_graph", "initial phase is absent from run graph")
    return cls(
        schema_version=2,
        run_id=run_id,
        version=0,
        status=NodeStatus.PENDING.value,
        current_phase=initial_phase.value,
        source_revision=source_revision,
        requirement=requirement,
        profile=profile.value,
        run_graph=dict(run_graph),
        artifacts={},
    )
```

创建时将 enum value 持久化到现有 `profile`/`current_phase` 字段；`from_dict()` 解析 profile 后用 persisted graph 验证兼容性，不根据当前 `.ai-workflow.yaml` 重建 graph，也不新增 `initial_phase` state 字段。

- [ ] **Step 5: 修改 service init 与 CLI contract**

`WorkflowService.init()` 必须在创建 run directory、policy 或 state 前执行 `WorkflowProfile(profile)`，并将枚举失败翻译为 `invalid_profile`。CLI 不用 argparse `choices` 限制 profile，以便错误走稳定 JSON envelope。

Run: `python -m pytest tests/unit/workflow/test_graph.py tests/unit/workflow/test_models.py tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py -q`

Expected: PASS，full status 为 spec，grill status 为 plan 且包含 `plan.prd`。

- [ ] **Step 6: Commit**

```bash
git add src/ai_workflow/workflow/models.py src/ai_workflow/workflow/graph.py src/ai_workflow/workflow/service.py tests/unit/workflow/test_models.py tests/unit/workflow/test_graph.py tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py
git diff --check
git commit -m "feat: persist profile-aware workflow graphs"
```

---

### Task 4: Effective-phase 状态机与节点级恢复

**Files:**
- Modify: `src/ai_workflow/workflow/machine.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `tests/unit/workflow/test_machine.py`
- Modify: `tests/unit/workflow/test_service.py`
- Modify: `tests/e2e/test_workflow_recovery.py`

**Interfaces:**
- Produces: `effective_phases(state) -> tuple[Phase, ...]` 和批准的 earliest-node invalidation 语义。
- Consumes: Task 3 persisted graph/profile。
- Later tasks rely on: 新 implementation checkpoint 激活后可重置全部 verify nodes；checkpoint 不变时单个 verify sibling 可重跑。

- [ ] **Step 1: 写恢复矩阵失败测试**

```python
def test_cross_phase_rerun_marks_only_earliest_phase_nodes_rerun(state) -> None:
    machine = StateMachine()
    machine.apply_reruns(state, {
        "implement.code": "fix implementation",
        "verify.unit_test": "rerun against corrected code",
    })
    assert state.current_phase == "implement"
    assert state.run_graph["implement.code"].validity is NodeValidity.RERUN
    for key, node in state.run_graph.items():
        if key.startswith("verify."):
            assert node.validity is NodeValidity.PENDING
            assert node.reason is None
```

再覆盖 grill `plan → implement → verify`、单 verify child rerun 保留 valid sibling、`plan.prd` rerun 清空 implement/verify、full spec rerun 清空全部下游、blocked/resume 不伪造业务 rerun。

- [ ] **Step 2: 运行 machine/recovery tests，确认 RED**

Run: `python -m pytest tests/unit/workflow/test_machine.py tests/e2e/test_workflow_recovery.py -q`

Expected: 至少 cross-phase rerun 失败，因为当前实现会把显式下游请求重新标为 rerun。

- [ ] **Step 3: 实现 effective phases 和 earliest invalidation**

```python
def effective_phases(state: RunState) -> tuple[Phase, ...]:
    return tuple(phase for phase in PHASE_ORDER if phase_nodes(state, phase))
```

`advance()` 只在该 tuple 中查找下一 phase。`apply_reruns()` 先完整校验所有 node/reason，再找到 earliest phase：上游不变；earliest phase 只把显式目标设为 rerun并保留未请求 sibling；更晚 phase 无条件设 pending/reason None。Event 可保留完整 review 请求，但 active node validity 不保留下游 reason。

- [ ] **Step 4: 对齐 service attempt 清理与 sibling reuse**

`transition()` 和 `resume()` 从 earliest affected phase 开始清除 `current_attempts`，保留历史 attempts/staged evidence/events。`begin()` 只为非 valid nodes 创建新 attempt；若同 phase valid sibling 的输入锚点未变化，不重新 dispatch。

Run: `python -m pytest tests/unit/workflow/test_machine.py tests/unit/workflow/test_service.py tests/e2e/test_workflow_recovery.py -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/ai_workflow/workflow/machine.py src/ai_workflow/workflow/service.py tests/unit/workflow/test_machine.py tests/unit/workflow/test_service.py tests/e2e/test_workflow_recovery.py
git diff --check
git commit -m "feat: recover from earliest affected workflow node"
```

---

### Task 5: Workflow-owned `plan.prd` 不可变导入

**Files:**
- Modify: `src/ai_workflow/workflow/store.py`
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `src/ai_workflow/cli.py`
- Modify: `tests/unit/workflow/test_store.py`
- Modify: `tests/unit/workflow/test_staging.py`
- Modify: `tests/unit/workflow/test_service.py`
- Modify: `tests/contract/test_workflow_cli.py`

**Interfaces:**
- Produces: extended `DispatchItem`、`StateStore.owned_artifact_path()`、`WorkflowService.stage_owned()`、CLI `workflow stage-owned`。
- Consumes: Task 3 的 `execution_kind(node)` 和 Task 4 的 sibling reuse。
- Later tasks rely on: Grill plan artifact 使用现有 finalize/review/transition barrier，Agent 不直接写 run storage 或构造 ChildResult。

- [ ] **Step 1: 写 owned begin/stage/finalize 的失败测试**

```python
def test_begin_returns_workflow_owned_prd_target_without_dispatch_files(service) -> None:
    run = service.init("abc123", "requirement", "grill")
    attempt = service.begin(run.run_id, Phase.PLAN, skill_dir=None)
    item = attempt.dispatch_plan[0]
    assert item.node == "plan.prd"
    assert item.execution_kind == "workflow_owned"
    assert item.prompt_file is None
    assert item.packet_file is None
    assert item.allowed_artifact_path.endswith("/artifacts/prd.md")
```

再覆盖：schema-v2 synthesized ChildResult、identical retry 幂等、different bytes conflict、wrong owner、source inside current run、symlink/nonregular/blank summary、tampered target/evidence fail closed、begin retry 返回 `already_staged`。

- [ ] **Step 2: 运行 staging tests，确认 RED**

Run: `python -m pytest tests/unit/workflow/test_store.py tests/unit/workflow/test_staging.py -q`

Expected: FAIL，原因是 owned path、execution kind 和 `stage_owned` 尚不存在。

- [ ] **Step 3: 增加 attempt-scoped owned artifact path 与 DispatchItem shape**

```python
def owned_artifact_path(self, attempt_id: str, child: str) -> Path:
    return self._safe_path("attempts", attempt_id, "artifacts", f"{child}.md")

@dataclass(frozen=True, slots=True)
class DispatchItem:
    node: str
    child: str
    execution_kind: Literal["child_backed", "workflow_owned"]
    action: Literal["dispatch", "rerun", "already_staged"]
    allowed_artifact_path: str
    prompt_file: str | None
    packet_file: str | None
```

Owned begin 不要求 skill dir，不创建 knowledge packet、DispatchPacket 或 prompt；evidence 必须严格记录 execution kind、node、mode、rerun reason 和 exact target。Child-backed behavior 保持不变且仍要求有效 skill dir。

- [ ] **Step 4: 抽取共同 staging core 并实现 `stage_owned()`**

```python
def stage_owned(
    self,
    run_id: str,
    attempt_id: str,
    phase: Phase,
    child: str,
    artifact_path: Path,
    summary: str,
) -> StagedChild:
    """Validate and immutably import a workflow-owned artifact."""

def _stage_result_locked(
    self,
    store: StateStore,
    state: RunState,
    attempt_id: str,
    child: str,
    result: ChildResult,
    raw_result: bytes,
) -> StagedChild:
    """Run the shared owner, digest, immutable-write and event protocol."""
```

`stage_owned()` 校验 regular non-symlink source、source 不在当前 run storage、current attempt/phase/child/execution kind、非空 summary；immutable copy 到 exact target；生成 owner=`plan/prd`、status=`completed`、空 findings/citations 的 schema-v2 result，再进入与普通 `stage()` 相同的 digest、event 和 barrier 逻辑。只对 exact helper-owned target 提供窄豁免，不授权任意 `.ai-workflow/**`。

- [ ] **Step 5: 增加 CLI surface 与 contract tests**

```text
ai-workflow workflow stage-owned --repo REPO --run-id RUN --attempt-id ATTEMPT --phase plan --child prd --artifact FILE --summary TEXT
```

`workflow begin --skill-dir` 改为 optional；service 对 child-backed omission 返回 `invalid_skill_dir`。Contract 断言 owned item 的 prompt/packet 为 null、wrong phase/child 使用 JSON error envelope 且不产生 staged evidence。

- [ ] **Step 6: 运行 focused 与 contract tests**

Run: `python -m pytest tests/unit/workflow/test_store.py tests/unit/workflow/test_staging.py tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py -q`

Expected: PASS，现有 child-backed staging contract 无回归。

- [ ] **Step 7: Commit**

```bash
git add src/ai_workflow/workflow/store.py src/ai_workflow/workflow/service.py src/ai_workflow/cli.py tests/unit/workflow/test_store.py tests/unit/workflow/test_staging.py tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py
git diff --check
git commit -m "feat: import workflow-owned grill PRDs"
```

---

### Task 6: Grill Skill 与恢复 Contract

**Files:**
- Modify: `skills/ai-workflow-harness-grill/SKILL.md`
- Modify: `skills/ai-workflow-harness-grill/references/prd-loop.md`
- Modify: `skills/ai-workflow-harness-grill/references/dispatch.md`
- Modify: `skills/ai-workflow-harness/references/helper-cli.md`
- Modify: `README.md`
- Modify: `tests/contract/test_grill_harness_skill.py`
- Create: `tests/skill_scenarios/grill-harness.md`
- Create only when the RED run exhibits a violation: `tests/skill_scenarios/grill-harness.baseline.md`

**Interfaces:**
- Produces: 主 Agent 可执行的 Grill PRD loop、owned import 和 node recovery routing。
- Consumes: Tasks 3–5 的真实 CLI/node contract。
- Later tasks rely on: E2E driver 按文档 surface 执行，环境故障与业务 rerun 不混淆。

- [ ] **Step 1: 使用 `writing-skills` 子 Skill 先写 contract 与 pressure RED tests**

Contract 必须机械断言以下内容存在且顺序一致：

```text
workflow init --profile grill
execution_kind=workflow_owned
workflow stage-owned
plan.prd
implement.code
verify.integration_test
workflow block
```

PRD contract 同时要求 `ISSUE-001`、tracer-bullet vertical slice、acceptance criteria、non-goals、repository scope、verification commands、resolved/blocking open questions，以及“临时 PRD 位于 `.ai-workflow/runs/**` 外、禁止直接构造 ChildResult/编辑 state”。将未加载 Skill 的 pressure prompt 写入 `tests/skill_scenarios/grill-harness.md`；只有实际观察到违反上述 invariant 时才写 sibling baseline，并记录精确违规输出和命令序列。

- [ ] **Step 2: 运行 Skill tests，确认 RED**

Run: `python -m pytest tests/contract/test_grill_harness_skill.py tests/contract/test_skill_contract.py -q`

Expected: FAIL，因为当前 Grill 文档没有真实 owned staging 和节点路由 contract。随后按 `writing-skills` 执行未加载 Skill 的 pressure prompt并保存实际 RED evidence。

- [ ] **Step 3: 重写 Grill 执行与恢复说明**

文档固定路由：PRD/acceptance 变化回 `plan.prd`；implementation 缺陷回 `implement.code`；单项验证缺陷只回对应 `verify.*`；环境、权限、工具失败调用 `workflow block`。明确 Helper 是 run evidence 唯一写入者，主 Agent 一次只问一个 PRD 问题并在 run storage 外维护临时文件。

- [ ] **Step 4: 更新 helper CLI 与 README**

加入 exact `stage-owned`、`config migrate`、`config authorize-path` 命令；README 用中文说明“恢复不是从头开始，而是从最早受影响节点开始”，并说明 checkpoint 只用于验证锚定、不更新业务分支、不 push。

- [ ] **Step 5: 运行 Skill contract tests 并 commit**

Run: `python -m pytest tests/contract/test_grill_harness_skill.py tests/contract/test_skill_contract.py -q`

Expected: PASS。随后显式加载 Grill Skill 重跑同一个 pressure prompt；Agent 必须使用 owned import、按 node rerun，并把环境失败路由到 block。

```bash
git add skills/ai-workflow-harness-grill/SKILL.md skills/ai-workflow-harness-grill/references/prd-loop.md skills/ai-workflow-harness-grill/references/dispatch.md skills/ai-workflow-harness/references/helper-cli.md README.md tests/contract/test_grill_harness_skill.py tests/skill_scenarios/grill-harness.md
# 仅当 RED 执行实际创建了该证据文件时运行下一行：
git add tests/skill_scenarios/grill-harness.baseline.md
git diff --check
git commit -m "docs: define executable grill workflow contract"
```

---

### Task 7: Checkpoint Baseline、临时 Index 与 Hidden Ref

**Files:**
- Create: `src/ai_workflow/workflow/checkpoint.py`
- Create: `tests/unit/workflow/test_checkpoint.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces: `PathSnapshot`、`ImplementationBaseline`、`CheckpointRecord`、`CheckpointService.capture_baseline()`、`create()`、`validate_record()`。
- Consumes: Task 2 的 `CheckpointScope`；标准 Git executable。
- Later tasks rely on: service 只保存 record，不直接实现 Git plumbing。

- [ ] **Step 1: 建立真实 Git repository test fixture 并写保护不变量 RED tests**

Fixture 必须创建初始 commit、返回真实 SHA，并提供读取 HEAD、symbolic ref、branch ref 和 `.git/index` bytes 的 helper。核心测试：

```python
def test_checkpoint_uses_temporary_index_and_preserves_user_git_state(git_repo) -> None:
    service = CheckpointService(git_repo.root)
    scope = RepositoryPathAuthorizer(
        git_repo.root, RepositoryConfig.load(git_repo.root)
    ).checkpoint_scope()
    before = git_repo.snapshot_git_state()
    baseline = service.capture_baseline(
        attempt_id="implement-1-a", source_revision=git_repo.head,
        active_checkpoint=None,
    )
    git_repo.write("src/app.py", "changed\n")
    record = service.create(
        run_id="RUN-1", baseline=baseline,
        source_revision=git_repo.head, scope=scope,
        previous_checkpoint=None, no_code_delivery=False,
    )
    assert git_repo.snapshot_git_state() == before
    assert record.parent_commit == git_repo.head
    assert git_repo.rev_parse(record.hidden_ref) == record.commit_sha
```

再覆盖：pre-existing dirty unchanged 被排除、dirty overlap 返回 `checkpoint_scope_ambiguous`、out-of-scope/escaping symlink/special file/submodule fail closed、existing ref immutable、第二 checkpoint parent 为 previous active、临时 index 总被清理。

- [ ] **Step 2: 运行 checkpoint tests，确认 RED**

Run: `python -m pytest tests/unit/workflow/test_checkpoint.py -q`

Expected: FAIL with `ModuleNotFoundError: ai_workflow.workflow.checkpoint`。

- [ ] **Step 3: 实现 checkpoint data models 与 strict serialization**

```python
@dataclass(frozen=True, slots=True)
class ImplementationBaseline:
    attempt_id: str
    base_revision: str
    head_revision: str
    head_ref: str | None
    dirty_paths: tuple[str, ...]
    dirty_snapshots: tuple[PathSnapshot, ...]
    captured_at: str

@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    commit_sha: str
    tree_sha: str
    hidden_ref: str | None
    source_revision: str
    parent_commit: str
    implementation_attempt_id: str
    included_paths: tuple[str, ...]
    previous_checkpoint_sha: str | None
    created_at: str

class CheckpointService:
    def __init__(
        self,
        repo_root: Path,
        *,
        clock: Callable[[], datetime] = datetime.now,
        timeout_seconds: int = 30,
    ) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.clock = clock
        self.timeout_seconds = timeout_seconds

    def capture_baseline(
        self,
        *,
        attempt_id: str,
        source_revision: str,
        active_checkpoint: CheckpointRecord | None,
    ) -> ImplementationBaseline:
        """Capture Git identity and dirty snapshots relative to the effective base."""

    def create(
        self,
        *,
        run_id: str,
        baseline: ImplementationBaseline,
        source_revision: str,
        scope: CheckpointScope,
        previous_checkpoint: CheckpointRecord | None,
        no_code_delivery: bool,
    ) -> CheckpointRecord:
        """Create or recover one immutable verification checkpoint."""

    def validate_record(self, record: CheckpointRecord) -> None:
        """Verify commit, tree, parent, hidden ref and canonical metadata."""
```

所有 `from_dict()` 检查 exact keys、nonblank identity、40/64 位 hex digest、canonical ref 和 plain values；invalid persisted shape 返回 `invalid_state`。

- [ ] **Step 4: 实现 baseline 与 attempt ownership 算法**

`capture_baseline()` 首次使用 source revision，rerun 使用 active checkpoint commit；记录 HEAD commit/ref；使用临时 `GIT_INDEX_FILE` 对 base 执行 `read-tree`，结合 `diff-files --name-only -z` 与 `ls-files --others --exclude-standard -z` 计算 dirty paths，并保存 regular/symlink/missing 的 mode 与内容或 link-target SHA-256。

创建时重新 snapshot：baseline dirty path 未变化则排除；发生变化则抛 `checkpoint_scope_ambiguous`；baseline clean 且结束时相对 base 变化的 path 才是 candidate。每个 candidate 必须通过注入的 `CheckpointScope`，否则返回 `path_not_authorized`。

- [ ] **Step 5: 实现临时 index tree、commit 和 immutable ref**

固定 Git 流程：`read-tree <base>`；regular file 用 `hash-object -w --stdin` 和 `update-index --add --cacheinfo`；删除用 `update-index --force-remove -- <path>`；最后 `write-tree`、`commit-tree <tree> -p <base>`、`update-ref --create-reflog <ref> <commit> <zero-oid>`。Commit message 包含 canonical JSON metadata，Git author/committer 使用固定 `ai-workflow` identity 和 record timestamp，便于 ref 已写但 state 未写时恢复。

Checkpoint 前后重新读取 HEAD、symbolic branch、branch ref 和 user index digest；任一变化返回 `checkpoint_creation_failed`。所有 Git 失败保存 argv、exit status、截断 stdout/stderr evidence；不得记录环境 secret。

- [ ] **Step 6: 实现 no-code contract 与 record validation**

保留 finding ID：

```json
{"id":"NO-CODE-DELIVERY","title":"No-code delivery","detail":"This implementation attempt intentionally changes no code."}
```

无变化且 marker 存在时 record 复用 baseline base commit、`hidden_ref=null`、`parent_commit=commit_sha=baseline.base_revision`；无变化无 marker或有变化带 marker均返回 `checkpoint_creation_failed`。`validate_record()` 对普通 record 使用 `show-ref`、`cat-file`、tree 和真实 parent 校验 ref/object/metadata；对 no-code record 要求 hidden ref 为空、commit 等于记录的 base/parent 且 tree 可解析。不可解析返回 `checkpoint_unavailable`，绝不重建不同 ref。

- [ ] **Step 7: 运行 tests 并 commit**

Run: `python -m pytest tests/unit/workflow/test_checkpoint.py -q`

Expected: PASS，测试显式证明 HEAD、branch ref 和 user index bytes 不变。

```bash
git add src/ai_workflow/workflow/checkpoint.py tests/unit/workflow/test_checkpoint.py tests/conftest.py
git diff --check
git commit -m "feat: create immutable local verification checkpoints"
```

---

### Task 8: Review Gate 激活与 Verification Revision 锚定

**Files:**
- Modify: `src/ai_workflow/workflow/service.py`
- Modify: `skills/ai-workflow-harness/references/agents/coder.md`
- Modify: `tests/unit/workflow/test_service.py`
- Modify: `tests/unit/workflow/test_review.py`
- Modify: `tests/unit/workflow/test_staging.py`
- Modify: `tests/unit/workflow/test_reflection.py`
- Modify: `tests/contract/test_workflow_cli.py`
- Modify: `tests/contract/test_child_result_v2.py`

**Interfaces:**
- Produces: implementation baseline persistence、active/previous checkpoint state、`_expected_source_revision()`、recovery reconciliation 和稳定 checkpoint error routing。
- Consumes: Tasks 2、4、7 的 path scope、verify invalidation 和 `CheckpointService`。
- Later tasks rely on: 所有 verification packet/result/reuse 都绑定 active commit；新 checkpoint 清空旧 verify active evidence。

- [ ] **Step 1: 写 lifecycle 与 anchor RED tests**

覆盖 human/auto acceptance、accept retry、event repair、creation failure block、transition 防御校验，以及：

```python
def test_verify_dispatch_uses_active_checkpoint_source_revision(service, completed_impl) -> None:
    checkpoint = service.status(completed_impl.run_id).artifacts["checkpoints"]["active"]
    service.transition(completed_impl.run_id)
    attempt = service.begin(completed_impl.run_id, Phase.VERIFY, skill_dir=SKILL_DIR)
    packet = load_packet(attempt.dispatch_plan[0].packet_file)
    assert packet.source_revision == checkpoint["commit_sha"]
```

再覆盖 stale stage/finalize/sibling 返回 `checkpoint_mismatch`，missing ref/object 返回 `checkpoint_unavailable`，这些错误不得被包装为 `invalid_state`。

- [ ] **Step 2: 运行 service/review/staging tests，确认 RED**

Run: `python -m pytest tests/unit/workflow/test_service.py tests/unit/workflow/test_review.py tests/unit/workflow/test_staging.py -q`

Expected: FAIL，因为 implementation begin 没有 baseline，review acceptance 不创建 checkpoint，verify 仍使用 run source。

- [ ] **Step 3: 在 implementation begin 原子持久化 baseline**

Attempt ID 生成后、dispatch evidence 写入前调用 `capture_baseline()`；将 exact baseline dict 放入 `artifacts.attempt_history[attempt_id].implementation_baseline`，与 `phase_begun` 同次 state/event version 保存。Begin retry 复用 persisted baseline；implementation rerun 必须以 active checkpoint 为 base，active record 不可用时先 block 并返回 `checkpoint_unavailable`。

- [ ] **Step 4: 统一 human/auto Review Gate checkpoint 激活**

新增协调方法：

```python
def _activate_implementation_checkpoint_locked(
    self,
    store: StateStore,
    state: RunState,
    attempt_id: str,
) -> CheckpointRecord:
    """Create or recover the attempt checkpoint and activate it in state."""

def _expected_source_revision(self, state: RunState, phase: Phase) -> str:
    if phase is Phase.VERIFY:
        return self._active_checkpoint(state, required=True).commit_sha
    return state.source_revision
```

`review()` 的 auto accept 与 `record_review_acceptance()` 的 human accept 在同一 helper 中激活 checkpoint；`finalize()` 不创建；`transition()` 只防御性要求 active record。Git ref 先创建、state 后写；ref 已存在而 state 缺失时从 canonical commit metadata 收养；state 已写但 event 缺失时补 `checkpoint_activated` event；ref 指向不同 commit绝不覆盖。

- [ ] **Step 5: 持久化 active/previous 并失效旧 verification**

State exact shape：

```yaml
artifacts:
  checkpoints:
    active:
      commit_sha: CHECKPOINT_COMMIT_SHA
      tree_sha: CHECKPOINT_TREE_SHA
      hidden_ref: refs/ai-workflow/checkpoints/RUN-1/implement-1-a
      source_revision: RUN_SOURCE_SHA
      parent_commit: BASE_COMMIT_SHA
      implementation_attempt_id: implement-1-a
      included_paths: [src/app.py]
      previous_checkpoint_sha: null
      created_at: "2026-07-17T12:00:00+08:00"
    previous: null
```

第二次激活：previous 保存旧 active；保留旧 hidden ref 和历史 evidence；删除 active artifact registry 中全部 verification artifact；所有 `verify.*` 设 pending/reason null；清除 `current_attempts.verify`。`checkpoint_scope_ambiguous`、`checkpoint_creation_failed`、`checkpoint_unavailable` 或 checkpoint 内部的 `path_not_authorized` 都保留原 error code，写 `_checkpoint_failure` 和 `checkpoint_failed` event，并将 run 持久化 blocked；resume 后必须重新 review，不能复用 stale accepted gate。

- [ ] **Step 6: 替换所有 source revision 不变量**

在 dispatch creation/owner validation、artifact validation、staged evidence、registered refs、current attempt、finalize、transition 和 load/recovery reconciliation 中统一使用 phase/node 对应的 expected anchor。历史 verify evidence 可保留旧 SHA，但只有等于 active checkpoint 的 evidence 能成为 active staged/valid sibling；非 verify artifact 继续要求 run source revision。

ChildResult/DispatchPacket exact key tests 必须继续通过，证明 schema shape 未变化；coder contract 增加 `NO-CODE-DELIVERY` 的唯一合法位置和双向一致性规则。

- [ ] **Step 7: 运行 focused、contract tests 并 commit**

Run: `python -m pytest tests/unit/workflow/test_checkpoint.py tests/unit/workflow/test_service.py tests/unit/workflow/test_review.py tests/unit/workflow/test_staging.py tests/unit/workflow/test_reflection.py tests/contract/test_workflow_cli.py tests/contract/test_child_result_v2.py -q`

Expected: PASS。

```bash
git add src/ai_workflow/workflow/service.py skills/ai-workflow-harness/references/agents/coder.md tests/unit/workflow/test_service.py tests/unit/workflow/test_review.py tests/unit/workflow/test_staging.py tests/unit/workflow/test_reflection.py tests/contract/test_workflow_cli.py tests/contract/test_child_result_v2.py
git diff --check
git commit -m "feat: anchor verification to accepted checkpoints"
```

---

### Task 9: 真实 Git Fake Agent 与 Behavioral E2E

**Files:**
- Modify: `tests/e2e/fake_agent.py`
- Create: `tests/e2e/test_grill_workflow.py`
- Create: `tests/e2e/test_workflow_checkpoint.py`
- Modify: `tests/e2e/test_mvp_acceptance.py`
- Modify: `tests/e2e/test_skill_first_wave1.py`
- Modify: `tests/e2e/test_workflow_recovery.py`
- Modify: 其他执行完整 implement→verify 生命周期的 E2E fixtures

**Interfaces:**
- Produces: 真实 Git source SHA、真实 implementation code change、owned PRD driver 和 checkpoint/recovery E2E evidence。
- Consumes: Tasks 3–8 的完整 CLI/service contract。
- Later tasks rely on: 最终验收不再由静态安装/文档断言冒充生命周期正确性。

- [ ] **Step 1: 先写五个批准场景的 E2E tests**

测试名称固定为：

```text
test_grill_run_stages_owned_prd_and_completes_plan_implement_verify
test_verify_child_rerun_reuses_checkpoint_and_valid_siblings
test_implementation_rerun_creates_new_checkpoint_and_invalidates_all_verify
test_checkpoint_survives_new_process_and_anchors_verification
test_dirty_overlap_blocks_without_moving_head_branch_or_index
```

每个测试断言 node validity、attempt identity、active/previous checkpoint、packet/artifact source revision 和最终 status；dirty overlap 额外比较 HEAD、symbolic branch、branch ref、user index bytes。

- [ ] **Step 2: 运行新 E2E，确认 RED**

Run: `python -m pytest tests/e2e/test_grill_workflow.py tests/e2e/test_workflow_checkpoint.py -q`

Expected: FAIL，因为现有 fake project 使用 `abc123` 且 implementation 不修改授权代码。

- [ ] **Step 3: 升级 ProjectTemplate、CliDriver 和 FakeAgent**

Project fixture 初始化真实 Git repo、配置 local test identity、提交 `src/app.py` 与 v2 config，并返回 `git rev-parse HEAD`。`workflow_init(profile="full")` 传真实 SHA；新增 `workflow_stage_owned(run_id, attempt_id, phase, child, artifact, summary)`。Fake implementation 修改一个 Task 2 authorizer 允许的代码 path；result JSON 写在 repository 外；每个 ArtifactRef revision 复制其 packet revision，禁止硬编码 `abc123`。

- [ ] **Step 4: 实现 Grill happy path 与 verify-only rerun**

Happy path 必须从 plan 开始、没有 spec attempt、PRD 经 `stage-owned` 导入、实现 Gate 后存在 hidden ref、verify packets 全部锚定 active SHA，最终 completed。Verify-only rerun 只 dispatch 请求 child，其他 sibling 保持 valid 且 revision 不变。

- [ ] **Step 5: 实现 implementation rerun、new-process recovery 与 dirty ambiguity**

Implementation finding 回到 `implement.code`；第二 checkpoint parent 等于第一 active SHA，previous 指向第一 SHA，全部 verify nodes pending。新 service/process 只读 persisted graph/checkpoint/ref 继续 verify。Dirty overlap 必须进入 blocked 并返回 `checkpoint_scope_ambiguous`，且 Git 用户状态逐 byte 不变。

- [ ] **Step 6: 迁移旧完整生命周期 E2E 并运行全部 E2E**

Run: `python -m pytest tests/e2e -q`

Expected: PASS；不存在完整 workflow fixture 继续使用伪 SHA 或把 result/report 写入 checkpoint scope。

- [ ] **Step 7: Commit**

```bash
git add tests/e2e/fake_agent.py tests/e2e/test_grill_workflow.py tests/e2e/test_workflow_checkpoint.py tests/e2e/test_mvp_acceptance.py tests/e2e/test_skill_first_wave1.py tests/e2e/test_workflow_recovery.py
git diff --check
git commit -m "test: prove grill checkpoint recovery end to end"
```

---

### Task 10: 全量回归、追踪矩阵与交付收敛

**Files:**
- Modify: `docs/superpowers/specs/2026-07-17-p0-workflow-correctness-design.md`
- Modify: `README.md`（仅当 Task 6/8 的实际 contract 与示例需要最终对齐）
- Create: `docs/superpowers/reports/2026-07-17-p0-workflow-correctness-verification.md`

**Interfaces:**
- Produces: 设计目标到测试证据的追踪矩阵和最终本地验证记录。
- Consumes: Tasks 1–9 的 commits。
- Later tasks rely on: 后续 CI/provider/telemetry 工作有明确完成基线，不误报真实客户端 parity。

- [ ] **Step 1: 运行新增子系统的 focused suites**

```bash
python -m pytest tests/unit/test_config.py tests/unit/test_path_authorization.py -q
python -m pytest tests/unit/workflow/test_graph.py tests/unit/workflow/test_machine.py tests/unit/workflow/test_checkpoint.py -q
python -m pytest tests/unit/workflow/test_service.py tests/unit/workflow/test_review.py tests/unit/workflow/test_staging.py -q
python -m pytest tests/contract/test_config_cli.py tests/contract/test_workflow_cli.py tests/contract/test_grill_harness_skill.py -q
python -m pytest tests/e2e/test_grill_workflow.py tests/e2e/test_workflow_checkpoint.py -q
```

Expected: 每条命令 PASS。

- [ ] **Step 2: 运行全量测试、Wiki lint 和 whitespace validation**

```bash
python -m pytest -q
ai-workflow wiki lint --wiki wiki
git diff --check
```

Expected: 全量 pytest 0 failures；Wiki 输出 `valid: true`；`git diff --check` 无输出。若当前基线仍为 425 tests，则新增测试后总数必须大于 425，不把 exact count 写成长期 contract。

- [ ] **Step 3: 写 verification report 与追踪矩阵**

报告逐项列出：full/grill graph；earliest-node recovery；owned PRD；config migration；path authorization；temporary-index checkpoint；HEAD/branch/index preservation；human/auto activation；verify anchor；second checkpoint invalidation；new-process recovery；dirty ambiguity block。每行记录测试文件、测试名、命令和实际结果，不写 real Codex/Claude parity 声明。

- [ ] **Step 4: 更新设计状态并检查工作树**

将设计文档状态改为“已实现并通过本地自动化验证”仅限 Step 2 全绿时。运行：

```bash
git status --short
git diff --stat
git diff --check
```

Expected: 只包含本任务 report/status/docs 变更，无临时 index、`.ai-workflow/runs/**`、测试产物或无关用户文件。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-17-p0-workflow-correctness-design.md docs/superpowers/reports/2026-07-17-p0-workflow-correctness-verification.md README.md
git diff --cached --check
git commit -m "docs: record P0 workflow correctness verification"
```

最终 handoff 只报告本地 commits 和验证结果；不创建业务分支、不 push、不创建 MR，除非用户随后明确要求。
