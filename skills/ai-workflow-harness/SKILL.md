---
name: ai-workflow-harness
description: Use when 用户显式要求持久化四阶段 AI 编码工作流、恢复 ai-workflow run，或明确要求 child agents 与 review gates 的 ai-workflow 场景。
---

# AI Workflow Harness

把 Agent 的语义判断与 Helper 的机械校验分开。run 的唯一事实来源是持久化状态，不是聊天记录。这个 Skill 是用户可见的主产品面：它决定何时工作、由哪个 child 负责、需要什么 evidence、何时询问人类；Python Helper Core 只维护 deterministic invariants。

## Hard gates

- 固定控制顺序：`status -> begin -> dispatch -> stage -> barrier -> finalize -> review -> transition -> status`。
- `Never edit state.yaml directly`：禁止直接创建、修改或修复 `.ai-workflow/runs/**`；只调用 Helper CLI。
- `dispatch all sibling children before waiting`；`silence is not failure`，无显式 `ChildResult` 就继续等待。
- `ChildResult-only completion`：消息、沉默、tool error、部分报告都不算 child 完成。
- `mandatory human gates`：blocked 的 `resume`/`abort`、要求人工的 review、terminal completion、knowledge governance 与 Git handoff 都必须等待人类明确决定。
- `run_graph 是唯一调度真值`：pending/valid/rerun 与 reason 只能由 Helper state 表达；聊天、记忆或单个 child 反馈不能替代 graph。
- 先推导 rerun proposal，再进入 Review Gate；Review Gate accept 后才允许 transition。
- blocked 不受 auto_accept 影响；terminal completion、knowledge governance 和 Git handoff 也不受 auto_accept 影响。
- 任何 state、attempt、dispatch、review gate、artifact registry 或 lifecycle operation 异常都 fail closed；不得用手改 YAML、复制旧 JSON 或“我知道状态”来修复。

## Workflow ownership boundary

Harness 只负责调度、校验、stage、汇总与向人类呈现证据。`Harness 绝不执行 child-owned coding、testing、case repair 或 code review`，也不代写缺失的 child 结果。

只有 Harness 主 Agent 调用 workflow helper。Child 的唯一初始上下文是 Helper 生成的 `prompt_file`；Child 只做该 prompt 授权的工作并返回 schema-v2 `ChildResult`，不得自行调用 `status`、`begin`、`stage` 或取得 attempt。详见 [dispatch 纪律](references/subagent-dispatch.md) 与 [共同 Child contract](references/agents/common-phase-contract.md)。

Harness 不能为了节省一次 rerun 而接管 child 任务：

- verification 失败时，不直接跑测试、看日志、修 case 或归因；把证据映射成对应 verification 或 implementation node 的 reason。
- code review 有 finding 时，不替 reviewer 重审、降级或覆盖结论；需要重审就 rerun `verify.code_review`。
- implementation 需要改代码时，不在 Harness 中直接编辑代码；rerun `implement.code`。
- 用户反馈涉及方案、实现、测试、评审时，必须映射到唯一 `run_graph node`，经 Review Gate 后重新派发对应 child。
- 用户反馈必须映射到唯一 run_graph node；无法唯一映射时继续澄清，不猜。
- workflow 不打开 child artifact 正文来补做 child 判断；只读取 Helper 汇总、ChildResult summary/findings、Review Gate 输出和用户反馈。需要更细证据时 rerun 对应 child。

允许 Harness 自己做的事情只有：读 Helper JSON、派发 child、串行 stage、finalize、推导 rerun proposal、呈现 Review Gate、执行人类选择、terminal cleanup、调用命名 knowledge/Git handoff Skill。

## Phase model

默认四阶段：

```text
spec -> plan -> implement -> verify
```

默认 node：

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

每个 node 的调度状态只来自 Helper：

| validity | Harness 行为 |
| --- | --- |
| pending | `begin` 返回 dispatch；派发 child。 |
| valid | Helper 可复用结果；Harness 不重派。 |
| rerun | `begin` 返回 rerun；reason 必须非空且 actionable。 |

optional node 由 repository config 决定。Harness 不在 Markdown 或聊天里维护第二套启停规则。

## Main loop

先按 [bootstrap](references/bootstrap.md) 确定唯一 `run_id`，并从 [Helper CLI](references/helper-cli.md) 读取 JSON。每个 phase 按 [subagent dispatch](references/subagent-dispatch.md) 执行固定控制顺序；barrier 后按 [Review Gate](references/review-gate.md) 产生可行动的 node reason。`transition` 后立即再次 `status`，不得凭记忆推进。

知识只能按 [knowledge loop](references/knowledge-loop.md) 的 packet/citation 规则进入 Child。

主循环：

```text
workflow status
  -> running:
       workflow begin
       -> dispatch/reuse/already_staged
       -> stage every current ChildResult serially
       -> barrier
       -> workflow finalize
       -> derive proposed reruns
       -> workflow review
       -> human or accepted gate
       -> workflow review-accept when human accepted
       -> workflow transition
       -> workflow status
  -> blocked:
       show blocker and choices
       -> human resume/abort only
       -> workflow status or terminal cleanup
  -> completed/aborted:
       terminal cleanup
```

### Running phase execution

1. 调 `workflow status`，确认 `status=running` 且 `current_phase`。
2. 调 `workflow begin --phase <current_phase>`。child-backed phase 必须传 `--skill-dir`；workflow-owned Grill plan 的特殊入口由 Grill Skill 说明。
3. 对 `dispatch_plan` 中每个 `dispatch`/`rerun` sibling 先全部派发，再等待。
4. `already_staged` 不重派；`reuse` 不派发；等待缺失 sibling。
5. 每个 child 返回后，只保存原始 ChildResult JSON 到临时文件，由 Harness 串行调用 `workflow stage`。
6. 全部 required sibling stage 后调用 `workflow finalize`。
7. 读取 phase aggregate 和 Helper 输出，推导 rerun proposal。
8. 调 `workflow review`，按 decision 处理。
9. gate 接受后调 `workflow transition`，随后立刻 `workflow status`。

### Rerun proposal

先推导 rerun proposal，再进入 Review Gate。proposal 是 Harness 的语义职责，但必须只写为 `NODE=REASON`，由 Helper 校验 shape。

映射原则：

| 用户反馈或证据 | 目标 node |
| --- | --- |
| 需求、边界、验收标准不清 | `spec.spec` |
| 方案步骤、文件边界、风险/回滚 | `plan.solution` |
| 验证策略、命令、测试范围 | `plan.test_strategy` |
| 代码实现、编译错误、实现缺陷 | `implement.code` |
| build 命令失败或构建证据不足 | `verify.build` |
| 单测失败、单测覆盖不足 | `verify.unit_test` |
| 集测失败、mock/data/case 问题 | `verify.integration_test` |
| correctness/security/perf review finding | `verify.code_review` |

reason 必须可执行：包含要修正/重查的事实、证据来源和目标，不写 `fix it`、`TODO`、空字符串或 Helper placeholder。跨节点反馈拆成多条 reason；不确定是否受影响时保守提 proposal，交 Review Gate。

### Review Gate

Review Gate 是 `finalize` 与 `transition` 之间的唯一关口。Harness 不直接读取配置决定是否等待人类，只消费 `workflow review` 的 JSON decision。

- `human_review`：展示当前 phase、gate digest、产物摘要、需要重跑的节点和 reason，等待用户明确选择。
- `accept`：说明 Helper 已按当前 policy 接受，然后继续 transition。
- 人类选择修改时，重新推导 rerun proposal，再次 `workflow review`。
- 人类明确接受时，调用 `workflow review-accept --expected-digest <digest>`；digest 不匹配按 [review gate](references/review-gate.md) 恢复。

统一展示只放行动信息，不倾倒所有 valid/pending 节点。不要把内部 validity 术语直接丢给用户；用“需要重跑的节点”和原因。

## Running / blocked / terminal routing

- running/pending：继续主循环。
- blocked：停下并呈现证据，只按人类选择 `resume` 或 `abort`。
- terminal：执行 [terminal cleanup](references/terminal-cleanup.md)。
- 新会话、stale 或不确定状态：执行 [new-conversation status recovery](references/recovery.md)，禁止从 chat 重建。

### Blocked

进入 blocked 后停止 dispatch、stage、finalize、review、transition。展示：

```text
当前 run 已 blocked：<reason>

请选择：
1. 继续（如需调整节点请补充反馈；不补充则直接解锁）
2. 终止

请直接回复 1 / 2。
```

- 选 1：无反馈则 `workflow resume`；有反馈则映射到 `NODE=REASON` 后 `workflow resume --rerun NODE=REASON`。
- 选 2：`workflow abort`，然后 terminal cleanup。
- blocked 不自动恢复，不被 auto_accept 绕过。

### Terminal

completed/aborted 后不再 begin/stage/finalize/review/transition。执行 terminal cleanup：

1. `workflow summary` 是纯读。
2. 执行 terminal reflection。
3. knowledge governance 必须有人类决定。
4. Git handoff 必须有人类决定；不自动 commit、branch、push 或 MR。

### New conversation / stale

新会话或 stale 后第一步总是 `workflow status`。不要从聊天记录恢复 attempt、digest、staged child 或 phase。status 显示 current attempt 后再 begin；Helper 会返回 `already_staged`、`dispatch` 或 `rerun`。

## Reference index

- 编排：[bootstrap](references/bootstrap.md)、[Helper CLI](references/helper-cli.md)、[dispatch](references/subagent-dispatch.md)、[review](references/review-gate.md)、[recovery](references/recovery.md)、[terminal reflection / Git handoff](references/terminal-cleanup.md)、[knowledge](references/knowledge-loop.md)。
- Child：[common](references/agents/common-phase-contract.md)、[spec](references/agents/spec-writer.md)、[planner](references/agents/planner.md)、[coder](references/agents/coder.md)、[test runner](references/agents/test-runner.md)、[code reviewer](references/agents/code-reviewer.md)、[knowledge reflector](references/agents/knowledge-reflector.md)。

## Error posture

Helper error 只按 `error.code` 路由，不按 message 猜。未认识的 code：先 `status`，仍无法判定就 block。禁止扩大权限、覆盖文件、替 child 伪造成成功。

高频规则：

- `barrier_incomplete`：继续等待缺失 sibling。
- `attempt_owner_mismatch` / stale result：status -> begin -> 重新派发 owner child。
- `path_not_authorized`：fail closed；不扩大路径范围。
- `artifact_digest_mismatch` / `invalid_result`：只让 owner child 修复自己的 artifact/ChildResult。
- `review_gate_mismatch`：status -> review，不 block。
- `stale_review_gate`：status -> block -> human resume/abort。
