# AI Workflow 微信人工干预通知设计

日期：2026-08-12
状态：已与用户确认（设计评审通过）

## 背景与目标

`be-aicoding-workflow` 提供 Skill-first 的本地 AI coding workflow（`spec -> plan -> implement -> verify`）。工作流中存在多类需要人工干预的节点（human gates）：Review Gate、Blocked、Knowledge Governance、Git Handoff。当前这些节点只在开跑者本地终端等待，团队其他成员无法感知进展，需要人工处理时也无人提醒。

目标：在需要人工干预的节点，通过**个人微信**通知提醒团队。约束：

- 免费，无自有服务器、无域名、无任何部署资源。
- 支持多人使用。
- 团队所有成员都能收到各成员开启的工作流通知，并带「@开启者」标识。
- 开启工作流时可指定本工作流的操作者（创建者默认有权限，可为多个）；未指定的成员只收到通知，不可操作/处理/回复。

## 关键决策

| 决策点 | 结论 | 理由 |
| --- | --- | --- |
| 微信打通方案 | WxPusher（公众号通道推送到个人微信） | 免费、纯云 API、无需服务器域名、支持按 UID 定向推送 |
| 多人语义 | 默认全员共享广播 + 关键节点定向授权标注 | 用户要求两者都要 |
| 操作发生地 | 通知 + 授权标注（不在微信内回复，不做共享状态） | 用户无服务器；run 状态在开跑者本地，无法在微信内直接操作 |
| 团队名单来源 | git 仓库共享 `.ai-workflow/team.yaml` | 无服务器下最自然的共享机制，git 天然同步 |
| 通知触发范围 | 全部四类：review / blocked / governance / git_handoff | 用户要求全部 |
| secret 存储 | 仅从环境变量读，绝不落盘 | 安全 |

## 架构

```
┌─ 配置层 ──────────────────────────────────────────────┐
│ .ai-workflow/team.yaml  团队名单（共享，git 同步）    │
│ .ai-workflow.yaml       notify: 块（本机开启/团队/范围）│
├─ Helper Core（确定、可测）────────────────────────────┤
│ ai-workflow notify      幂等、软失败、dry-run、去重    │
├─ Skill 层（语义决策）────────────────────────────────┤
│ harness/git-handoff/     到达人工 gate 时调用 notify   │
│ knowledge-governance                                   │
└────────────────────────────────────────────────────────┘
```

### 组件

1. **`team.yaml`**（仓库根 `.ai-workflow/team.yaml`，团队共享，git 同步）

   ```yaml
   teams:
     default:
       members:
         - name: sunxianshun
           wxpusher_uid: UID_xxx
         - name: wangxiaofei
           wxpusher_uid: UID_yyy
   ```

   - 团队名 + 成员（`name` + `wxpusher_uid`）。
   - 广播 = 给该团队**全部成员 UID** 推送；成员增删由团队维护 team.yaml，开跑者无感。

2. **`.ai-workflow.yaml` 新增 `notify:` 块**（本机控制是否开启、用哪个团队、推哪些 gate）

   ```yaml
   notify:
     enabled: true
     provider: wxpusher
     app_token_env: WXPUSHER_APP_TOKEN
     team: default
     gates: [review, blocked, governance, git_handoff]
   ```

   - secret（app token）只从环境变量读，绝不落盘。

3. **Helper 新增 `ai-workflow notify` 命令**（确定性、幂等、软失败、dry-run）。

   - 语义决策由 Skill 负责；Helper 只保证"发出可靠、不重复、不破坏主流程的通知"。

4. **授权标注**：`workflow init --operators` 指定操作者（创建者默认），写入 run state `artifacts["operators"]`；后续每个 gate 通知从 run state 读取，在消息里标注授权操作者与其他成员。

5. **Skill 集成**：`$ai-workflow-harness`（review gate / blocked / terminal）、`$ai-knowledge-governance`、`$ai-git-handoff` 四类节点各加一步调用 notify。

## 消息内容与 @ 标识

消息用 **Markdown** 渲染（WxPusher 支持，正文上限 40k 字符）。

```markdown
**🔔 工作流需要人工处理**

👤 开启者：@sunxianshun
🔑 授权操作者：@sunxianshun @wangxiaofei
📌 类型：Review Gate（plan 阶段）
🆔 Run ID：`a1b2c3d4`
🏷 摘要：实现订单导出模块，含单元测试
📁 仓库：language-neutral-example

**当前状态：**
- plan.solution 已完成，需要审核
- 需重跑：`plan.test_strategy`（测试策略与实现不一致）

请授权操作者处理。
其他成员仅收到通知，请勿直接操作本工作流。
```

- **@ 标识**：开头两行 `👤 开启者：@xxx` / `🔑 授权操作者：@xxx @yyy`。
- **唯一性**：`Run ID` + `📌 类型`（review / blocked / governance / git_handoff）+ `🧭 阶段`（blocked/review 时）组成通知的稳定 key；同一 gate 内容未变不重复推送。
- **可行动性**：每个类型带一句"请做什么"——review→"接受或修改 rerun"、blocked→"resume 或 abort"、governance→"promote/reject/保持"、git_handoff→"skip/commit/branch+MR"。
- **敏感信息**：Summary 只取 run 的 requirement（短），不粘贴文件内容、diff 或日志。
- `@` 前缀用成员 `name`（team.yaml 里的名字），识别用 name，发送用 UID。

## `notify` 命令契约与数据流

### 命令

```bash
ai-workflow notify \
  --gate review|blocked|governance|git_handoff \
  --run-id RUN-xxx \
  --phase plan \              # blocked/review 必填；governance/git_handoff 省略
  --action "接受或修改 rerun proposal" \
  --summary "实现订单导出模块"
  [--dry-run]                 # 只打印 payload，不真发
  [--force]                   # 跳过幂等去重，强制重发
```

### 输出

```json
{"sent": true, "targets": ["@sunxianshun @wangxiaofei", "others_cc": 3], "dedup": "new|repeat|content_changed"}
```

让 Skill 能读到是否真的发了、发给谁。

### 幂等去重规则（核心，防打扰）

- key = `(run_id, gate, phase, content_digest)`
- 记录在 `.ai-workflow/notifications/<run_id>.json`
- `content_digest` 不变 → `dedup=repeat`，不重发；变了 → `content_changed`，重发
- `--force` 跳过

### 软失败

网络/API/超时错误一律不抛异常，返回 JSON `{"sent": false, "error": "..."}`，写 warning 到 stderr，**绝不影响 workflow 主流程**。

### 数据流（一次 Review Gate 通知）

```text
1. 开跑者: workflow init --operators sunxianshun,wangxiaofei
        → artifacts["operators"] = ["sunxianshun","wangxiaofei"]  # 创建者默认在列
2. Harness: barrier 后 workflow review → decision = human_review
3. Harness: ai-workflow notify --gate review --run-id RUN-xxx --phase plan ...
4. Helper:  读 .ai-workflow/team.yaml → 团队 default 全部成员 UID
           读 run state artifacts["operators"] → 操作者子集
           广播给全部成员；消息里 @开启者、🔑授权操作者=[operators]
           写入 .ai-workflow/notifications/RUN-xxx.json
5. Harness: 把 JSON decision（sent/dedup）带回 Review Gate 呈现
```

## 错误处理与边界情况

| 场景 | 行为 |
| --- | --- |
| 网络/API 超时、5xx | 返回 `{"sent": false, "error": "..."}`，stderr 写 warning，workflow 照常 |
| `team.yaml` 缺失或格式错 | 返回 `sent=false` + 明确 error，不崩溃 |
| `wxpusher_uid` 缺失 | 跳过该成员，消息里注记"未配置微信，跳过：@xxx" |
| `app_token` 环境变量未设置 | `sent=false` + "WXPUSHER_APP_TOKEN 未设置" |
| 未授权成员收到广播 | 消息标注"其他成员仅收到通知，请勿直接操作本工作流" |
| `notify:` 未配置 / `enabled: false` | 整个命令 no-op，`{"sent": false, "reason": "not_enabled"}` |
| 重复内容（同 gate 同摘要） | `dedup=repeat`，不重发 |

**关键边界：通知与权限的关系。** 授权语义只通过通知内容表达（`🔑 授权操作者: @A @B` + `其他成员请勿操作`），不引入共享状态，也不做服务器端权限执行——因为这是"通知 + 授权标注"模式，实际 gate 处理仍在开跑者本地。这是有意为之的边界，防止以后膨胀成多人协作系统。

**通知日志与 path authorization 的关系：** `.ai-workflow/notifications/<run_id>.json` 与 `.ai-workflow/runs/` 同属 Helper-owned 写入。配置里 `protected_paths: [.ai-workflow/**]` 保护的是 child agent 经由 path authorization 对 `.ai-workflow/` 的访问，不约束 Helper 自身写入（Helper 本来就在 `.ai-workflow/runs/` 下写 run state）。通知日志不写入 run state。

**Git 处理：** `team.yaml` 需要提交（团队共享名单）；`.ai-workflow/notifications/` 与 `.ai-workflow/runs/` 是本地运行态，加入 `.gitignore` 不提交（`.gitignore` 追加 `.ai-workflow/notifications/` 与 `.ai-workflow/runs/`）。

## 测试策略

分层测试（对齐现有目录结构）：

| 层 | 覆盖 | 落点 |
| --- | --- | --- |
| **unit** | `TeamRegistry` 解析 team.yaml（正常/缺失/坏格式/uid 缺失）、notify 幂等去重（same→repeat / changed→重发 / force）、消息 @标识与授权标注渲染 | `tests/unit/notify/test_team.py`、`tests/unit/notify/test_notify.py` |
| **unit** | `init --operators` 写入 `artifacts["operators"]`、创建者默认在列、未知成员名报错 | `tests/unit/workflow/test_service.py` 扩展 |
| **contract** | Skill 契约：harness / git-handoff / governance 的 SKILL.md 引用 `notify` 命令；`notify` CLI 参数与 JSON 输出 envelope | `tests/contract/test_notify_skill.py`、`tests/contract/test_cli_envelope.py` 扩展 |
| **e2e** | fake transport（注入的 HTTP stub）跑通：review gate → notify → 幂等 → 第二次不重发 | `tests/e2e/test_notify_gate.py` |

**测试关键设计：不真连 WxPusher。** 用 fake transport 注入 HTTP 层，本地可离线跑、CI 稳定。真实推送由 `--dry-run` + 手动脚本验证一次即可，不纳入 CI。

## 成功标准（验收）

- `ai-workflow notify` 在 fake transport 下：首次 `sent=true`，重复 `dedup=repeat`，内容变 `content_changed` 重发。
- `init --operators sunxianshun,wangxiaofei` → state artifacts 正确，创建者自动在列。
- 三个 Skill 的 contract test 断言文档引用 notify 命令。
- 全量 `pytest -q` 通过；`.ai-workflow/notifications/` 写入且不污染 run state。
- 真实推送用 `--dry-run` 人工验证一次（不纳入 CI）。

## 非目标（Non-goals）

- 不做微信内直接回复操作（无服务器，无法接收回调）。
- 不做共享 run 状态的多人协作（保持"通知 + 授权标注"模式）。
- 不做服务器端权限执行；授权语义仅通过消息表达。
- 不做内容审计；不推送文件内容、diff 或日志。
