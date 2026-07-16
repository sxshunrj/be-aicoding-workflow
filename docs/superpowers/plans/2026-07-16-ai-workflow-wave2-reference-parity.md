# AI Workflow Wave 2 Reference Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Wave 2 reference-parity Skill suite and conformance coverage on top of the Wave 1 Helper Core.

**Architecture:** Keep Python Helper Core as the deterministic state/contract layer and add Wave 2 capabilities primarily as focused Skills with static contract tests and local conformance scenarios. Add Helper Core only where the Skills need machine-readable repository adapter or checkpoint facts.

**Tech Stack:** Python 3.11+, standard library, PyYAML 6.x, pytest 8.x, Markdown Agent Skills, YAML/JSON contracts.

## Global Constraints

- Keep `skills/` as the canonical Skill source.
- Skill `name` and display name stay English; user-facing descriptions and SKILL.md bodies stay Chinese.
- Do not add runtime dependencies beyond `PyYAML>=6.0,<7`.
- Preserve Wave 1 commands, state schema, ChildResult schema, and Wiki lifecycle compatibility.
- Python Helper Core validates mechanics only; semantic correctness remains Agent/human responsibility.
- Every task ends with focused tests, affected regression tests, `git diff --check`, and a local commit.
- Do not claim `reference-parity` until Wave 2 local conformance and real-client evidence are available.

---

## Target File Map

- `skills/ai-workflow-harness-grill/`: interactive PRD-driven `plan -> implement -> verify` workflow Skill.
- `skills/ai-integration-test-checklists/`: evidence-mapped integration-test checklist Skill.
- `skills/ai-integration-test-generator/`: repository-adapter-driven integration-test asset generator Skill.
- `skills/ai-integration-test-v2/`: execute/diagnose/converge integration tests without adapting expectations to broken code.
- `skills/ai-ci-failure-triage/`: collect failed-job facts and route failures to the correct Skill.
- `src/ai_workflow/config.py`: repository adapter fields for integration, lint, source/test paths, and report destinations.
- `src/ai_workflow/workflow/service.py`: checkpoint evidence and reusable sibling-result summary if needed.
- `src/ai_workflow/cli.py`: adapter/doctor extensions if needed.
- `tests/contract/`: static Skill and CLI contracts.
- `tests/e2e/test_wave2_reference_parity.py`: local reference-parity conformance scenario.
- `docs/wave-2-trial.md`, `docs/wave-2-traceability.md`: real-client trial and local evidence.

---

### Task 1: Grill Harness Skill Contract

**Files:**
- Create: `skills/ai-workflow-harness-grill/SKILL.md`
- Create: `skills/ai-workflow-harness-grill/agents/openai.yaml`
- Create: `skills/ai-workflow-harness-grill/references/prd-loop.md`
- Create: `skills/ai-workflow-harness-grill/references/dispatch.md`
- Create: `tests/contract/test_grill_harness_skill.py`

**Interfaces:**
- Produces: `$ai-workflow-harness-grill`, a PRD-driven Skill that owns interactive planning and delegates implementation/verification to child-backed workflow patterns.
- Consumes: existing `ai-workflow-harness` control-loop concepts, but does not create new Helper state schema in this task.

- [ ] **Step 1: Write failing static contract tests**

```python
from pathlib import Path


SKILL_DIR = Path("skills/ai-workflow-harness-grill")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_grill_frontmatter_and_display_metadata_are_canonical() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")
    assert skill.startswith(
        "---\nname: ai-workflow-harness-grill\n"
        "description: Use when 用户显式要求 PRD-driven plan/implement/verify workflow，"
        "或要求 ai-workflow grill harness。\n---\n"
    )
    assert 'display_name: "AI Workflow Harness Grill"' in metadata
    assert "交互式 PRD 驱动" in metadata


def test_grill_skill_defines_prd_driven_three_phase_loop() -> None:
    skill = _read()
    for phrase in (
        "plan -> implement -> verify",
        "一次只问一个问题",
        "plan phase 由主 Agent 交互式拥有",
        "implement 和 verify 仍然 child-backed",
        "PRD issue identifier 是内容标识，不是 dynamic run-graph node",
        "不得直接编辑 .ai-workflow/runs/**",
    ):
        assert phrase in skill


def test_grill_references_cover_prd_loop_and_dispatch_boundaries() -> None:
    prd = _read("references/prd-loop.md")
    dispatch = _read("references/dispatch.md")
    for phrase in ("acceptance criteria", "non-goals", "open questions", "PRD artifact"):
        assert phrase in prd
    for phrase in ("prompt_file", "ChildResult", "barrier", "stage", "finalize"):
        assert phrase in dispatch
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/contract/test_grill_harness_skill.py -q
```

Expected: fail because `skills/ai-workflow-harness-grill` does not exist.

- [ ] **Step 3: Implement the Grill Skill files**

Create `SKILL.md` in Chinese. It must say:

```markdown
---
name: ai-workflow-harness-grill
description: Use when 用户显式要求 PRD-driven plan/implement/verify workflow，或要求 ai-workflow grill harness。
---

# AI Workflow Harness Grill

Grill 是交互式 PRD 驱动 workflow。它只用于用户显式要求，不替代 `$ai-workflow-harness`。

## Control loop

`plan -> implement -> verify`

- plan phase 由主 Agent 交互式拥有：一次只问一个问题，澄清目标、范围、acceptance criteria、non-goals 和 open questions。
- plan phase 写 run-local PRD artifact；PRD issue identifier 是内容标识，不是 dynamic run-graph node。
- implement 和 verify 仍然 child-backed，遵守 prompt_file、ChildResult、stage、barrier、finalize、review gate。
- 不得直接编辑 `.ai-workflow/runs/**`；所有状态变化只通过 Helper CLI。
- 如果需求扩大到多条独立 workflow，先拆分 PRD，不要在一个 Grill run 里混合。

## References

- [PRD loop](references/prd-loop.md)
- [Dispatch](references/dispatch.md)
```

Create `agents/openai.yaml`:

```yaml
interface:
  display_name: "AI Workflow Harness Grill"
  short_description: "交互式 PRD 驱动的 plan/implement/verify workflow"
  default_prompt: "使用 $ai-workflow-harness-grill 启动交互式 PRD 驱动 workflow。"
```

Create `references/prd-loop.md` with exact sections:

```markdown
# PRD Loop

plan phase 由主 Agent 拥有。一次只问一个问题，直到可以写出 PRD artifact。

PRD artifact 必须包含：

- requirement summary
- acceptance criteria
- non-goals
- open questions
- repository scope
- verification commands

如果 open questions 仍影响实现或验收，停止并继续提问，不进入 implement。
```

Create `references/dispatch.md` with exact sections:

```markdown
# Dispatch

implement 和 verify 使用 child-backed 执行。

- 只把 Helper 生成的 `prompt_file` 交给 child。
- child 只返回 schema-v2 `ChildResult`。
- 主 Agent serially `stage` 每个 child result。
- `barrier` 未满足时不得 `finalize`。
- `finalize` 后才进入 review gate。
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/contract/test_grill_harness_skill.py -q
git diff --check
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add skills/ai-workflow-harness-grill tests/contract/test_grill_harness_skill.py
git commit -m "feat: add grill harness skill"
```

---

### Task 2: Integration Checklist Skill

**Files:**
- Create: `skills/ai-integration-test-checklists/SKILL.md`
- Create: `skills/ai-integration-test-checklists/agents/openai.yaml`
- Create: `skills/ai-integration-test-checklists/references/checklist-schema.md`
- Create: `tests/contract/test_integration_checklists_skill.py`

**Interfaces:**
- Produces: `$ai-integration-test-checklists`.
- Consumes: requirements, designs, diffs, PRD artifacts, and repository adapter fields.

- [ ] **Step 1: Write failing static tests**
- [ ] **Step 2: Implement Chinese Skill and checklist schema**
- [ ] **Step 3: Verify and commit**

---

### Task 3: Integration Test Generator Skill

**Files:**
- Create: `skills/ai-integration-test-generator/SKILL.md`
- Create: `skills/ai-integration-test-generator/agents/openai.yaml`
- Create: `skills/ai-integration-test-generator/references/repository-adapter.md`
- Modify: `src/ai_workflow/config.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/contract/test_integration_generator_skill.py`

**Interfaces:**
- Produces: repository adapter fields for generated-test destinations and source/test path patterns.
- Produces: `$ai-integration-test-generator`.

- [ ] **Step 1: Write failing config and Skill tests**
- [ ] **Step 2: Extend repository config with optional adapter fields**
- [ ] **Step 3: Implement Skill contract**
- [ ] **Step 4: Verify and commit**

---

### Task 4: Integration Test V2 Convergence Skill

**Files:**
- Create: `skills/ai-integration-test-v2/SKILL.md`
- Create: `skills/ai-integration-test-v2/agents/openai.yaml`
- Create: `skills/ai-integration-test-v2/references/convergence.md`
- Create: `tests/contract/test_integration_test_v2_skill.py`

**Interfaces:**
- Produces: `$ai-integration-test-v2`.
- Consumes: repository adapter commands and generated/checklist artifacts.

- [ ] **Step 1: Write failing static tests**
- [ ] **Step 2: Implement Chinese convergence Skill**
- [ ] **Step 3: Verify and commit**

---

### Task 5: CI Failure Triage Skill

**Files:**
- Create: `skills/ai-ci-failure-triage/SKILL.md`
- Create: `skills/ai-ci-failure-triage/agents/openai.yaml`
- Create: `skills/ai-ci-failure-triage/references/failure-routing.md`
- Create: `tests/contract/test_ci_failure_triage_skill.py`

**Interfaces:**
- Produces: `$ai-ci-failure-triage`.
- Consumes: CI failed-job facts and routes to environment/build/unit/integration failure classes.

- [ ] **Step 1: Write failing static tests**
- [ ] **Step 2: Implement Chinese triage Skill**
- [ ] **Step 3: Verify and commit**

---

### Task 6: Installer and Doctor Cover Eleven Skills

**Files:**
- Modify: `src/ai_workflow/doctor.py`
- Modify: `tests/unit/test_doctor.py`
- Modify: `tests/unit/test_install.py`
- Create: `tests/contract/test_wave2_skill_suite.py`

**Interfaces:**
- Consumes: all Wave 1 and Wave 2 skill directories.
- Produces: suite-level contract proving all eleven Skills are discoverable and have English display names.

- [ ] **Step 1: Write failing suite tests for all eleven Skills**
- [ ] **Step 2: Adjust doctor messages if needed**
- [ ] **Step 3: Verify and commit**

---

### Task 7: Wave 2 Local Conformance and Trial Docs

**Files:**
- Create: `tests/e2e/test_wave2_reference_parity.py`
- Create: `docs/wave-2-trial.md`
- Create: `docs/wave-2-traceability.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Wave 2 Skills.
- Produces: local conformance evidence and real-client evidence template.

- [ ] **Step 1: Write local conformance test**
- [ ] **Step 2: Add docs and status text without claiming reference-parity**
- [ ] **Step 3: Run full verification**
- [ ] **Step 4: Commit and stop for real-client Wave 2 evidence**
