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
- 幂等：同一 gate 同一内容不重复推送；`--force` 强制重发。
- 失败只写 warning，不中断 workflow。

## 何时调用

- Review Gate：`workflow review` 返回 `human_review` 后。
- Blocked：进入 `run_blocked` 后。
- Knowledge Governance：需要人工 promote/reject/保持时。
- Git Handoff：需要人工 skip/commit/MR 时。

## 输出

`{"ok": true, "data": {"sent": bool, "dedup": "...", ...}}`。`sent=false` + `reason` 时按 no-op 处理。
