# AI Workflow 企业微信人工干预通知与回复处理设计

日期：2026-08-12（状态更新：2026-08-19）
状态：v3（Plan 1 群机器人通知已实现；Plan 2 回调仍未实现）

## 背景与目标

`be-aicoding-workflow` 提供 Skill-first 的本地 AI coding workflow（`spec -> plan -> implement -> verify`）。工作流中存在多类需要人工干预的节点（human gates）：Review Gate、Blocked、Knowledge Governance、Git Handoff。当前这些节点只在开跑者本地终端等待。

目标：通过**企业微信**，在需要人工干预的节点通知团队，并（未来）支持**在企业微信中回复即处理**。约束：

- 免费为主；无域名，不依赖公网服务器。
- 支持多人使用；通知通过**群机器人**推送到群内所有成员。
- 开启工作流时可指定操作者（创建者默认，可多个）；未指定成员只收到通知，不可操作。

## 关键决策

| 决策点 | 结论 | 理由 |
| --- | --- | --- |
| 通道（Plan 1，已实现） | 企业微信**群机器人 Webhook** | URL 自带 key，配置最简 |
| 通知组（Plan 1） | 机器人所在的**群** | 圈人在企微侧建群拉人即可 |
| 通道（Plan 2，未实现） | 企业微信自建应用（回调回复即处理） | 回复需回调，需要应用 + 回调 URL |
| 回调域名（Plan 2） | 免费穿透随机域名（ZeroNews / Cloudflare Tunnel / ngrok） | 无域名、无备案；穿透借公网 HTTPS 域名 |
| 回调宿主（Plan 2） | 本地回调（开跑者机器，run state 所在） | 回调需执行本地 run 操作；无共享状态 |
| 回复处理（Plan 2） | 全部五类：review / blocked / governance / git_handoff / terminal | 所有需要人工处理的节点 |
| 阿里云服务器 | **不需要** | run state 在本地，服务器够不到；仅未来离线中继可考虑 |
| 授权模型 | 指定操作者白名单（创建者默认） | 通知标注 + 回调鉴权 |
| secret | 环境变量，不落盘 | 安全 |

## 架构（Plan 1：已实现）

```
你的本地（工作流所在机器）                  企业微信
┌─────────────────────────────┐         ┌─────────────────┐
│  人工 gate 节点              │         │  通知群          │
│   └─ ai-workflow wecom notify│───推送──▶│  群机器人        │
│       (webhook/send, key 在 URL)        │  （群内成员可见） │
└─────────────────────────────┘         └─────────────────┘
```

### 组件（Plan 1）

1. **企业微信群机器人**（群内一次配置）
   - 建群 → 群设置 → 群机器人 → 复制 **Webhook 地址**（`.../cgi-bin/webhook/send?key=...`）

2. **`.ai-workflow.yaml` 的 `wecom:` 块**
   ```yaml
   wecom:
     enabled: true
     webhook_url_env: WECOM_WEBHOOK_URL   # 群机器人 URL 的环境变量名
     creator_userid_env: WECOM_CREATOR_USERID
     gates: [review, blocked, governance, git_handoff, terminal]
   ```

3. **Helper 新增一条命令**（确定性、幂等、软失败、dry-run）
   - `ai-workflow wecom notify` —— 通过群机器人 Webhook 推送通知，幂等去重（`(run_id, gate, phase, content_digest)`），软失败不影响主流程

4. **授权标注**：`workflow init --operators` 指定操作者（创建者默认），写入 `artifacts["operators"]`；通知从这里读取并标注

5. **Skill 集成 + Helper 机械推送**：run 内所有 gate（review / blocked / governance / terminal+git_handoff 合并单条）由 Helper 在对应 CLI 命令内机械自动推送（不依赖 skill/LLM 调用）；`workflow status` 恢复时补发未通知的 pending review；run 外候选（`wiki propose`）由命令层推送。Skill 仍可在人工 gate 处补充调用 `wecom notify`，但不是通知的唯一来源。

## 架构（Plan 2：未实现，回调回复即处理）

```
你的本地（工作流所在机器）                  企业微信
┌─────────────────────────────┐         ┌─────────────────┐
│ 本地回调服务 ai-workflow wecom serve │         │                 │
│   └─ 校验签名 → 解密 → 鉴权         │◄────────│  成员回复消息     │
│   └─ 解析命令 → 执行 run 操作(锁)    │  回调   │                 │
│   └─ 回复确认                        │         │                 │
│ 穿透隧道 (ZeroNews/CF Tunnel) ◄──公网HTTPS │         │                 │
└─────────────────────────────┘         └─────────────────┘
```

Plan 2 组件与流程（保留设计，当前未实现）：

1. **企业微信自建应用**（管理员一次配置）
   - `corpid / agentid / secret` + 回调 `Token / EncodingAESKey`
   - 回调 URL = 穿透隧道公网 HTTPS 域名 + 本地服务路径，通过企微 GET 校验（签名+echostr，1 秒内返回）

2. **`.ai-workflow.yaml` 增补回调字段**（Plan 2）
   ```yaml
   wecom:
     callback_token_env: WECOM_CALLBACK_TOKEN
     callback_aeskey_env: WECOM_CALLBACK_AESKEY
   ```

3. **Helper 新增命令**（Plan 2）
   - `ai-workflow wecom serve` —— 本地 HTTP 回调服务：校验签名 → AES 解密 → 解析命令 → 鉴权 → 调用既有 `record_review_acceptance`/`block`/`resume`/wiki lifecycle/git-handoff 方法 → 回复确认

### 回调服务流程（回复即处理，Plan 2）

```text
成员在企微应用回复命令
→ 企微 POST 加密 XML 到回调 URL（穿透隧道 → 本地服务）
→ 校验签名 + AES 解密
→ 鉴权：回复者 userid 必须在 artifacts["operators"]（创建者默认在列）
→ 解析命令（见下）
→ 调用既有服务方法执行 run 操作（event_lock 串行，防并发）
→ 构造被动回复（5 秒内返回）确认结果
```

**Git Handoff 二次确认流程（Plan 2）：**

```text
授权者回复 commit
→ 回调校验签名/鉴权 → 解析为 git_handoff commit
→ 因 commit/MR 不可逆：先向该授权者推送「确认卡」（列出将提交的文件/分支/MR 信息）
→ 授权者再回复「确认」→ 回调在开跑者本地执行 git 操作
→ 推送执行结果；未二次确认则不执行
```

## 消息内容与 @ 标识（Plan 1）

Markdown 格式（企微群机器人 markdown 支持；操作者以 `<@userid>` 真正强提醒，未解析到具体 userid 时依次回退机器主机名 → `@all`）。当前实现为紧凑格式（行动项置首，PRD 标题只取 160 字节 gist，整条消息 4096 字节截断）：

```markdown
**🔔 工作流需要人工处理**
<@alice> <@bob>
👉 请审核 plan.solution（接受或提出 rerun proposal）
📌 类型：Review Gate（plan 阶段）
🆔 Run ID：`a1b2c3d4`
🏷 摘要：实现订单导出模块…
```

> 状态更新（2026-08-20）：早期版本的「👤 开启者 / 🔑 授权操作者纯文本标注、不支持真 @」格式已被替换；`render_message` 现使用 `<@userid>` 强提醒。

## 回复命令语法（Plan 2）

| Gate | 命令 | 对应 Helper 方法 |
| --- | --- | --- |
| review | `accept` / `rerun <node>:<原因>` | `record_review_acceptance`（accept 带 expected digest）/ `review` |
| blocked | `resume` / `abort` | `resume` / `abort` |
| governance | `promote` / `reject` / `保持` | wiki lifecycle |
| git_handoff | `skip` / `commit` / `MR`（commit/MR 需**二次确认**） | git-handoff 由回调在开跑者本地执行；commit/MR 不可逆，先发确认卡、授权者再回一条确认才执行 |
| terminal | `接受` / `拒绝重跑` | 终态验收；aborted 时可返回指定 phase 重跑 |

## 错误处理与边界

| 场景 | 行为 |
| --- | --- |
| 推送网络/API 失败 | `wecom notify` 返回 sent=false + error，写 warning，不影响主流程 |
| `WECOM_WEBHOOK_URL` 未设置 | `wecom notify` 返回 `wecom_not_configured`（stderr 可见），exit 0 软失败 |
| `wecom:` 未配置 / enabled=false / 无 webhook_url_env | notify no-op，不报错 |
| 签名校验失败（Plan 2） | 回调返回 401，拒绝执行 |
| 未授权 userid 回复（Plan 2） | 回复"无操作权限"，不执行 |
| 机器关机（Plan 2） | 企微回调重试 3 次后丢弃（本地回调固有代价，已接受） |

## 测试策略

| 层 | 覆盖 | 落点 |
| --- | --- | --- |
| unit | 配置解析、webhook 发送、幂等去重、消息渲染 | `tests/unit/wecom/` |
| contract | 四个 Skill 契约引用 `wecom notify`；CLI envelope（dry-run / not_enabled / 网络失败软失败 / 未设 webhook 报错）；block / review / abort / wiki propose 的 Helper 自动推送 | `tests/contract/test_wecom_notify_*.py` |
| e2e | fake transport：notify → dedup 全链路、resume 后重发、status 补发 pending review、checkpoint auto-block、dedup 日志写失败不 crash | `tests/e2e/test_wecom_notify.py`、`tests/e2e/test_wecom_notify_gates.py`、`tests/e2e/test_wecom_notify_gates_deep.py` |

测试不真连企微；用 fake transport，本地离线跑。真实对接用 `--dry-run` + 手动脚本验证一次。

## 成功标准

- `wecom notify` fake transport 下幂等去重正确。
- webhook 发送仅依赖环境变量中的 URL。
- 网络失败软失败（exit 0，stderr 有原因）；未配置时 no-op。
- 四个 Skill contract test 引用 `wecom notify`。
- 全量 `pytest -q` 通过；`.ai-workflow/notifications/` 不污染 run state。

## 非目标

- 不做共享 run 状态的多人协作（run state 在开跑者本地）。
- 阿里云服务器不作为回调宿主或离线中继（本地回调已够用；离线中继列为 future）。
- 不做内容审计；不推送文件内容、diff 或日志。
- 不做企业微信 OAuth 登录等额外集成。
- Plan 2（回调回复即处理）在实现前不启用。

## 附录：穿透隧道与企微配置要点（Plan 2）

- ZeroNews 提供专门解决企微回调握手的方案（自动响应 GET 校验）；备选 Cloudflare Tunnel / ngrok。
- 企微回调 URL 校验会验证域名可解析且 HTTPS 可达；纯 IP 地址不接受。
- 自建应用需配置接收回调事件，可见范围需包含会回复消息的成员，否则成员无法触发回调。
