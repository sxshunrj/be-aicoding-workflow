# WeCom 人工干预通知

到达需要人工干预的节点时，调用 Helper 通知团队。通知是增强，不是依赖：失败不影响主流程。

## 命令

```bash
ai-workflow wecom notify \
  --repo <repo> \
  --run-id <run-id> \
  --gate <review|blocked|governance|git_handoff|terminal> \
  --action "<人类需要做什么>" \
  [--phase <phase>] \
  [--summary "<摘要>"] \
  [--dry-run]
```

- `--dry-run`：只打印 payload，不真发。
- 幂等：同一 `(run_id, gate, phase, 内容摘要)` 不重复推送；`--force` 强制重发。
- **Review / Blocked 必须传 `--phase <phase>`**：去重键含 phase，缺省时不同阶段同 gate 的内容完全相同，会互相误去重（spec 门发过后，plan 门不再推送）。
- 失败只写 warning，不中断 workflow。

## 何时调用

- Review Gate：`workflow review` 返回 `human_review` 时**自动推送**（Helper 机械保证，phase 由 Helper 自动填写），无需 skill 调用。
- Blocked：`workflow block` **自动推送**（Helper 机械保证，phase 由 Helper 自动填写），无需 skill 调用。
- Terminal Completion：`workflow transition`（→completed）/ `workflow abort`（→aborted）**自动推送**（Helper 机械保证），无需 skill 调用。
- Knowledge Governance / Git Handoff：由 `$ai-knowledge-governance` / `$ai-git-handoff` skill 各自触发。

## 输出

`{"ok": true, "data": {"sent": bool, "dedup": "...", ...}}`。

- 仅当 `data.sent == true` 时才向人类报告「已通知团队」。
- `sent=false` + `dedup=repeat`：已通知过、未重复推送，报告「已通知过，未重复推送」，不要写成「已通知团队」。
- `sent=false` + `reason` 时按 no-op 处理。

## 通知结果随命令返回（可观测）

`workflow block` / `workflow review` / `workflow transition` / `workflow abort` 的返回 `data.notify` 字段包含本次通知结果：`{"sent": true, "dedup": "..."}`，或 `{"sent": false, "reason"/"error": "..."}`。通知是 Helper 机械推送、结果随命令返回，**任何软失败都可见、不静默**。若 `notify.sent=false` 且带 `error`（如 `wecom_not_configured`/`wecom_http_error`），说明通知未发出，应排查而非当作已通知。

`notify.sent=true` 且带 `warning=notify_log_write_failed`：消息已送达、但去重日志写入失败（磁盘满/只读）。命令不受影响，但同一通知后续可能重发——over-notify 优于静默漏发，按已通知处理即可。
