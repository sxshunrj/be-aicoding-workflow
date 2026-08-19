# Terminal cleanup

仅当 `workflow status` 明确为 `completed` 或 `aborted` 时进入。terminal run 本身不再修改；cleanup 的外部动作按下面顺序执行。

## 1. terminal human completion

先运行 `workflow status` 确认 terminal。向人类重新展示最终 status、各 phase 结果、未解决 findings 和 aborted 原因（如有），等待明确验收；沉默不是接受。展示前调用 `ai-workflow wecom notify --repo <repo> --run-id <run-id> --gate terminal --action "请验收 run 终态（completed/aborted）"` 通知团队；失败仅写 warning，不影响主流程。

## 2. terminal reflection

调用 `$ai-knowledge-reflection`。它先检测既有 accepted artifacts 与已有 reflection 产物：合法且 digest 一致就幂等复用，否则只从 Helper 记录的 terminal evidence 继续，产出 `knowledge-reflection.json`。Harness 不自行反思、不补写结论；即使 aborted 也执行 reflection。

## 3. status-based governance choice

先由 `$ai-knowledge-governance` 查询对象当前持久状态，再给人类与该状态匹配的选择：

| 对象状态 | 合法人类选择 |
| --- | --- |
| `candidate` | `promote` / `reject` / 保持不变 |
| `approved` | 独立退役流程：`archive` / 保持不变 |
| `archived` | 保持不变 |

Candidate governance 只能 promote、reject 或保持不变；`archive` 不是 candidate 选择。Approved 的 archive 是独立退役流程，必须重新检查 digest 并经过人类 gate。

当前没有 `wiki supersede` 命令。Supersession 只通过 proposal 的 `supersedes` / `conflicts` 关系与 governance 校验表达；暂不提供独立 supersede 命令。没有明确人类决定时保持对象当前状态。

## 4. summary

```text
ai-workflow workflow summary --repo REPO --run-id RUN
```

summary 是纯读：汇总 phase durations、attempt/rerun 次数、review gates 与 cited knowledge IDs，不把读取当成 cleanup checkpoint。

## 5. Git handoff

最后调用 `$ai-git-handoff`。每次都重新检查 Git status/diff 并再次询问，让人类选择 skip、commit current branch 或 create branch/MR。commit、branch、push、MR、merge、丢弃改动等动作都有人类 gate；Harness 不自行执行破坏性操作。

## New-conversation safe replay

当前没有 cleanup checkpoint；不得假装知道上次中断点。每次 terminal 新会话都从步骤 1 安全幂等重放：

1. 用 `status` 确认 terminal。
2. 重新展示终态验收并等待人类。
3. Reflection 检测既有 accepted artifacts，再幂等复用或继续。
4. Governance 检查当前 candidate/approved/archive 状态，只展示此刻合法选择。
5. `summary` 是纯读，可安全重跑。
6. Git handoff 重新检查 Git status/diff 并再次询问，不复用旧选择。
