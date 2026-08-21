# Bootstrap：选择唯一 run

Bootstrap 只决定“恢复还是新建”，并返回一个 `run_id`；不得开始 phase 工作。

## 1. scan

1. 确认 repository root、当前 `source_revision` 和用户的原始 `requirement`。
2. 运行 `ai-workflow config show --repo REPO`，读取 `profile` 默认值与 repository 配置。
3. 只扫描 `.ai-workflow/runs/` 的 run 目录名以发现候选；不要读取或编辑其中的 `state.yaml`。
4. 对每个候选运行 `ai-workflow workflow status --repo REPO --run-id RUN_ID`。状态、requirement、profile 与 source revision 一律以该 JSON 为准。

目录不存在表示没有候选，不是错误。

## 2. choose resume/new

- 恰有一个非 terminal run 与本次 requirement/profile 相符：选择 resume，并先进入 recovery。
- 有多个可能 run、source revision 不同或用户意图不明确：列出 `run_id` 与状态，请人类选择。**等待人类选择前**，若已配置通知通道，调用 `ai-workflow wecom notify --repo REPO --gate blocked --action "请选择要恢复的 run" --summary "存在多个候选 run，等待人类选择"` 通知团队；失败仅写 warning，不影响主流程（若已选中 run 可带 `--run-id`）。
- 没有匹配 run：新建。
- `completed`/`aborted` 不得作为可变 run 恢复；只允许 terminal cleanup。

## 3. initialize

先保留用户原始 requirement，不自行改写；profile 必须来自用户选择或 repository 默认值。运行：

```text
ai-workflow workflow init --repo REPO --source-revision SHA --requirement TEXT --profile PROFILE
```

只从 `{ "ok": true, "data": ... }` 提取新 `run_id`。若返回 `state_exists` 或并发冲突，重新 scan + status，不猜测 ID。

## 4. pin one run ID

本次 Harness 后续所有命令只使用选定的一个 `run_id`。切换 run 必须重新 bootstrap 并让人类确认；最终输出该 ID。
