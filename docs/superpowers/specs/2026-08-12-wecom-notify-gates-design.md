# AI Workflow 企业微信人工干预通知与回复处理设计

日期：2026-08-12
状态：修订版（v2，由微信方案改为企业微信方案）

## 背景与目标

`be-aicoding-workflow` 提供 Skill-first 的本地 AI coding workflow（`spec -> plan -> implement -> verify`）。工作流中存在多类需要人工干预的节点（human gates）：Review Gate、Blocked、Knowledge Governance、Git Handoff。当前这些节点只在开跑者本地终端等待。

目标：通过**企业微信**，在需要人工干预的节点通知团队，并支持**在企业微信中回复即处理**。约束：

- 免费为主；只有阿里云轻量云服务器（公网 IP）、无域名。
- 支持多人使用；团队通讯录（企业微信标签）作为"通知组"。
- 开启工作流时可指定操作者（创建者默认，可多个）；未指定成员只收到通知，不可操作。

## 关键决策

| 决策点 | 结论 | 理由 |
| --- | --- | --- |
| 通道 | 企业微信自建应用 | 团队通讯录标签作通知组、支持回复即处理 |
| 通知组 | 企业微信**标签**（`totag` 推送） | 跨部门自由圈人，成员增删在标签维护 |
| 回调域名 | **免费穿透随机域名**（ZeroNews / Cloudflare Tunnel / ngrok） | 无域名、无备案；穿透借公网 HTTPS 域名 |
| 回调宿主 | **本地回调**（开跑者机器，run state 所在） | 回调需执行本地 run 操作；无共享状态 |
| 回复处理 | 全部四类：review / blocked / governance / git_handoff | 所有需要人工处理的节点 |
| 阿里云服务器 | **本设计不需要** | run state 在本地，服务器够不到；仅未来离线中继可考虑 |
| 授权模型 | 指定操作者白名单（创建者默认） | 通知标注 + 回调鉴权 |
| secret | 环境变量，不落盘 | 安全 |

## 架构

```
你的本地（工作流所在机器）                  企业微信
┌─────────────────────────────┐         ┌─────────────────┐
│ 本地回调服务 ai-workflow wecom serve │         │                 │
│   └─ 校验签名 → 解密 → 鉴权         │◄────────│  成员回复消息     │
│   └─ 解析命令 → 执行 run 操作(锁)    │  回调   │                 │
│   └─ 回复确认                        │         │                 │
│ 穿透隧道 (ZeroNews/CF Tunnel) ◄──公网HTTPS │         │                 │
└─────────────────────────────┘         └─────────────────┘
          ↑ message/send (totag 通知组推送)
```

### 组件

1. **企业微信自建应用**（管理员一次配置，你有权限）
   - `corpid / agentid / secret` + 回调 `Token / EncodingAESKey`
   - 回调 URL = 穿透隧道公网 HTTPS 域名 + 本地服务路径，通过企微 GET 校验（签名+echostr，1 秒内返回）
   - 通知组标签：通讯录→标签管理→建"工作流通知组"，圈人；推送用 `totag`

2. **`.ai-workflow.yaml` 新增 `wecom:` 块**
   ```yaml
   wecom:
     enabled: true
     notify_tag: "工作流通知组"     # 通讯录标签名 → 运行时解析为 tagid
     callback_token_env: WECOM_CALLBACK_TOKEN
     callback_aeskey_env: WECOM_CALLBACK_AESKEY
     agent_secret_env: WECOM_AGENT_SECRET
     gates: [review, blocked, governance, git_handoff]
   ```

3. **Helper 新增两条命令**（确定性、幂等、软失败、dry-run）
   - `ai-workflow wecom notify` —— 推送通知给标签通知组，幂等去重（`(run_id, gate, phase, content_digest)`），软失败不影响主流程
   - `ai-workflow wecom serve` —— 本地 HTTP 回调服务：校验签名 → AES 解密 → 解析命令 → 鉴权 → 调用既有 `record_review_acceptance`/`block`/`resume`/wiki lifecycle/git-handoff 方法 → 回复确认

4. **授权标注**：`workflow init --operators` 指定操作者（创建者默认），写入 `artifacts["operators"]`；通知与回调鉴权都从它读取

5. **Skill 集成**：四个 Skill 在人工 gate 处调用 `wecom notify`

### 回调服务流程（回复即处理）

```text
成员在企微应用回复命令
→ 企微 POST 加密 XML 到回调 URL（穿透隧道 → 本地服务）
→ 校验签名 + AES 解密
→ 鉴权：回复者 userid 必须在 artifacts["operators"]（创建者默认在列）
→ 解析命令（见下）
→ 调用既有服务方法执行 run 操作（event_lock 串行，防并发）
→ 构造被动回复（5 秒内返回）确认结果
```

**Git Handoff 二次确认流程：**

```text
授权者回复 commit
→ 回调校验签名/鉴权 → 解析为 git_handoff commit
→ 因 commit/MR 不可逆：先向该授权者推送「确认卡」（列出将提交的文件/分支/MR 信息）
→ 授权者再回复「确认」→ 回调在开跑者本地执行 git 操作
→ 推送执行结果；未二次确认则不执行
```

## 消息内容与 @ 标识

Markdown 格式（企微 textcard/markdown 支持）：

```markdown
**🔔 工作流需要人工处理**

👤 开启者：@sunxianshun
🔑 授权操作者：@sunxianshun @wangxiaofei
📌 类型：Review Gate（plan 阶段）
🆔 Run ID：`a1b2c3d4`
🏷 摘要：实现订单导出模块，含单元测试

**当前状态：**
- plan.solution 已完成，需要审核
- 需重跑：`plan.test_strategy`（测试策略与实现不一致）

请授权操作者回复命令处理：
- review：回复 `accept` 或 `rerun <node>:<原因>`
- blocked：回复 `resume` 或 `abort`
- governance：回复 `promote` / `reject` / `保持`
- git_handoff：回复 `skip` / `commit` / `MR`（commit/MR 将收到确认卡，再回复确认后执行）
其他成员仅收到通知，请勿回复操作。
```

## 回复命令语法

| Gate | 命令 | 对应 Helper 方法 |
| --- | --- | --- |
| review | `accept` / `rerun <node>:<原因>` | `record_review_acceptance`（accept 带 expected digest）/ `review` |
| blocked | `resume` / `abort` | `resume` / `abort` |
| governance | `promote` / `reject` / `保持` | wiki lifecycle |
| git_handoff | `skip` / `commit` / `MR`（commit/MR 需**二次确认**） | git-handoff 由回调在开跑者本地执行；commit/MR 不可逆，先发确认卡、授权者再回一条确认才执行 |

## 错误处理与边界

| 场景 | 行为 |
| --- | --- |
| 推送网络/API 失败 | `wecom notify` 返回 sent=false + error，写 warning，不影响主流程 |
| 签名校验失败 | 回调返回 401，拒绝执行 |
| 解密失败 / 命令无法解析 | 回复"命令无法识别"，不执行 |
| 未授权 userid 回复 | 回复"无操作权限"，不执行 |
| run 操作抛 AppError | 把错误回成被动回复，run 状态不变 |
| `wecom:` 未配置 / enabled=false | notify no-op；serve 不启动 |
| 机器关机 | 企微回调重试 3 次后丢弃（本地回调固有代价，已接受） |

## 测试策略

| 层 | 覆盖 | 落点 |
| --- | --- | --- |
| unit | 配置解析、标签→tagid 解析、幂等去重、消息渲染、命令解析（含非法命令）、签名/解密 | `tests/unit/wecom/` |
| contract | 四个 Skill 契约引用 `wecom notify`；CLI envelope | `tests/contract/test_wecom_skill.py` |
| e2e | fake transport + fake 企微 server：notify→serve→回调→回复→执行→确认，全链路 | `tests/e2e/test_wecom_callback.py` |

测试不真连企微；用 fake transport / fake server，本地离线跑。真实对接用 `--dry-run` + 手动脚本验证一次。

## 成功标准

- `wecom notify` fake transport 下幂等去重正确。
- `wecom serve` 收到合法签名+授权回复后，能调用既有方法执行 review/blocked/governance/git_handoff 操作并回复确认。
- 未授权回复被拒绝；非法命令被拒绝且 run 状态不变。
- 四个 Skill contract test 引用 `wecom notify`。
- 全量 `pytest -q` 通过；`.ai-workflow/notifications/` 不污染 run state。

## 非目标

- 不做共享 run 状态的多人协作（run state 在开跑者本地）。
- 阿里云服务器不作为回调宿主或离线中继（本地回调已够用；离线中继列为 future）。
- 不做内容审计；不推送文件内容、diff 或日志。
- 不做企业微信 OAuth 登录等额外集成。

## 附录：穿透隧道与企微配置要点

- ZeroNews 提供专门解决企微回调握手的方案（自动响应 GET 校验）；备选 Cloudflare Tunnel / ngrok。
- 企微回调 URL 校验会验证域名可解析且 HTTPS 可达；纯 IP 地址不接受。
- 自建应用可见范围需包含通知组标签成员；message/send 的 `totag` 要求对标签有查看权限。
