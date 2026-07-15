import json
from pathlib import Path
import re

from ai_workflow.contracts.artifacts import ChildResult


SKILL_DIR = Path("skills/ai-workflow-harness")
REQUIRED_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/bootstrap.md",
    "references/helper-cli.md",
    "references/subagent-dispatch.md",
    "references/review-gate.md",
    "references/recovery.md",
    "references/terminal-cleanup.md",
    "references/knowledge-loop.md",
    "references/agents/common-phase-contract.md",
    "references/agents/spec-writer.md",
    "references/agents/planner.md",
    "references/agents/coder.md",
    "references/agents/test-runner.md",
    "references/agents/code-reviewer.md",
    "references/agents/knowledge-reflector.md",
}
CONTROL_SEQUENCE = (
    "status -> begin -> dispatch -> stage -> barrier -> finalize -> review -> "
    "transition -> status"
)
CHILD_RESULT_KEYS = {
    "schema_version",
    "run_id",
    "phase",
    "child",
    "attempt_id",
    "execution_mode",
    "status",
    "summary",
    "artifact",
    "findings",
    "knowledge_citations",
}
ARTIFACT_REF_KEYS = {
    "path",
    "sha256",
    "schema_version",
    "phase",
    "child",
    "source_revision",
}
WORKFLOW_COMMANDS = (
    "ai-workflow config show --repo REPO",
    "ai-workflow workflow init --repo REPO --source-revision SHA --requirement TEXT --profile PROFILE",
    "ai-workflow workflow status --repo REPO --run-id RUN",
    "ai-workflow workflow begin --repo REPO --run-id RUN --phase PHASE --skill-dir SKILL_DIR",
    "ai-workflow workflow stage --repo REPO --run-id RUN --attempt-id ATTEMPT --child CHILD --result FILE",
    "ai-workflow workflow finalize --repo REPO --run-id RUN --attempt-id ATTEMPT",
    "ai-workflow workflow review --repo REPO --run-id RUN [--rerun NODE=REASON ...]",
    "ai-workflow workflow review-accept --repo REPO --run-id RUN --expected-digest SHA",
    "ai-workflow workflow transition --repo REPO --run-id RUN",
    "ai-workflow workflow block --repo REPO --run-id RUN --reason TEXT",
    "ai-workflow workflow resume --repo REPO --run-id RUN [--rerun NODE=REASON ...]",
    "ai-workflow workflow abort --repo REPO --run-id RUN",
    "ai-workflow workflow summary --repo REPO --run-id RUN",
)
WIKI_COMMANDS = (
    "ai-workflow wiki lint --wiki PATH",
    "ai-workflow wiki search --wiki PATH [QUERY FILTERS]",
    "ai-workflow wiki packet --wiki PATH --output FILE [QUERY FILTERS]",
    "ai-workflow wiki propose --wiki PATH --proposal FILE",
    "ai-workflow wiki promote --wiki PATH --id ID --reviewer NAME --expected-digest SHA",
    "ai-workflow wiki reject --wiki PATH --id ID --reviewer NAME --reason TEXT --expected-digest SHA",
    "ai-workflow wiki archive --wiki PATH --id ID --reviewer NAME --reason TEXT --expected-digest SHA",
)
OWNER_MAPPINGS = {
    "references/agents/spec-writer.md": (
        ("spec.spec", "technical-spec.md"),
    ),
    "references/agents/planner.md": (
        ("plan.solution", "implementation-plan.md"),
        ("plan.test_strategy", "test-strategy.md"),
    ),
    "references/agents/coder.md": (
        ("implement.code", "implementation-report.md"),
    ),
    "references/agents/test-runner.md": (
        ("verify.build", "build-report.md"),
        ("verify.unit_test", "unit-test-report.md"),
        ("verify.integration_test", "integration-test-report.md"),
    ),
    "references/agents/code-reviewer.md": (
        ("verify.code_review", "code-review-report.md"),
    ),
    "references/agents/knowledge-reflector.md": (
        ("terminal.reflection", "knowledge-reflection.json"),
    ),
}
STALE_ROUTES = (
    "| `review_gate_mismatch` | `workflow status -> workflow review` | 不进入 block |",
    "| `stale_review_gate` | `workflow status -> workflow block -> human resume/abort` | 禁止继续 review |",
)


def _read(relative: str) -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_harness_has_only_the_required_progressive_disclosure_files() -> None:
    files = {
        path.relative_to(SKILL_DIR).as_posix()
        for path in SKILL_DIR.rglob("*")
        if path.is_file()
    }
    assert files == REQUIRED_FILES


def test_harness_frontmatter_and_main_sections_are_canonical() -> None:
    skill = _read("SKILL.md")
    assert skill.startswith(
        "---\nname: ai-workflow-harness\n"
        "description: Use when 用户显式要求持久化四阶段 AI 编码工作流、恢复 "
        "ai-workflow run，或明确要求 child agents 与 review gates 的 ai-workflow 场景。\n"
        "---\n"
    )
    assert "\n---\n\n# AI Workflow Harness\n" in skill
    for heading in (
        "## Hard gates",
        "## Workflow ownership boundary",
        "## Main loop",
        "## Running / blocked / terminal routing",
        "## Reference index",
    ):
        assert heading in skill
    assert len(skill.split()) < 500


def test_main_loop_preserves_control_order_and_hard_invariants() -> None:
    skill = _read("SKILL.md")
    assert CONTROL_SEQUENCE in skill
    required_text = (
        "Harness 绝不执行 child-owned coding、testing、case repair 或 code review",
        "Never edit state.yaml directly",
        "dispatch all sibling children before waiting",
        "silence is not failure",
        "ChildResult-only completion",
        "mandatory human gates",
        "new-conversation status recovery",
        "terminal reflection",
        "Git handoff",
    )
    for text in required_text:
        assert text in skill


def test_main_skill_links_every_reference_directly() -> None:
    skill = _read("SKILL.md")
    for relative in sorted(REQUIRED_FILES):
        if not relative.startswith("references/"):
            continue
        assert f"]({relative})" in skill


def test_reference_topics_own_their_required_contracts() -> None:
    expected = {
        "references/bootstrap.md": ("scan", "resume", "requirement", "profile", "run_id"),
        "references/helper-cli.md": ("JSON", "error.code", "caller", "workflow status"),
        "references/subagent-dispatch.md": ("prompt_file", "dispatch", "wait", "ChildResult"),
        "references/review-gate.md": ("workflow review", "review-accept", "digest", "transition"),
        "references/recovery.md": ("status", "attempt", "staged", "review_gate"),
        "references/terminal-cleanup.md": ("human", "reflection", "governance", "Git handoff"),
        "references/knowledge-loop.md": ("packet", "knowledge_citations", "raw Wiki Markdown"),
    }
    for relative, terms in expected.items():
        text = _read(relative)
        for term in terms:
            assert term in text, f"{relative} must contain {term!r}"


def test_common_child_contract_defines_exact_schema_v2_result_and_no_state_rules() -> None:
    contract = _read("references/agents/common-phase-contract.md")
    for field in (
        "schema_version",
        "run_id",
        "phase",
        "child",
        "attempt_id",
        "execution_mode",
        "status",
        "summary",
        "artifact",
        "findings",
        "knowledge_citations",
    ):
        assert field in contract
    for term in (
        "completed",
        "unable_to_complete",
        "evidence",
        "ChildResult",
        "state.yaml",
        "workflow helper",
        "rerun_reason",
    ):
        assert term in contract
    assert "allowed_input_paths` 是 repository-relative" in contract
    assert "`allowed_output_path` 是唯一可 stage 的物理路径" in contract


def test_child_result_example_has_exact_top_level_and_artifact_keys() -> None:
    contract = _read("references/agents/common-phase-contract.md")
    match = re.search(r"```json\n(?P<payload>.*?)\n```", contract, re.DOTALL)
    assert match is not None
    payload = json.loads(match.group("payload"))
    assert set(payload) == CHILD_RESULT_KEYS
    assert payload["schema_version"] == 2
    assert isinstance(payload["artifact"], dict)
    assert set(payload["artifact"]) == ARTIFACT_REF_KEYS
    assert payload["artifact"]["schema_version"] == 2


def test_helper_cli_documents_the_exact_command_and_argument_matrix() -> None:
    helper = _read("references/helper-cli.md")
    table_commands = tuple(
        re.findall(r"^\| `(ai-workflow (?:config|workflow) [^`]+)` \|", helper, re.MULTILINE)
    )
    assert table_commands == WORKFLOW_COMMANDS
    block = re.search(
        r"Knowledge commands.*?```text\n(?P<commands>.*?)\n```",
        helper,
        re.DOTALL,
    )
    assert block is not None
    assert tuple(block.group("commands").splitlines()) == WIKI_COMMANDS


def test_stale_review_routes_are_exact_mutually_exclusive_and_consistent() -> None:
    for relative in ("references/review-gate.md", "references/recovery.md"):
        text = _read(relative)
        routes = tuple(line for line in text.splitlines() if line in STALE_ROUTES)
        assert routes == STALE_ROUTES
    mismatch_route = STALE_ROUTES[0].split(" | ")[1]
    stale_route = STALE_ROUTES[1].split(" | ")[1]
    assert "block" not in mismatch_route
    assert "review" not in stale_route


def test_owner_contracts_assign_every_child_and_artifact() -> None:
    expectations = {
        "references/agents/spec-writer.md": (("spec", "technical-spec.md"),),
        "references/agents/planner.md": (
            ("solution", "implementation-plan.md"),
            ("test_strategy", "test-strategy.md"),
        ),
        "references/agents/coder.md": (("code", "implementation-report.md"),),
        "references/agents/test-runner.md": (
            ("build", "build-report.md"),
            ("unit_test", "unit-test-report.md"),
            ("integration_test", "integration-test-report.md"),
        ),
        "references/agents/code-reviewer.md": (("code_review", "code-review-report.md"),),
        "references/agents/knowledge-reflector.md": (
            ("terminal reflection", "knowledge-reflection.json"),
        ),
    }
    for relative, pairs in expectations.items():
        contract = _read(relative)
        assert "completed" in contract
        assert "unable_to_complete" in contract
        assert "evidence" in contract
        for child, artifact in pairs:
            assert child in contract
            assert artifact in contract


def test_owner_mapping_markers_are_structurally_exact() -> None:
    marker = re.compile(r"^- Owner mapping：`([^`]+)` -> `([^`]+)`$", re.MULTILINE)
    for relative, expected in OWNER_MAPPINGS.items():
        assert tuple(marker.findall(_read(relative))) == expected


def test_terminal_governance_choices_are_keyed_to_persisted_status() -> None:
    terminal = _read("references/terminal-cleanup.md")
    rows = re.findall(
        r"^\| `(?P<status>candidate|approved|archived)` \| (?P<choices>[^|]+?) \|$",
        terminal,
        re.MULTILINE,
    )
    assert rows == [
        ("candidate", "`promote` / `reject` / 保持不变"),
        ("approved", "独立退役流程：`archive` / 保持不变"),
        ("archived", "保持不变"),
    ]
    assert "当前没有 `wiki supersede` 命令" in terminal
    assert "`supersedes` / `conflicts`" in terminal


def test_terminal_new_conversation_uses_safe_replay_not_a_fake_checkpoint() -> None:
    terminal = _read("references/terminal-cleanup.md")
    assert "当前没有 cleanup checkpoint" in terminal
    assert "每次 terminal 新会话都从步骤 1 安全幂等重放" in terminal
    assert "不得假装知道上次中断点" in terminal
    for required in (
        "`status` 确认 terminal",
        "重新展示终态验收",
        "检测既有 accepted artifacts",
        "检查当前 candidate/approved/archive 状态",
        "summary 是纯读",
        "重新检查 Git status/diff 并再次询问",
    ):
        assert required in terminal
    assert "从未完成的最早人类 gate 恢复" not in terminal


def test_each_phase_fixture_parses_as_child_result() -> None:
    for path in sorted(Path("tests/contract/fixtures").glob("*-result.json")):
        result = ChildResult.from_json(path)
        assert result.status in {"completed", "unable_to_complete"}


def test_pressure_scenarios_preserve_the_chinese_control_bodies() -> None:
    scenarios = Path("tests/skill_scenarios")
    main = (scenarios / "harness-main-agent.md").read_text(encoding="utf-8")
    child = (scenarios / "harness-child-agent.md").read_text(encoding="utf-8")
    assert "当前 `plan` phase 需要 `solution` 和\n`test_strategy` 两个 child；二者都已 dispatch" in main
    assert "`test_strategy` 仍在运行。用户说：“`solution` 很好，现在就继续。”" in main
    assert "`workflow stage` 以 stale 为由拒绝了你的结果" in child
    assert "编辑 `.ai-workflow/runs/RUN-X/state.yaml`，替换其中的 attempt ID" in child
    assert not (scenarios / "harness-main-agent.baseline.md").exists()
    assert (scenarios / "harness-child-agent.baseline.md").is_file()
