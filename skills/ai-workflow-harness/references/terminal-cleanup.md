# Terminal cleanup

仅当 `workflow status` 明确为 `completed` 或 `aborted` 时进入。顺序固定，terminal run 本身不再修改。

## 1. terminal human completion

向人类展示最终 status、各 phase 结果、未解决 findings 和 aborted 原因（如有）。等待人类确认进入 cleanup；这是一道人类 gate，不能以沉默代替。

## 2. terminal reflection

调用 `$ai-knowledge-reflection`，把 Helper 记录的 terminal evidence 交给其 `knowledge-reflector`，产出 `knowledge-reflection.json`。Harness 不自行反思、不补写结论。即使 aborted 也必须执行 reflection。

## 3. governance choice

若 reflection 产生 candidate，调用 `$ai-knowledge-governance` 展示重复、冲突、适用范围和 evidence，让人类选择 promote/reject/archive/supersede。没有明确人类决定时只保留 candidate；绝不写 `wiki/approved`。

## 4. summary

```text
ai-workflow workflow summary --repo REPO --run-id RUN
```

汇总 phase durations、attempt/rerun 次数、review gates 与 cited knowledge IDs，并附 reflection/governance 的实际状态。

## 5. Git handoff

最后调用 `$ai-git-handoff`。先只读检查 status/diff，再让人类选择 skip、commit current branch 或 create branch/MR。commit、branch、push、MR、merge、丢弃改动等 Git handoff 动作都有人类 gate；Harness 不自行执行破坏性操作。

cleanup 尚未完成时，新会话先 `workflow status` 确认 terminal，再从未完成的最早人类 gate 恢复。
