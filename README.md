# AI Workflow

Status: wave-1 trial; wave-2 local conformance in progress

本仓库提供一套 Skill-first 的本地 AI coding workflow：`spec -> plan -> implement -> verify` 持久化流程、schema-v2 ChildResult、LLM Wiki 检索/反思/治理、以及 Codex/Claude Code 可发现的 Wave 1 Skill 套件。Python Helper Core 只做确定性校验和状态持久化；语义判断仍由 Agent 与人类 gate 负责。

## 本地准备

1. 安装 Python 3.11+。
2. 安装依赖：`pip install -e '.[dev]'`。
3. 安装 Skill：`bash skills/ai-workflow-init/scripts/init.sh --client all --scope user`。
4. 诊断环境：`ai-workflow doctor --source-root "$PWD/skills" --repo "$PWD/examples/language-neutral" --client all`。
5. 运行离线验证：`python -m pytest -q`。

## Skill Overview

Skill 名称保持英文，便于在 Codex/Claude Code 中稳定调用；说明和流程以中文为主。调用时使用 `$skill-name`，不是 `/skills` 列表里的展示标题。

### `$ai-workflow-init`

安装和诊断整套 Skill。第一次安装、更新仓库后重新安装、`/skills` 看不到某个 Skill、或 `doctor` 失败时使用。

核心流程：

```text
locate/update ai-workflow-init
-> reread latest SKILL.md
-> run scripts/init.sh
-> inspect installed/updated/skipped/failed
-> run doctor
```

它只处理安装和诊断，不运行业务 workflow phase。

### `$ai-workflow-harness`

完整四阶段持久化 AI coding workflow。适合需求已经相对明确、需要从 spec 到 verify 闭环推进的开发任务。

生命周期：

```text
spec -> plan -> implement -> verify
```

主控循环：

```text
status -> begin -> dispatch -> stage -> barrier -> finalize -> review -> transition -> status
```

关键边界：不直接编辑 `.ai-workflow/runs/**/state.yaml`，不代写 child result，不跳过 review gate。状态恢复必须从 `ai-workflow workflow status` 和持久化 state 读取，不靠聊天记录。

### `$ai-workflow-harness-grill`

PRD 驱动的交互式 workflow。适合需求还不清楚，需要先一问一答整理 PRD，再进入实现和验证的场景。

流程：

```text
plan -> implement -> verify
```

`plan` 由主 Agent 交互式拥有：一次只问一个问题，澄清目标、范围、acceptance criteria、non-goals 和 open questions，并写出 run-local PRD artifact。`implement` 和 `verify` 仍然使用 child-backed 执行。

关键命令路径：

```text
workflow init --profile grill
-> workflow begin --phase plan
-> execution_kind=workflow_owned / plan.prd
-> workflow stage-owned
-> workflow finalize
-> workflow review
-> workflow transition
-> workflow begin --phase implement
```

恢复不是从头开始，而是从最早受影响节点开始：PRD/acceptance 变化回 `plan.prd`，实现缺陷回 `implement.code`，单项验证缺陷只回对应 `verify.*`，环境、权限或工具失败进入 `workflow block`。

Checkpoint 只用于验证锚定，不更新业务分支、不 push；后续 Git 决策仍由 `$ai-git-handoff` 在人类确认后执行。

### `$ai-small-tdd-change`

显式触发的小范围 TDD 工作流。适合单点 bugfix、小行为改动、低风险局部修改。

流程：

```text
clarify -> failing focused test -> minimal implementation -> focused pass -> independent verification -> lightweight review
```

如果改动扩大到 public API、shared data model、多模块行为或高风险兼容性，它会停下并建议切到完整 harness。

### `$ai-git-handoff`

Git 收尾和交接。每次任务完成后，需要决定是否跳过、提交当前分支、或创建远程分支/MR 时使用。

流程：

```text
inspect status/diff/current branch
-> summarize intended task files and unrelated files
-> human choice
-> execute only chosen scope
-> report evidence
```

它不会自动 `git add .`，不会提交无关文件，不会自动 push、force-push、reset 或 clean。外部或不可逆动作都需要人类明确选择。

### `$ai-knowledge-reflection`

终态 run 后做知识反思，把 run evidence 转成明确的 `no_candidate` decision 或 candidate proposal。

流程：

```text
workflow reflect
-> read packet
-> search related approved knowledge
-> write decision
-> optional proposal
-> workflow reflect-submit
-> wiki propose
```

它只生成候选知识，不会 promote，不会直接写 `wiki/approved`。

### `$ai-knowledge-governance`

人工审核 candidate knowledge。用于 review、promote、reject 或保持 candidate 不变。

流程：

```text
wiki review
-> inspect candidate evidence/scope/reuse/conflicts/related approved
-> show digest and material differences
-> human choice
-> execute one digest-protected lifecycle command
-> report result
```

它不会默认 promote；沉默等于保持不变。所有 promote/reject 都带 candidate digest，避免 stale candidate 被误处理。

### `$ai-integration-test-checklists`

把需求、设计、PRD、diff 或实现说明转换成 evidence-mapped integration-test checklist。它只产出 checklist，不改代码。

输出结构：

```text
Scope
Evidence Map
Checklist Items
Gap Analysis
Verification Commands
```

每个 checklist item 必须指向 evidence；没有 evidence 的猜测必须放到 gap/open question，而不是写成测试项。

### `$ai-integration-test-generator`

基于 repository adapter 生成或更新 integration-test assets。

依赖 `.ai-workflow.yaml` 中的 adapter：

```yaml
adapter:
  source_paths: [...]
  test_paths: [...]
  generated_test_destinations: [...]
  report_paths: [...]
commands:
  integration_test: [...]
protected_paths: [...]
```

它只写 adapter 授权的测试路径，优先写 `generated_test_destinations`；不修改生产代码，不写 protected paths。adapter 不足时会停止并要求补配置。

### `$ai-integration-test-v2`

执行、诊断和收敛 integration tests。

流程：

```text
execute -> diagnose -> classify -> fix -> rerun
```

失败分类：

```text
implementation bug
test asset bug
environment issue
mock/fixture drift
```

核心纪律：不能为了通过测试而把 expected output 改成 broken behavior；每次只改一个归因，并用 rerun evidence 证明。

### `$ai-ci-failure-triage`

CI 失败事实收集和路由。适合用户给出 CI job、失败日志或流水线失败时使用。

流程：

```text
collect facts -> classify -> route -> report
```

先收集 job URL、commit、branch、stage、command、exit status、bounded logs、changed files 和环境信息，再分类为 environment/build/unit-test/integration-test failure。证据不足时不直接修复。

## Recommended Usage Order

小改动：

```text
$ai-small-tdd-change -> $ai-git-handoff
```

完整需求：

```text
$ai-workflow-harness -> $ai-knowledge-reflection -> $ai-knowledge-governance -> $ai-git-handoff
```

需求不清楚：

```text
$ai-workflow-harness-grill -> implement/verify -> reflection/governance -> git handoff
```

测试规划和生成：

```text
$ai-integration-test-checklists -> $ai-integration-test-generator -> $ai-integration-test-v2
```

CI 挂了：

```text
$ai-ci-failure-triage -> 按分类路由到对应 Skill
```

## Example

`examples/language-neutral` 是离线接入样例。它使用 schema v2 配置 `build` 与 `unit_test` 命令，禁用 `verify.integration_test`，并把 Wiki 指向 sibling `../../wiki`。

真实 Codex trial 请按 [docs/wave-1-trial.md](docs/wave-1-trial.md) 执行，并把 evidence template 填回。当前 traceability 只记录本地离线证据；未声明 Codex 或 Claude Code 已完成真实客户端验收。

Wave 2 真实客户端 trial 请按 [docs/wave-2-trial.md](docs/wave-2-trial.md) 执行；未回填 evidence 前，不声明 `reference-parity`。
