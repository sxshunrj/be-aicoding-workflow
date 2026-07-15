# Recovery：从持久化证据恢复

任何新会话、context compaction、stale error、工具中断或不确定状态都从下面命令开始：

```text
ai-workflow workflow status --repo REPO --run-id RUN
```

这就是 `new-conversation status recovery`。不得从 chat 推断 attempt、staged child、review acceptance 或下一 phase。

## status routing

### running / pending

1. 读取 `current_phase`、`run_graph` 和状态中的 attempt metadata。
2. 再调用当前 phase 的 `begin`。它会恢复同一 attempt；`dispatch_plan` 中 `already_staged` 的 child 不重派。
3. 对仍为 `dispatch`/`rerun` 的项，只使用新返回的 `prompt_file` 重建 Child 上下文。
4. staged siblings 保持 barrier 已关闭；不要从聊天复制旧 JSON 再 stage。
5. 若已有 phase aggregate，转入 review；若已有 `review_gate`，按其 decision/digest 恢复等待或接受，绝不重建 gate。

### blocked

展示 blocker、prior phase/status 与 rerun evidence。只接受人类明确选择：

```text
ai-workflow workflow resume --repo REPO --run-id RUN [--rerun NODE=REASON ...]
ai-workflow workflow abort --repo REPO --run-id RUN
```

裸 `resume` 只解锁；带 rerun 必须有 actionable node reason。Harness 不自动 resume/abort。

### terminal

`completed` 或 `aborted` 不可 begin/stage/finalize/review/transition。进入 terminal cleanup；每次新会话都从其步骤 1 安全幂等重放，不根据 chat 猜测 cleanup 进度。

## stale / conflict

- stale attempt：Child 不修改 `state.yaml`，不替换 attempt ID，也不调用 workflow helper。Harness `status -> begin` 获取当前 prompt，重新 dispatch 原 Child；Child 只重新生成自己的 artifact/ChildResult。
- staged result conflict：保留两份原始证据并停下，不覆盖。
Review error 必须按互斥 route 处理：

| error.code | exact route | 禁止动作 |
| --- | --- | --- |
| `review_gate_mismatch` | `workflow status -> workflow review` | 不进入 block |
| `stale_review_gate` | `workflow status -> workflow block -> human resume/abort` | 禁止继续 review |

- `review_gate_mismatch`：`status` 读取当前持久 gate，再重新 `review` 并展示新 digest。
- `stale_review_gate`：`status` 确认后直接执行 `workflow block --reason "stale review gate cannot be refreshed"`，不得尝试 review。等待人类 `resume`/`abort`；旧 acceptance 作废。
- event/state integrity error：fail closed 并报告人类；绝不手工 repair state。
