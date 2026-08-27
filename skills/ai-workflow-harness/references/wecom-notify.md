# WeCom 人工干预通知

到达需要人工干预的节点时，调用 Helper 通知团队。通知是增强，不是依赖：失败不影响主流程。

## 命令

```bash
ai-workflow wecom notify \
  --repo <repo> \
  [--run-id <run-id>] \
  --gate <review|blocked|governance|git_handoff|terminal> \
  --action "<人类需要做什么>" \
  [--summary "<摘要>"] \
  [--subject <去重主体>] \
  [--dry-run]
```

- `--run-id` 可选：run 内传 run-id；**run 外（独立 Git 收尾、`wiki propose` 直建候选、仓库级治理）可省略**，Helper 自动降级为 repo 级通知（省略 🆔 与 gist 行、操作者回退创建者/@all），不再因 `state_not_found` 硬失败。
- `--subject` 可选但 **governance 必传**（候选知识 id，如 `KW-pattern-xxx-001`）：subject 是跨 run、跨发送方共享的去重键，同一 subject 只要**成功推送过一次**，后续通知（无论文案、无论 run 内 run 外）一律去重，`--force` 可强制重发。推送失败不写去重日志，后续发送方仍会尝试——**去重永不会把该到的通知吞掉**。
- `--dry-run`：只打印 payload，不真发。
- 消息紧凑直指要点：`<@userid>` @ 操作者 + 动作在第一行；需求（requirement）只取首个非空行作为标题 gist（去 `#`、跳过 `---`，超 160 字节按 UTF-8 字符边界截断），**全文 PRD 不进群**；`--summary`（重跑原因/阻塞原因等）独立成块（空行分隔）并按 **360 字节显示预算**截断——群消息是提醒不是报告，完整内容始终在 run 状态与当前会话里。去重摘要按**未截断全文**计算：两轮内容前缀相同仍是不同决策，照常重新提醒。骨架与 `<@userid>` 强提醒 @ 永远保留，超长内容不会被企业微信群机器人 markdown **4096 字节**上限拒绝（否则通知静默丢失）。
- 网络级发送失败自动重试 3 次（退避），业务拒绝（`errcode != 0`）不重试。
- 幂等：同一 `(run_id, gate, phase, 内容摘要)` 不重复推送；带 `--subject` 时按 subject 键存在即去重（不限文案）；`--force` 强制重发。
- **Review / Blocked 必须传 `--phase <phase>`**：去重键含 phase，缺省时不同阶段同 gate 的内容完全相同，会互相误去重（spec 门发过后，plan 门不再推送）。
- 失败只写 warning，不中断 workflow。

## 何时调用

- Review Gate：`workflow review` 返回 `human_review` 时**自动推送**（Helper 机械保证，phase 由 Helper 自动填写），无需 skill 调用。
- Blocked：`workflow block` **自动推送**（Helper 机械保证，phase 由 Helper 自动填写），无需 skill 调用。
- Terminal Completion + Git Handoff：`workflow transition`（→completed）/ `workflow abort`（→aborted）时**自动推送一条消息**，同时请团队验收终态并决定 Git 收尾方式（合并单条发送，避免企业微信群机器人 ~20s/条 限频导致第二条被丢弃）。
- Knowledge Governance：`workflow reflect-submit` 产出 candidate 时**自动推送**（Helper 机械保证，以 `run-proposal:<run-id>` 为 subject——此时候选 entry id 尚未生成），无需 skill 调用；随后 `wiki propose` 建候选时**自动按 `--subject <entry-id>` 对齐去重**（从 proposal 的 run source 反查 run 上下文）：reflect-submit 已推送过则去重并把 entry id 记入共享日志，此前推送软失败过则由 wiki propose 补发。直接 `wiki propose --repo <repo>` 建候选（run 外直建）也自动推送（subject 即 entry id）。`$ai-knowledge-governance` 模板带 `--subject <candidate-id>` 的通知在已推送过时自动去重——**同一候选全链路只 ping 一次**，任何一环软失败则下一环兜底。
- Git Handoff：并入 Terminal Completion 消息（`workflow transition`/`workflow abort`）。run 外独立 Git 收尾时用 `$ai-git-handoff` 模板调用 `--gate git_handoff`（`--run-id` 可省略）。
- 恢复补发：`workflow status` 检测到 pending 且未通知过的 `human_review` gate 时补发一条 review 通知（幂等，dedup 抑制已通知过的）。恢复会话不再静默卡住。
- `$ai-git-handoff` / `$ai-knowledge-governance` skill 模板中的 notify 调用仍需带 `--repo <repo>`（`--run-id` 仅 run 内传；run 外省略自动降级）。

## @ 强提醒

所有通知的「授权操作者」以企业微信 `<@userid>` 提及语法渲染（真实 userid 或 `@all`），会真正 @ 到成员并触发强提醒。若 run 未记录操作者（`--operators` 与 `WECOM_CREATOR_USERID` 均缺失），依次回退：机器主机名（首段 label，可作为 userid 时）→ `<@all>` @ 全群，保证一定有人被提醒。企业微信群机器人 markdown 里纯文本 `@名字` 不触发强提醒，勿用。

## 输出

`{"ok": true, "data": {"sent": bool, "dedup": "...", ...}}`。

- 仅当 `data.sent == true` 时才向人类报告「已通知团队」。
- `sent=false` + `dedup=repeat`：已通知过、未重复推送，报告「已通知过，未重复推送」，不要写成「已通知团队」。
- `sent=false` + `reason` 时按 no-op 处理。

## 通知结果随命令返回（可观测）

`workflow block` / `workflow review` / `workflow transition` / `workflow abort` 的返回 `data.notify` 字段包含本次通知结果：`{"sent": true, "dedup": "..."}`，或 `{"sent": false, "reason"/"error": "..."}`。通知是 Helper 机械推送、结果随命令返回，**任何软失败都可见、不静默**。若 `notify.sent=false` 且带 `error`（如 `wecom_not_configured`/`wecom_http_error`），说明通知未发出，应排查而非当作已通知。

`notify.sent=true` 且带 `warning=notify_log_write_failed`：消息已送达、但去重日志写入失败（磁盘满/只读）。命令不受影响，但同一通知后续可能重发——over-notify 优于静默漏发，按已通知处理即可。
