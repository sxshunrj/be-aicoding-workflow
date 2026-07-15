---
name: ai-workflow-harness
description: Use when 用户显式要求持久化四阶段 AI 编码工作流、恢复 ai-workflow run，或明确要求 child agents 与 review gates 的 ai-workflow 场景。
---

# AI Workflow Harness

把 Agent 的语义判断与 Helper 的机械校验分开。run 的唯一事实来源是持久化状态，不是聊天记录。

## Hard gates

- 固定控制顺序：`status -> begin -> dispatch -> stage -> barrier -> finalize -> review -> transition -> status`。
- `Never edit state.yaml directly`：禁止直接创建、修改或修复 `.ai-workflow/runs/**`；只调用 Helper CLI。
- `dispatch all sibling children before waiting`；`silence is not failure`，无显式 `ChildResult` 就继续等待。
- `ChildResult-only completion`：消息、沉默、tool error、部分报告都不算 child 完成。
- `mandatory human gates`：blocked 的 `resume`/`abort`、要求人工的 review、terminal completion、knowledge governance 与 Git handoff 都必须等待人类明确决定。

## Workflow ownership boundary

Harness 只负责调度、校验、stage、汇总与向人类呈现证据。`Harness 绝不执行 child-owned coding、testing、case repair 或 code review`，也不代写缺失的 child 结果。

只有 Harness 主 Agent 调用 workflow helper。Child 的唯一初始上下文是 Helper 生成的 `prompt_file`；Child 只做该 prompt 授权的工作并返回 schema-v2 `ChildResult`，不得自行调用 `status`、`begin`、`stage` 或取得 attempt。详见 [dispatch 纪律](references/subagent-dispatch.md) 与 [共同 Child contract](references/agents/common-phase-contract.md)。

## Main loop

先按 [bootstrap](references/bootstrap.md) 确定唯一 `run_id`，并从 [Helper CLI](references/helper-cli.md) 读取 JSON。每个 phase 按 [subagent dispatch](references/subagent-dispatch.md) 执行固定控制顺序；barrier 后按 [Review Gate](references/review-gate.md) 产生可行动的 node reason。`transition` 后立即再次 `status`，不得凭记忆推进。

知识只能按 [knowledge loop](references/knowledge-loop.md) 的 packet/citation 规则进入 Child。

## Running / blocked / terminal routing

- running/pending：继续主循环。
- blocked：停下并呈现证据，只按人类选择 `resume` 或 `abort`。
- terminal：执行 [terminal cleanup](references/terminal-cleanup.md)。
- 新会话、stale 或不确定状态：执行 [new-conversation status recovery](references/recovery.md)，禁止从 chat 重建。

## Reference index

- 编排：[bootstrap](references/bootstrap.md)、[Helper CLI](references/helper-cli.md)、[dispatch](references/subagent-dispatch.md)、[review](references/review-gate.md)、[recovery](references/recovery.md)、[terminal reflection / Git handoff](references/terminal-cleanup.md)、[knowledge](references/knowledge-loop.md)。
- Child：[common](references/agents/common-phase-contract.md)、[spec](references/agents/spec-writer.md)、[planner](references/agents/planner.md)、[coder](references/agents/coder.md)、[test runner](references/agents/test-runner.md)、[code reviewer](references/agents/code-reviewer.md)、[knowledge reflector](references/agents/knowledge-reflector.md)。
