# WeCom 人工干预通知

到达需要人工干预的节点时，调用 Helper 通知团队。通知是增强，不是依赖：失败不影响主流程。

## 命令

```bash
ai-workflow wecom notify \
  --repo <repo> \
  --run-id <run-id> \
  --gate <review|blocked|governance|git_handoff> \
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

- Review Gate：`workflow review` 返回 `human_review` 后。**必须带 `--phase <当前阶段>`**。
- Blocked：进入 `run_blocked` 后。**必须带 `--phase <当前阶段>`**。
- Knowledge Governance：需要人工 promote/reject/保持时。
- Git Handoff：需要人工 skip/commit/MR 时。

## 输出

`{"ok": true, "data": {"sent": bool, "dedup": "...", ...}}`。

- 仅当 `data.sent == true` 时才向人类报告「已通知团队」。
- `sent=false` + `dedup=repeat`：已通知过、未重复推送，报告「已通知过，未重复推送」，不要写成「已通知团队」。
- `sent=false` + `reason` 时按 no-op 处理。
