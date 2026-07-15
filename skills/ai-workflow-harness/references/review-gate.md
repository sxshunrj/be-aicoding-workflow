# Review Gate

Review Gate 位于 `finalize` 和 `transition` 之间；Helper 只校验提案，Harness 负责语义判断，人类拥有要求人工的决定。

## 1. 形成 actionable node reasons

读取 phase aggregate、Child `findings`、报告证据和 `status.run_graph`。对需要 rerun 的每个 node 生成 `NODE=REASON`：

- NODE 必须是当前或更早的具体 node，如 `implement.code`，不是 phase 名。
- REASON 必须描述可执行修复与证据；禁止空白、`TODO`、`fix it` 或 Helper 的 placeholder。
- `unable_to_complete` 必须转换为有证据的 actionable reason，不能直接沿用 `child unable to complete; workflow must provide an actionable reason`。

没有 rerun 也必须调用 `workflow review`。

```text
ai-workflow workflow review --repo REPO --run-id RUN [--rerun NODE=REASON ...]
```

## 2. wait / accept

- `decision=human_review`：向人类展示 phase、evidence、effective reruns 和 `digest`，等待“接受此 digest”或修改意见。沉默不是接受。
- `decision=accept`：只接受 Helper 已持久化的 auto-accept；Harness 不自行构造。
- verify 的 terminal review 永远是 human review。任何配置都不能跳过它。

人类明确接受时记录同一 digest：

```text
ai-workflow workflow review-accept --repo REPO --run-id RUN --expected-digest DIGEST
```

若 digest/state version 已 stale，回到 `status -> review`，重新向人类展示；禁止复用旧接受。

## 3. transition

只有 gate 已持久化接受后才调用：

```text
ai-workflow workflow transition --repo REPO --run-id RUN
ai-workflow workflow status --repo REPO --run-id RUN
```

`transition` 只消费已接受 gate：无 rerun 时推进 phase，有 rerun 时回到最早 node 并使下游 pending。不得把 rerun 参数传给 transition。
