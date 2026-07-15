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

`completed` 或 `aborted` 不可 begin/stage/finalize/review/transition。进入 terminal cleanup；重复会话只恢复尚未完成人类 gate 的 cleanup，不改变 run。

## stale / conflict

- stale attempt：Child 不修改 `state.yaml`，不替换 attempt ID，也不调用 workflow helper。Harness `status -> begin` 获取当前 prompt，重新 dispatch 原 Child；Child 只重新生成自己的 artifact/ChildResult。
- staged result conflict：保留两份原始证据并停下，不覆盖。
- `stale_review_gate`：先 `status`。若持久 gate 仍 stale，禁止循环调用 `review`；由 Harness 执行 `workflow block --reason "stale review gate cannot be refreshed"`，展示证据并等待人类 `resume`/`abort`。人类 resume 清除旧 gate 后才重新 `review`，旧 acceptance 永久作废。
- event/state integrity error：fail closed 并报告人类；绝不手工 repair state。
