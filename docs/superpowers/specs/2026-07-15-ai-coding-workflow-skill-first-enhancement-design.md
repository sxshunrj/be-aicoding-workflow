# AI Coding Workflow Skill-First Enhancement Design

**Date:** 2026-07-15  
**Status:** Approved design  
**Reference implementation:** `cg/ad-billing-ai-coding`, default branch `master`, inspected at commit `cf6a69e5af6ab70dfac6f1b3a814aa9df5397f3a`  
**Supersedes:** The Skill product-surface portions of `2026-07-14-ai-coding-workflow-llm-wiki-design.md`; the deterministic Workflow and Wiki Core remain valid unless this document changes them explicitly.

## 1. Purpose

The current repository proves a deterministic four-phase workflow and Git-backed Wiki core, but exposes them through one thin Skill. That result is a CLI-first engine with a Skill adapter, not the Skill-first product requested by the user.

This enhancement restructures the product around a suite of reusable Skills, following the implementation method of `ad-billing-ai-coding`:

- a single outer workflow harness owns orchestration semantics;
- reusable activities live in focused top-level Skills;
- phase and child responsibilities live in explicit Agent contracts;
- deterministic scripts and the Python Core validate, persist, and advance state;
- the LLM proposes semantic decisions, while humans approve irreversible or quality-sensitive actions;
- the first delivery is deliberately light enough for real Codex use before further optimization.

The reference repository's domain-specific billing behavior is not copied. Its Skill organization, ownership boundaries, staged child-result protocol, recovery model, and human gates are generalized into a language-neutral framework.

## 2. Goals

1. Reach functional parity with the stable and experimental Skill capabilities present in the reference repository, using language-neutral names and repository adapters.
2. Make Skills the primary user-facing product surface and keep the Python package as a deterministic Helper Core.
3. Preserve one canonical Skill source tree and install it into Codex and Claude Code without duplicate implementations.
4. Support a complete four-phase workflow, an interactive PRD-driven three-phase workflow, and an explicitly invoked lightweight TDD workflow.
5. Support staged child results, phase barriers, reruns with actionable reasons, result reuse, checkpoints, blocked recovery, and terminal Git handoff.
6. Add an auditable LLM-Wiki loop: bounded retrieval, citations, mandatory reflection, candidate generation, and human-controlled governance.
7. Deliver in two waves so the user can run a lightweight real-client trial before reference-parity completion and later optimization.

## 3. Non-Goals

- Do not embed billing, Java, Maven, white-box framework, ByteDance CI, or Lark assumptions in the generic core.
- Do not duplicate the canonical Skill content for Codex and Claude Code.
- Do not move semantic technical decisions into Python validators.
- Do not auto-promote knowledge, auto-approve blocked recovery, or auto-authorize destructive Git actions.
- Do not optimize the reference workflow before capability parity and real-client feedback.
- Do not preserve the current thin `ai-workflow` Skill as a compatibility Skill. The CLI executable remains named `ai-workflow`.

## 4. Chosen Architecture

The selected architecture is a hybrid Skill-first model.

```text
Top-level workflow Skill
        |
        +--> phase/child Agent contracts
        +--> reusable specialist Skills
        +--> immutable prompt files and ChildResult contracts
        |
        v
ai-workflow CLI / Python Helper Core
        |
        +--> workflow state, run graph, attempts, staging, events
        +--> packet generation, artifact and digest validation
        +--> Wiki retrieval, proposal validation, and governance mutations
```

The outer Harness decides when work should happen, which child owns it, what evidence is required, and when a human decision is necessary. Specialist Skills explain how to perform reusable activities. The Helper Core enforces deterministic invariants and never decides whether a design or code change is technically correct.

## 5. Canonical Skill Suite

Canonical sources remain under `skills/`. `ai-workflow-init` installs or links them into each supported client's discovery directory.

```text
skills/
├── ai-workflow-init/
├── ai-workflow-harness/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   │   ├── bootstrap.md
│   │   ├── helper-cli.md
│   │   ├── subagent-dispatch.md
│   │   ├── review-gate.md
│   │   ├── recovery.md
│   │   ├── terminal-cleanup.md
│   │   ├── knowledge-loop.md
│   │   └── agents/
│   │       ├── common-phase-contract.md
│   │       ├── spec-writer.md
│   │       ├── planner.md
│   │       ├── coder.md
│   │       ├── test-runner.md
│   │       ├── code-reviewer.md
│   │       └── knowledge-reflector.md
│   └── tests/
├── ai-workflow-harness-grill/
├── ai-small-tdd-change/
├── ai-integration-test-generator/
├── ai-integration-test-checklists/
├── ai-integration-test-v2/
├── ai-ci-failure-triage/
├── ai-git-handoff/
├── ai-knowledge-reflection/
└── ai-knowledge-governance/
```

### 5.1 Reference capability mapping

| Reference Skill | Generic Skill | Responsibility |
| --- | --- | --- |
| `billing-init` | `ai-workflow-init` | Install the CLI and Skill suite, validate discovery, and report an idempotent summary. |
| `billing-workflow-harness` | `ai-workflow-harness` | Persistent four-phase orchestration with child-backed execution and human gates. |
| `billing-workflow-harness-grill` | `ai-workflow-harness-grill` | Interactive PRD-driven `plan -> implement -> verify` workflow. |
| `billing-small-tdd-change` | `ai-small-tdd-change` | Explicit-only lightweight TDD loop with independent verification and review. |
| `billing-integration-test-class-generator` | `ai-integration-test-generator` | Generate or update integration-test assets through a repository adapter. |
| `generating-integration-test-checklists` | `ai-integration-test-checklists` | Turn requirements, designs, or diffs into an evidence-mapped test checklist. |
| `white-box-test-v2` | `ai-integration-test-v2` | Execute, diagnose, and converge integration tests without adapting expectations to broken code. |
| `billing-ci-failure-triage` | `ai-ci-failure-triage` | Collect failed-job facts, classify failures, and route to the correct Skill. |
| `billing-git-handoff` | `ai-git-handoff` | Human-controlled skip, commit, branch, push, and merge-request handoff. |
| New LLM-Wiki capability | `ai-knowledge-reflection` | Derive evidence-backed reusable candidate knowledge from a terminal run. |
| New LLM-Wiki capability | `ai-knowledge-governance` | Review, compare, promote, reject, archive, and supersede knowledge. |

### 5.2 Ownership boundaries

- The Harness schedules, stages, summarizes, proposes reruns, presents gates, and invokes Helper commands.
- The Harness does not write business code, run verification commands, repair integration cases, or override child findings.
- Child Agents write only their assigned artifacts and ChildResult.
- A child cannot edit workflow state, stage a sibling result, finalize a phase, or transition the run.
- Specialist Skills own reusable techniques, not workflow state.
- The Helper Core owns state shape, legal transitions, attempt identity, barriers, digests, and persistence.
- Humans own blocked recovery, terminal completion, knowledge promotion, and destructive Git decisions.

## 6. Workflow Models

### 6.1 Four-phase Harness

Formal phases remain:

```text
spec -> plan -> implement -> verify
```

The default language-neutral run graph is:

```text
spec.spec
plan.solution
plan.test_strategy
implement.code
verify.build
verify.unit_test
verify.integration_test
verify.code_review
```

Repository configuration may remove unsupported optional nodes, such as integration testing. The Helper derives the effective graph; the Agent cannot silently remove nodes.

Every node has one scheduling validity:

| Validity | Meaning | Execution |
| --- | --- | --- |
| `pending` | Never executed | `fresh` child execution |
| `valid` | Previous result is reusable | Helper-owned result reuse |
| `rerun` | Must execute again | Child receives a non-empty actionable reason |

### 6.2 Grill Harness

The PRD-driven Harness follows the reference model:

```text
plan -> implement -> verify
```

`plan` is workflow-owned and interactive. It asks one question at a time, resolves scope and acceptance criteria, and writes a run-local PRD. Implementation and verification remain child-backed. PRD issue identifiers are content identifiers, not dynamic run-graph nodes.

### 6.3 Small TDD Skill

`ai-small-tdd-change` is manual-trigger only. It does not enter the persistent four-phase run graph. It follows:

```text
clarify -> failing focused test -> minimal implementation
        -> focused test pass -> independent test phase
        -> lightweight code review -> concise handoff
```

If the change expands across public interfaces, data models, multiple modules, or high-risk behavior, the Skill stops and asks the user whether to switch to a full Harness run.

## 7. Harness Control Loop

```text
bootstrap
  -> status/read-state
  -> begin phase
  -> receive Helper-generated dispatch plan and prompt files
  -> dispatch every required child
  -> stage each ChildResult serially
  -> barrier: wait for all required children
  -> finalize phase
  -> derive rerun proposal from results and human feedback
  -> Review Gate
  -> transition
  -> status/read-state
```

### 7.1 Bootstrap

Bootstrap scans existing runs, asks whether to resume or create a run when candidates exist, records the original requirement, resolves the repository profile, and initializes the effective graph. It does not execute a phase or infer the next transition.

### 7.2 Dispatch plan and prompt files

`workflow begin` generates a dispatch plan. Every executable child receives a dedicated immutable prompt file containing:

- run, phase, child, and attempt identity;
- the original requirement;
- owner and common contract paths;
- execution mode and rerun reason;
- repository profile and allowed commands;
- allowed input and output paths;
- prior accepted artifacts;
- a bounded knowledge packet reference and digest;
- implementation checkpoint anchors when applicable.

The Harness dispatch message is only:

```text
Read <prompt_file>, follow it exactly, and return only the ChildResult JSON.
```

The Harness must not summarize, rewrite, or append hidden context.

### 7.3 Stage, barrier, and finalize

A child result is staged but does not advance a phase. Staging validates the current attempt, artifact ownership, schema, digests, citations, and checkpoint context. The Helper finalizes only when every required child has a current staged result.

Completed sibling results become reusable even when another child cannot complete. `unable_to_complete` marks only the responsible node for rerun and requires the Harness to replace placeholder failure text with an actionable reason before transition.

### 7.4 Review Gate and transition

The Harness derives a complete rerun proposal before requesting the Helper's review decision. A transition is illegal unless the current results are finalized and the applicable gate is accepted.

Intermediate phase gates may use repository-configured `human` or `auto_accept` mode. The following gates are always human:

- blocked resume or abort;
- terminal completion;
- knowledge promotion, rejection, archival, or supersession;
- commit, push, remote branch, merge request, or destructive Git action.

### 7.5 Checkpoint and verification

After accepted implementation, a Git checkpoint records the implementation delivery. Verification children validate that checkpoint. A later implementation rerun creates a new checkpoint while retaining the previous checkpoint as an optional delta-focus anchor. Final verification scope remains the full active implementation delivery.

## 8. Recovery and Failure Semantics

Run truth remains under:

```text
.ai-workflow/runs/<run_id>/
```

A new conversation starts with `workflow status`. Chat history is never reconstructed into state.

| Condition | Required behavior |
| --- | --- |
| Invalid user input or repository config | Report the exact field and wait for correction. |
| Invalid ChildResult | Return the validation error to the owning child; do not advance. |
| Stale attempt or result | Reject it and use the current dispatch plan. |
| One sibling finishes early | Stage it and keep waiting. |
| Child is quiet or a wait call times out | Continue waiting; silence is not failure. |
| Child returns `unable_to_complete` | Stage the result and route the node through rerun review. |
| Environment, permission, or tool failure | Persist a blocked reason. |
| State or event corruption | Enter `workflow_internal` blocked; never hand-edit state. |
| Human gate pending | Stop transitions until an explicit decision arrives. |

Helper commands return a stable JSON envelope and machine-readable error codes. Skills route by error code, not by fragile natural-language matching.

## 9. LLM-Wiki Knowledge Loop

### 9.1 Retrieval and citations

Before each child execution, the Helper builds a bounded packet using repository, service/module, path, language, phase, child role, task keywords, and rerun reason. A child may consume Wiki content only through the referenced packet.

ChildResult citations must be selected IDs from that packet. Unknown or tampered citations are rejected.

### 9.2 Mandatory terminal reflection

Every `done` or `aborted` run invokes `ai-knowledge-reflection`. It inspects only recorded run evidence:

- original requirement and final status;
- phase and child artifacts;
- findings, rerun reasons, and human decisions;
- actual verification commands and results;
- cited knowledge IDs;
- transition events;
- checkpoint or Git-diff summaries.

Candidate types are `rule`, `pattern`, `diagnostic`, `decision`, `pitfall`, and `workflow`. Insufficient evidence produces a `no-candidate` report rather than invented knowledge.

### 9.3 Human governance

`ai-knowledge-governance` searches for related approved and candidate knowledge, evaluates duplication, conflict, applicability, expiration, and supersession, then presents a human gate.

Reflection may write proposals only through `wiki propose`. It cannot modify approved knowledge. Governance mutations require the reviewed candidate digest. Approved entries record source run, evidence, scope, owner, reviewer, and validity period. Superseded entries retain history and explicit relationships.

The closed loop is:

```text
approved knowledge
  -> bounded phase packet
  -> cited child result
  -> run evidence
  -> reflection candidate
  -> human governance
  -> approved knowledge
```

## 10. Installation and Client Adapters

`skills/` is the single source of truth. `ai-workflow-init` follows a strict self-update/read/run protocol and performs idempotent installation.

The installer:

1. checks Python 3.11+, Git, and supported clients;
2. installs or verifies the `ai-workflow` CLI;
3. defaults to user-scope development links in `$HOME/.agents/skills` for Codex and `$HOME/.claude/skills` for Claude Code, so the suite is available from arbitrary target repositories;
4. supports explicit repository-scope links in `<repo>/.agents/skills` and `<repo>/.claude/skills`, plus copy installation for distribution;
5. writes an installation manifest with source commit and Skill digests;
6. runs `ai-workflow doctor` against CLI, Skill discovery, Wiki layout, and the example configuration;
7. prints installed, updated, skipped, and failed items and exits non-zero when failures remain.

Codex and Claude Code adapters differ only in child dispatch and resume primitives. They use identical prompt files, Helper commands, state, artifacts, ChildResult, and knowledge protocols.

## 11. Repository Adapters

Language- and platform-specific mechanics are declared in `.ai-workflow.yaml`, not encoded in generic Skills. The repository profile provides:

- build, unit-test, integration-test, lint, and optional review commands;
- report paths and parser identifiers;
- source and test path patterns;
- generated-test destinations;
- optional phase/child nodes;
- protected paths;
- knowledge scope defaults;
- CI provider adapter when available.

`examples/language-neutral` supplies a complete local adapter and deterministic fake reports for Skill and E2E testing.

## 12. Test Strategy

### 12.1 Skill documentation TDD

Each Skill is developed with pressure scenarios:

1. run the scenario without the Skill or with the old thin Skill and record the Agent's protocol violation;
2. add the minimal Skill guidance and contracts;
3. rerun the same scenario and verify compliance;
4. add adversarial variants to close rationalization loopholes.

Contract tests validate front matter, references, scripts, ownership boundaries, required sub-Skills, and forbidden state mutations.

### 12.2 Helper Core tests

Existing unit, contract, and E2E coverage remains. New coverage includes:

- node-level run graph and actionable rerun reasons;
- multi-child staging, barrier, and finalization;
- immutable prompt-file completeness;
- stale attempts, damaged state, duplicate submission, and digest conflicts;
- blocked, resume, abort, and new-process recovery;
- checkpoint activation and child-result reuse;
- reflection proposal and human governance round trips.

### 12.3 Real-client conformance

Codex and Claude Code execute the same scenario definitions. Evidence records client version, installed Skill digest, run ID, attempt IDs, commands, child dispatches, final state, and fresh-conversation recovery output.

## 13. Delivery Waves

### Wave 1: lightweight trial

Deliver:

- `ai-workflow-init`;
- `ai-workflow-harness`;
- `ai-small-tdd-change`;
- `ai-git-handoff`;
- `ai-knowledge-reflection`;
- `ai-knowledge-governance`;
- four-phase child contracts;
- required Helper Core enhancements.

Then pause for real Codex use. The trial covers installation, Skill discovery, one small TDD change, one minimal four-phase run, child dispatch and staging, fresh-conversation recovery, candidate generation, human promotion, and Git handoff.

### Wave 2: reference parity

Deliver:

- `ai-workflow-harness-grill`;
- `ai-integration-test-generator`;
- `ai-integration-test-checklists`;
- `ai-integration-test-v2`;
- `ai-ci-failure-triage`;
- parallel verification children;
- checkpoints and result reuse.

Only after Wave 2 passes conformance tests does optimization based on observed usage begin.

Release labels are:

```text
experimental -> wave-1 trial -> reference-parity -> optimized
```

The repository must not claim `MVP verified` or `reference-parity` before the corresponding real-client evidence exists.

## 14. Acceptance Criteria

Wave 1 is accepted when:

1. The installer discovers and installs all Wave 1 Skills idempotently.
2. Codex lists the installed Skills and explicitly invokes them.
3. A real small-TDD task completes focused TDD, independent verification, and lightweight review.
4. A minimal four-phase run uses real child dispatch, staging, barrier, finalization, review, and transition.
5. A new conversation restores the same run only from persisted state.
6. Terminal reflection creates either an evidence-backed candidate or an explicit no-candidate report.
7. A human can promote a candidate, and a later run can retrieve and cite it.
8. Git handoff asks for a human choice before external or irreversible actions.
9. No Agent edits workflow state or approved Wiki content directly.

Wave 2 is accepted when:

1. The Grill Harness completes a PRD-driven three-phase run.
2. Integration checklist, generation, and convergence Skills compose through a repository adapter.
3. CI triage collects complete failed-job facts and routes environment, build, unit-test, and integration-test failures correctly.
4. Parallel verification observes full dispatch-before-wait and barrier semantics.
5. Valid sibling results are reused across reruns.
6. Verification results are anchored to the active implementation checkpoint.
7. All eleven Skills are installable, discoverable, independently triggerable, and covered by contract tests.
8. Codex and Claude Code pass the shared protocol conformance suite.

---

# AI Coding Workflow Skill-First 增强设计

**日期：** 2026-07-15  
**状态：** 已批准设计  
**参考实现：** `cg/ad-billing-ai-coding`，默认分支 `master`，核对提交 `cf6a69e5af6ab70dfac6f1b3a814aa9df5397f3a`  
**替代范围：** 替代 `2026-07-14-ai-coding-workflow-llm-wiki-design.md` 中 Skill 产品层相关设计；除非本文明确修改，确定性的 Workflow Core 与 Wiki Core 继续有效。

## 1. 目的

当前仓库已经证明四阶段状态机和 Git Wiki Core 可以工作，但只暴露了一个很薄的 Skill。它本质上是“CLI-first 引擎 + Skill 适配器”，不是用户要求的 Skill-first 产品。

本次增强参考 `ad-billing-ai-coding` 的实现方法，把产品重构为可复用 Skill 套件：

- 唯一外层 Workflow Harness 持有编排语义；
- 可复用活动拆成聚焦的顶层 Skill；
- Phase 与 Child 职责由明确的 Agent contract 定义；
- 确定性脚本和 Python Core负责校验、持久化和推进状态；
- LLM提出语义决策，人类批准不可逆或影响质量的动作；
- 第一轮足够轻量，可以先在真实 Codex 中试用，再继续优化。

不会复制参考仓库的计费业务内容，而是通用化其 Skill组织、职责边界、staged result协议、恢复模型和人工闸门。

## 2. 目标

1. 以语言无关的名称和仓库适配器，对齐参考仓库中稳定及实验性 Skill能力。
2. 让 Skill成为主要产品入口，Python包降级为确定性 Helper Core。
3. 维护唯一 Skill源码，同时支持 Codex和Claude Code安装，避免双份实现。
4. 支持完整四阶段 Workflow、交互式PRD三阶段Workflow和显式触发的轻量TDD流程。
5. 支持Child结果暂存、Phase barrier、带可执行原因的重跑、结果复用、checkpoint、blocked恢复和终态Git交接。
6. 增加可审计的LLM-Wiki闭环：有界检索、引用、强制反思、候选生成和人工治理。
7. 分两轮交付，让用户在能力完全对齐和优化前先完成真实客户端轻量试用。

## 3. 非目标

- 不在通用核心中写死 billing、Java、Maven、white-box框架、字节CI或Lark假设。
- 不为 Codex和Claude Code复制两份canonical Skill内容。
- 不把技术语义判断移入Python校验器。
- 不自动晋升知识，不自动恢复blocked状态，不自动批准破坏性Git动作。
- 在能力对齐和真实使用反馈前，不提前优化参考流程。
- 不保留当前薄 `ai-workflow` Skill兼容壳；CLI可执行命令仍叫 `ai-workflow`。

## 4. 选定架构

采用混合 Skill-first 架构。

```text
顶层 Workflow Skill
        |
        +--> Phase/Child Agent contracts
        +--> 可复用专项 Skills
        +--> 不可变 Prompt files 与 ChildResult contracts
        |
        v
ai-workflow CLI / Python Helper Core
        |
        +--> Workflow state、run graph、attempt、staging、events
        +--> Packet生成、artifact与digest校验
        +--> Wiki检索、proposal校验和治理变更
```

外层 Harness 决定何时工作、由谁负责、需要什么证据、何时进入人工决策。专项 Skill 说明可复用活动如何执行。Helper Core只维护确定性不变量，不判断设计或代码在技术上是否正确。

## 5. Canonical Skill 套件

唯一源码保留在 `skills/`，由 `ai-workflow-init` 安装或链接到客户端发现目录。

```text
skills/
├── ai-workflow-init/
├── ai-workflow-harness/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   │   ├── bootstrap.md
│   │   ├── helper-cli.md
│   │   ├── subagent-dispatch.md
│   │   ├── review-gate.md
│   │   ├── recovery.md
│   │   ├── terminal-cleanup.md
│   │   ├── knowledge-loop.md
│   │   └── agents/
│   │       ├── common-phase-contract.md
│   │       ├── spec-writer.md
│   │       ├── planner.md
│   │       ├── coder.md
│   │       ├── test-runner.md
│   │       ├── code-reviewer.md
│   │       └── knowledge-reflector.md
│   └── tests/
├── ai-workflow-harness-grill/
├── ai-small-tdd-change/
├── ai-integration-test-generator/
├── ai-integration-test-checklists/
├── ai-integration-test-v2/
├── ai-ci-failure-triage/
├── ai-git-handoff/
├── ai-knowledge-reflection/
└── ai-knowledge-governance/
```

### 5.1 参考能力映射

| 参考 Skill | 通用 Skill | 职责 |
| --- | --- | --- |
| `billing-init` | `ai-workflow-init` | 安装CLI和Skill套件，校验发现能力，输出幂等汇总。 |
| `billing-workflow-harness` | `ai-workflow-harness` | 带持久化、Child执行和人工闸门的四阶段编排。 |
| `billing-workflow-harness-grill` | `ai-workflow-harness-grill` | 交互式PRD驱动的 `plan -> implement -> verify` 流程。 |
| `billing-small-tdd-change` | `ai-small-tdd-change` | 仅显式触发的轻量TDD、独立验证和审查。 |
| `billing-integration-test-class-generator` | `ai-integration-test-generator` | 通过仓库适配器生成或更新集成测试资产。 |
| `generating-integration-test-checklists` | `ai-integration-test-checklists` | 把需求、设计或diff转换为证据映射的测试清单。 |
| `white-box-test-v2` | `ai-integration-test-v2` | 执行、诊断和收敛集成测试，不让case迎合错误代码。 |
| `billing-ci-failure-triage` | `ai-ci-failure-triage` | 收集失败job事实，分类失败并路由到正确Skill。 |
| `billing-git-handoff` | `ai-git-handoff` | 人工控制skip、commit、branch、push和MR交接。 |
| 新LLM-Wiki能力 | `ai-knowledge-reflection` | 从终态run中提炼有证据的可复用候选知识。 |
| 新LLM-Wiki能力 | `ai-knowledge-governance` | 审核、比较、晋升、拒绝、归档和替代知识。 |

### 5.2 职责边界

- Harness只调度、暂存、汇总、提出重跑、展示闸门并调用Helper命令。
- Harness不写业务代码、不跑验证命令、不修集测case、不覆盖Child finding。
- Child Agent只写所属artifact和ChildResult。
- Child不能编辑Workflow state、提交sibling结果、finalize Phase或transition run。
- 专项Skill负责可复用技术，不拥有Workflow state。
- Helper Core负责state shape、合法transition、attempt身份、barrier、digest和持久化。
- 人类负责blocked恢复、terminal completion、知识晋升和破坏性Git决策。

## 6. Workflow 模型

### 6.1 四阶段 Harness

Formal phase保持：

```text
spec -> plan -> implement -> verify
```

默认语言无关run graph：

```text
spec.spec
plan.solution
plan.test_strategy
implement.code
verify.build
verify.unit_test
verify.integration_test
verify.code_review
```

仓库配置可以移除不支持的可选节点，例如integration test。有效graph由Helper推导，Agent不能静默删节点。

每个节点只有一种调度validity：

| Validity | 含义 | 执行方式 |
| --- | --- | --- |
| `pending` | 从未执行 | `fresh` Child执行 |
| `valid` | 上次结果可复用 | Helper复用结果 |
| `rerun` | 必须重跑 | Child收到非空、可执行reason |

### 6.2 Grill Harness

PRD驱动Harness沿用参考模型：

```text
plan -> implement -> verify
```

`plan`由Workflow主Agent交互式负责，一次只问一个问题，收敛范围和验收标准，并写run-local PRD。Implementation和Verification仍由Child负责。PRD issue ID只是内容标识，不是动态run-graph节点。

### 6.3 Small TDD Skill

`ai-small-tdd-change`只能手动触发，不进入持久化四阶段run graph：

```text
澄清 -> 聚焦失败测试 -> 最小实现
     -> 聚焦测试通过 -> 独立测试阶段
     -> 轻量代码审查 -> 简洁交接
```

如果改动扩大到公共接口、数据模型、多模块或高风险行为，Skill停止并询问是否切换为完整Harness run。

## 7. Harness 控制循环

```text
bootstrap
  -> status/read-state
  -> begin phase
  -> 获取Helper生成的dispatch plan和prompt files
  -> 派发所有required children
  -> 串行stage每个ChildResult
  -> barrier：等待所有required children
  -> finalize phase
  -> 根据结果与人工反馈推导rerun proposal
  -> Review Gate
  -> transition
  -> status/read-state
```

### 7.1 Bootstrap

Bootstrap扫描已有run；存在候选时询问恢复还是新建；记录原始需求；解析仓库profile；初始化有效graph。它不执行phase，也不推导下一次transition。

### 7.2 Dispatch plan 与 prompt files

`workflow begin`生成dispatch plan。每个需要执行的Child获得独立不可变prompt file，其中包含：

- run、phase、child和attempt身份；
- 原始需求；
- owner与common contract路径；
- execution mode与rerun reason；
- 仓库profile与允许命令；
- 允许输入输出路径；
- 前序已接受artifact；
- 有界knowledge packet引用与digest；
- 适用时的implementation checkpoint anchor。

Harness派发消息只包含：

```text
读取 <prompt_file>，严格执行，最终只返回 ChildResult JSON。
```

Harness不能摘要、改写或追加隐藏上下文。

### 7.3 Stage、barrier 与 finalize

Child结果只会被stage，不会推进phase。Stage校验当前attempt、artifact ownership、schema、digest、citation和checkpoint上下文。只有全部required children都存在当前staged result，Helper才能finalize。

即使某个Child无法完成，已完成sibling也会变成可复用结果。`unable_to_complete`只把所属节点标为需要重跑；transition前，Harness必须把占位失败文本替换为可执行reason。

### 7.4 Review Gate 与 transition

Harness必须先推导完整rerun proposal，再请求Helper给出review decision。未finalize当前结果或未接受适用gate时，transition非法。

中间Phase gate可使用仓库配置的 `human` 或 `auto_accept`。以下闸门始终要求人工：

- blocked resume或abort；
- terminal completion；
- 知识晋升、拒绝、归档或替代；
- commit、push、远程branch、MR或破坏性Git操作。

### 7.5 Checkpoint 与 verification

Implementation被接受后，用Git checkpoint记录实现交付。Verification Child验证该checkpoint。后续implementation rerun生成新checkpoint，并保留旧checkpoint作为可选delta anchor；最终验证范围仍是完整active implementation。

## 8. 恢复与失败语义

Run真值继续存放在：

```text
.ai-workflow/runs/<run_id>/
```

新会话只能从 `workflow status` 开始，不能根据聊天记录重建状态。

| 情况 | 必须行为 |
| --- | --- |
| 用户输入或仓库配置非法 | 指出精确字段并等待修正。 |
| ChildResult非法 | 把校验错误交回所属Child，不推进。 |
| stale attempt/result | 拒绝旧结果，使用当前dispatch plan。 |
| 单个sibling提前完成 | Stage并继续等待。 |
| Child安静或等待调用超时 | 继续等待；安静不等于失败。 |
| Child返回 `unable_to_complete` | Stage结果并经rerun review路由该节点。 |
| 环境、权限或工具失败 | 持久化blocked reason。 |
| State或event损坏 | 进入 `workflow_internal` blocked，禁止手改。 |
| 人工闸门等待 | 获得明确决定前停止transition。 |

Helper命令返回稳定JSON envelope和机器可读错误码。Skill按错误码路由，不使用脆弱的自然语言匹配。

## 9. LLM-Wiki 知识闭环

### 9.1 检索与引用

每个Child执行前，Helper根据repository、service/module、path、language、phase、child role、task keyword和rerun reason生成有界packet。Child只能通过该packet消费Wiki内容。

ChildResult引用必须来自该packet的selected IDs；未知或被篡改的引用会被拒绝。

### 9.2 强制终态反思

每个 `done` 或 `aborted` run都调用 `ai-knowledge-reflection`，只读取已经记录的run证据：

- 原始需求与最终状态；
- Phase和Child artifacts；
- findings、rerun reasons和人工决定；
- 实际验证命令和结果；
- 引用的knowledge IDs；
- transition events；
- checkpoint或Git diff摘要。

Candidate类型为 `rule`、`pattern`、`diagnostic`、`decision`、`pitfall` 和 `workflow`。证据不足时输出 `no-candidate` report，不得制造知识。

### 9.3 人工治理

`ai-knowledge-governance`检索相关approved和candidate知识，评估重复、冲突、适用范围、过期和替代关系，然后展示人工闸门。

Reflection只能通过 `wiki propose` 写proposal，不能修改approved知识。Governance变更必须携带已经审阅的candidate digest。Approved entry记录source run、evidence、scope、owner、reviewer和有效期。被替代知识保留历史和显式关系。

闭环为：

```text
approved knowledge
  -> 有界phase packet
  -> Child引用
  -> run证据
  -> reflection candidate
  -> 人工governance
  -> approved knowledge
```

## 10. 安装与客户端适配

`skills/`是唯一真值。`ai-workflow-init`遵循严格的自更新、重读、执行协议，并执行幂等安装。

安装器：

1. 检查Python 3.11+、Git和支持的客户端；
2. 安装或验证 `ai-workflow` CLI；
3. 默认使用用户级开发链接：Codex安装到 `$HOME/.agents/skills`，Claude Code安装到 `$HOME/.claude/skills`，从而能在任意目标仓库使用；
4. 显式指定repository scope时链接到 `<repo>/.agents/skills` 和 `<repo>/.claude/skills`，发布时另支持copy安装；
5. 写入包含source commit和Skill digest的安装manifest；
6. 使用 `ai-workflow doctor` 校验CLI、Skill发现、Wiki layout和示例配置；
7. 输出installed、updated、skipped和failed汇总，仍有失败时非零退出。

Codex与Claude Code只在Child dispatch/resume原语上不同。两者使用完全相同的prompt files、Helper commands、state、artifacts、ChildResult和knowledge协议。

## 11. 仓库适配器

语言和平台相关机制声明在 `.ai-workflow.yaml`，不写入通用Skill。Repository profile提供：

- build、unit test、integration test、lint和可选review命令；
- report路径和parser标识；
- source/test路径模式；
- 生成测试目标路径；
- 可选Phase/Child节点；
- protected paths；
- knowledge scope默认值；
- 可选CI provider adapter。

`examples/language-neutral`提供完整本地adapter和确定性fake report，用于Skill和E2E测试。

## 12. 测试策略

### 12.1 Skill 文档TDD

每个Skill通过压力场景开发：

1. 在没有Skill或只有旧薄Skill时执行场景，记录Agent协议偏差；
2. 加入最小Skill指导和contract；
3. 重跑同一场景并验证遵循；
4. 加入对抗变体，关闭Agent合理化漏洞。

Contract test校验front matter、references、scripts、职责边界、required sub-Skills和禁止状态变更。

### 12.2 Helper Core 测试

保留现有unit、contract和E2E覆盖，并增加：

- Node级run graph与可执行rerun reason；
- 多Child staging、barrier和finalization；
- 不可变prompt file完整性；
- stale attempt、损坏state、重复提交和digest conflict；
- blocked、resume、abort和新进程恢复；
- checkpoint激活与Child结果复用；
- reflection proposal与人工governance round trip。

### 12.3 真实客户端一致性

Codex和Claude Code执行相同场景定义。证据记录client version、已安装Skill digest、run ID、attempt IDs、命令、Child dispatch、最终state和新会话恢复输出。

## 13. 交付轮次

### 第一轮：轻量试用

交付：

- `ai-workflow-init`；
- `ai-workflow-harness`；
- `ai-small-tdd-change`；
- `ai-git-handoff`；
- `ai-knowledge-reflection`；
- `ai-knowledge-governance`；
- 四阶段Child contracts；
- 必要Helper Core增强。

然后暂停开发，进入真实Codex试用：安装、Skill发现、一个small TDD改动、一个最小四阶段run、Child dispatch与stage、新会话恢复、candidate生成、人工晋升和Git handoff。

### 第二轮：参考能力对齐

交付：

- `ai-workflow-harness-grill`；
- `ai-integration-test-generator`；
- `ai-integration-test-checklists`；
- `ai-integration-test-v2`；
- `ai-ci-failure-triage`；
- 并行verification children；
- checkpoint与结果复用。

只有第二轮通过一致性测试后，才根据实际使用反馈开始优化。

发布状态：

```text
experimental -> wave-1 trial -> reference-parity -> optimized
```

在真实客户端证据存在前，仓库不得标记 `MVP verified` 或 `reference-parity`。

## 14. 验收标准

第一轮验收：

1. 安装器能够幂等发现和安装全部第一轮Skill。
2. Codex能够列出并显式调用已安装Skill。
3. 真实small-TDD任务完成聚焦TDD、独立验证和轻量审查。
4. 最小四阶段run使用真实Child dispatch、stage、barrier、finalize、review和transition。
5. 新会话只能依靠持久化state恢复同一run。
6. Terminal reflection生成有证据candidate或明确no-candidate report。
7. 人工能够晋升candidate，后续run能够检索并引用它。
8. Git handoff在外部或不可逆动作前询问人工选择。
9. 没有Agent直接编辑Workflow state或approved Wiki内容。

第二轮验收：

1. Grill Harness完成PRD驱动三阶段run。
2. 集测Checklist、生成和收敛Skill通过仓库adapter组合运行。
3. CI Triage收集完整失败job事实，并正确路由环境、构建、单测和集测失败。
4. 并行Verification遵守先完整派发、再等待和barrier语义。
5. Valid sibling结果可跨rerun复用。
6. Verification结果锚定active implementation checkpoint。
7. 全部11个Skill可安装、可发现、可独立触发，并有contract test。
8. Codex与Claude Code通过共享协议一致性套件。
