# WeCom 人工干预通知使用指南

本指南说明如何为 `be-aicoding-workflow` 配置并启用**企业微信（WeCom）人工干预通知**。

工作流中的 Review Gate、Blocked、Knowledge Governance、Git Handoff 是需要人工干预的节点。启用 WeCom 通知后，团队全员通过企业微信收到提醒，并标注「开启者」与「授权操作者」。

> 状态：**Plan 1（通知推送）已实现**。本指南只覆盖推送；"在企业微信中回复即处理"（回调服务）属于 Plan 2，尚未实现，见文末「当前限制」。

## 功能概览

- 人工节点触发时，向企业微信**通讯录标签**（通知组）推送一条 Markdown 消息。
- 消息含 `👤 开启者`（创建者）与 `🔑 授权操作者`（白名单）标注。
- 幂等去重：同一 run 同一 gate 同一阶段内容不重复推送。
- 软失败：网络/API/配置失败返回错误但不影响工作流主流程。
- secret 只从环境变量读取，不落盘。

## 一、企业微信侧准备

需要企业微信管理员/应用负责人权限，配置一次：

1. **创建自建应用**（管理后台 → 应用管理 → 创建应用）
   - 记录三个值：**CorpID**（企业 ID）、**AgentID**（应用 ID）、**Secret**（应用密钥）
   - 设置应用的**可见范围**为需要接收通知的成员/部门
2. **创建通讯录标签**（通讯录 → 标签管理 → 新建）
   - 例如标签名 `工作流通知组`，把团队成员加入
   - 推送目标为 `totag`，圈内成员都会收到

> 回调相关（`Token`/`EncodingAESKey`）是 Plan 2 的内容，当前无需配置。

## 二、配置 `.ai-workflow.yaml`

在项目根目录 `.ai-workflow.yaml` 添加 `wecom:` 块：

```yaml
repository: your-repo
wecom:
  enabled: true
  corpid_env: WECOM_CORPID          # 环境变量名（不是值！）
  agentid_env: WECOM_AGENT_ID
  agent_secret_env: WECOM_AGENT_SECRET
  notify_tag: 工作流通知组          # 通讯录标签名，运行时解析为 tagid
  creator_userid_env: WECOM_CREATOR_USERID
  gates: [review, blocked, governance, git_handoff]   # 可只保留部分节点
```

字段说明：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `enabled` | 是 | 是否启用通知（默认 false） |
| `corpid_env` / `agentid_env` / `agent_secret_env` | 是 | 对应 secret 的**环境变量名** |
| `notify_tag` | 是 | 通知组标签名 |
| `creator_userid_env` | 否 | 创建者 userid 的环境变量名（默认 `WECOM_CREATOR_USERID`） |
| `gates` | 否 | 启用通知的节点，默认全部四个 |

## 三、设置环境变量

secret 只从环境变量读取，`wecom:` 块中存放的是变量名：

```bash
export WECOM_CORPID=ww1234567890abcdef
export WECOM_AGENT_ID=1000002
export WECOM_AGENT_SECRET=你的应用密钥
export WECOM_CREATOR_USERID=sunxianshun   # 你的企微 userid，init 默认操作者
```

## 四、开工作流时指定操作者

```bash
ai-workflow workflow init --repo "$PWD" \
  --source-revision "$(git rev-parse HEAD)" \
  --requirement "实现订单导出模块" \
  --operators "sunxianshun,wangxiaofei"    # 可多个；省略则只有创建者
```

- 操作者写入 `state.artifacts["operators"]`。
- **创建者始终在列**：未传 `--operators` 时，从 `WECOM_CREATOR_USERID` 取值作为默认操作者。

## 五、触发通知

### 自动触发（推荐）

`$ai-workflow-harness`、`$ai-git-handoff`、`$ai-knowledge-governance` 三个 skill 已内置：到达 Review Gate / Blocked / terminal 的 governance / git handoff 节点时自动调用通知。正常跑工作流即可，无需手动操作。

### 手动调用

```bash
# Review Gate（plan 阶段）
ai-workflow wecom notify --repo "$PWD" --run-id RUN-xxx \
  --gate review --phase plan \
  --action "接受或修改 rerun proposal" \
  --summary "plan.solution 已完成，需审核"

# Blocked
ai-workflow wecom notify --repo "$PWD" --run-id RUN-xxx \
  --gate blocked --phase implement \
  --action "请选择 resume 或 abort" \
  --summary "环境/权限失败"

# 不真发，只看消息内容（调试）
ai-workflow wecom notify --repo "$PWD" --run-id RUN-xxx \
  --gate review --phase plan --action "x" --dry-run
```

命令参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--repo` | 是 | 仓库根目录 |
| `--run-id` | 是 | 目标 run |
| `--gate` | 是 | `review` / `blocked` / `governance` / `git_handoff` |
| `--action` | 是 | 人类需要做什么（写入消息） |
| `--phase` | 否 | 阶段（review/blocked 建议提供） |
| `--summary` | 否 | 附加摘要 |
| `--force` | 否 | 跳过去重，强制重发 |
| `--dry-run` | 否 | 只打印消息不真发 |

## 六、团队成员收到的消息

```markdown
**🔔 工作流需要人工处理**

👤 开启者：@sunxianshun
🔑 授权操作者：@sunxianshun @wangxiaofei
📌 类型：Review Gate（plan 阶段）
🆔 Run ID：`RUN-xxx`
🏷 摘要：实现订单导出模块
📁 仓库：your-repo

plan.solution 已完成，需审核
请授权操作者处理：接受或修改 rerun proposal
其他成员仅收到通知，请勿直接操作本工作流。
```

## 七、行为细节

| 特性 | 行为 |
| --- | --- |
| 幂等去重 | key = `(run_id, gate, phase, 内容摘要)`；同内容不重复推送 |
| `--force` | 跳过去重强制重发 |
| `--dry-run` | 只打印不发送 |
| 软失败 | 网络/API/环境变量缺失 → `{"sent": false, "error": ...}` 且 exit 0，不影响工作流 |
| 未配置时 | `enabled: false` 或 gate 未启用 → no-op，不报错 |
| 记录位置 | `.ai-workflow/notifications/<run_id>.json`（已 gitignore） |
| secret | 只从环境变量读，配置文件里是变量名 |

## 八、当前限制（Plan 2 未做）

- 目前**只能推送，不能在微信里回复处理**。"回复即处理"（accept / resume / promote / commit / MR 二次确认）依赖 `ai-workflow wecom serve` 回调服务，属于 Plan 2，尚未实现。
- 因此人工节点仍需开跑者在**本地终端**处理，微信通知仅作提醒与授权标注。
- 阿里云服务器、回调域名、回调 `Token`/`EncodingAESKey` 当前都用不上。
