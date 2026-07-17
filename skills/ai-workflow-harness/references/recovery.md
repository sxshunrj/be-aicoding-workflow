# Recovery：从持久化证据恢复

任何新会话、context compaction、stale error、工具中断或不确定状态都从下面命令开始：

```text
ai-workflow workflow status --repo REPO --run-id RUN
```

这就是 `new-conversation status recovery` / `new conversation` 恢复入口。不得从 chat 推断 attempt、staged child、review acceptance 或下一 phase。

恢复原则：

- status 是唯一入口；
- begin 恢复 attempt；
- stage/finalize/review 只消费持久化 evidence；
- Child 不处理 recovery；
- Harness 不手改 state；
- 不得从聊天记录重建 state。

## status routing

### running / pending

1. 读取 `current_phase`、`run_graph` 和状态中的 attempt metadata。
2. 再调用当前 phase 的 `begin`。它会恢复同一 attempt；`dispatch_plan` 中 `already_staged` 的 child 不重派。
3. 对仍为 `dispatch`/`rerun` 的项，只使用新返回的 `prompt_file` 重建 Child 上下文。
4. staged siblings 保持 barrier 已关闭；不要从聊天复制旧 JSON 再 stage。
5. 若已有 phase aggregate，转入 review；若已有 `review_gate`，按其 decision/digest 恢复等待或接受，绝不重建 gate。

running 恢复表：

| status evidence | next action |
| --- | --- |
| 无 current attempt | `workflow begin --phase current_phase` |
| 有 current attempt 且 dispatch 未完成 | `workflow begin`，只派发 `dispatch`/`rerun` item |
| 有 staged child | 不重派该 child；等待其余 sibling |
| barrier 满足但无 aggregate | `workflow finalize` |
| 有 aggregate 但无 review gate | 推导 proposed rerun 后 `workflow review` |
| 有 review gate 且 `human_review` | 重新展示 digest，等待人类 |
| gate 已 accept | `workflow transition`，随后 `status` |

不要从 chat 里的“某 child 已经完成”来替代 staged evidence；只有 Helper state 中的 staged metadata 算数。

### blocked

展示 blocker、prior phase/status 与 rerun evidence。只接受人类明确选择：

```text
ai-workflow workflow resume --repo REPO --run-id RUN [--rerun NODE=REASON ...]
ai-workflow workflow abort --repo REPO --run-id RUN
```

裸 `resume` 只解锁；带 rerun 必须有 actionable node reason。Harness 不自动 resume/abort。

blocked 菜单：

```text
当前 run 已进入 blocked：<reason>

请选择：
1. 继续（如需调整节点请补充反馈；不补充则直接解锁）
2. 终止

请直接回复 1 / 2。
```

如果用户补充反馈，Harness 先映射到 node reason，再 `resume --rerun NODE=REASON`。反馈无法映射时继续问，不猜。

### terminal

`completed` 或 `aborted` 不可 begin/stage/finalize/review/transition。进入 terminal cleanup；每次新会话都从其步骤 1 安全幂等重放，不根据 chat 猜测 cleanup 进度。

terminal 恢复只做幂等读写：

1. `workflow summary` 纯读；
2. 检查 terminal reflection 是否已经有 accepted artifact；
3. 检查 candidate/approved/archived 状态；
4. 重新检查 Git status/diff；
5. 重新询问 Git handoff 决策。

不存在 cleanup checkpoint；不得假装知道上次中断点。

## stale / conflict

- stale attempt：Child 不修改 `state.yaml`，不替换 attempt ID，也不调用 workflow helper。Harness `status -> begin` 获取当前 prompt，重新 dispatch 原 Child；Child 只重新生成自己的 artifact/ChildResult。
- staged result conflict：保留两份原始证据并停下，不覆盖。
 - stale ChildResult：只说明该 result 不属于当前 attempt。Harness 走 `status -> begin -> redispatch owner child`；Child 不调用 `workflow status`、不调用 `workflow begin`、不改 JSON attempt。
Review error 必须按互斥 route 处理：

| error.code | exact route | 禁止动作 |
| --- | --- | --- |
| `review_gate_mismatch` | `workflow status -> workflow review` | 不进入 block |
| `stale_review_gate` | `workflow status -> workflow block -> human resume/abort` | 禁止继续 review |

- `review_gate_mismatch`：`status` 读取当前持久 gate，再重新 `review` 并展示新 digest。
- `stale_review_gate`：`status` 确认后直接执行 `workflow block --reason "stale review gate cannot be refreshed"`，不得尝试 review。等待人类 `resume`/`abort`；旧 acceptance 作废。
- event/state integrity error：fail closed 并报告人类；绝不手工 repair state。

## Recovery boundaries

| 问题 | 允许 | 禁止 |
| --- | --- | --- |
| prompt file 丢失或 digest 不符 | block，报告 evidence | 手工重写 prompt |
| dispatch packet mismatch | block 或重新 begin 当前 phase | 改 packet 字段 |
| result digest mismatch | owner child 重产 artifact/result | Harness 改 digest |
| path_not_authorized | fail closed，修 adapter/config 或 owner output | 读写父目录 |
| invalid_state | block，人工处置 | 手改 YAML |
| unknown error.code | status 后 fail closed | 按 message 猜恢复 |

## New conversation checklist

每次新对话或压缩后，按顺序：

1. 确认 repo 和 run id。
2. 调 `workflow status`。
3. 把 status 分类为 running / blocked / terminal。
4. running：调用 `workflow begin` 或进入已有 review gate。
5. blocked：展示 blocked 菜单。
6. terminal：进入 terminal cleanup 幂等重放。
7. 不复用上个对话里的 attempt id、review digest、child JSON、Git handoff 选择。
