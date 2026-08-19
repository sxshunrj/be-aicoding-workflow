# WeCom 人工干预通知使用指南

本指南说明如何为 `be-aicoding-workflow` 配置并启用**企业微信（WeCom）群机器人通知**。

工作流中的 Review Gate、Blocked、Terminal Completion（终态验收）、Knowledge Governance、Git Handoff 是需要人工干预的节点。启用 WeCom 通知后，团队通过企业微信群机器人收到提醒，并标注「开启者」与「授权操作者」。

> 状态：**Plan 1（通知推送）已实现，且只支持群机器人 Webhook 通道**。"在企业微信中回复即处理"（回调服务）属于 Plan 2，尚未实现，见文末「当前限制」。

## 功能概览

- 人工节点触发时，向企业微信**群机器人**推送一条 Markdown 消息（发到机器人所在的群）。
- 消息含 `👤 开启者`（创建者）与 `🔑 授权操作者` 标注。
- 幂等去重：同一 run 同一 gate 同一阶段同一内容不重复推送。
- 软失败：网络/API/配置失败返回错误但不影响工作流主流程。
- Webhook 地址只从环境变量读取，不落盘；`wecom:` 块只存**变量名**。

## 已安装 skill 的使用者：升级与使用

如果已经通过 `$ai-workflow-init` 安装过这套 skill，启用 WeCom 通知只需按下面的步骤升级你的环境。**前提要清楚：真正执行 `ai-workflow wecom notify` 的是 Python Helper Core，不是 skill。** skill 只在人工节点调用该命令，所以 Helper 代码必须同步更新，否则 skill 会自动触发但命令不存在。

### 1. 拉取含 WeCom 的源码分支并更新 Helper

> **前提**：WeCom 通知功能（含 webhook-only 精简版）目前位于 `wecom-notify-gates` 分支，**尚未合入 `main`**。只 `git pull main` 拿不到该功能；务必先切到该分支。（待该分支合入 `main` 后，此前提不再需要，直接 `git pull` 即可。）

```bash
cd <你 clone 的 be-aicoding-workflow 仓库>
git fetch origin
git checkout wecom-notify-gates       # 含 wecom notify（webhook-only 在最顶部两个提交）
git pull origin wecom-notify-gates
pip install -e '.[dev]'               # 更新 Helper Core
```

确认命令已存在：

```bash
ai-workflow --help 2>&1 | grep -c wecom    # ≥1 说明已支持
```

若仍为 0，检查是否切到了正确分支、或 Helper 重装是否成功。

### 2. 刷新 skill 安装

- **link 安装**（macOS/Linux 默认）：skill 是符号链接，切到新分支后自动跟随仓库，可跳过重装。
- **copy 安装**（Windows 默认）：必须重跑，否则仍是旧版 SKILL.md：

```bash
bash skills/ai-workflow-init/scripts/init.sh --client all --scope user
ai-workflow doctor --source-root "$PWD/skills" --repo <你的项目> --client all
```

### 3. 在你跑工作流的项目里配置 `.ai-workflow.yaml`

`wecom:` 块加在**项目**的配置文件里（不是 skill 仓库）：

```yaml
repository: your-repo
wecom:
  enabled: true
  webhook_url_env: WECOM_WEBHOOK_URL
  creator_userid_env: WECOM_CREATOR_USERID
  gates: [review, blocked, governance, git_handoff, terminal]
```

### 4. 设置环境变量

```bash
export WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的机器人key
export WECOM_CREATOR_USERID=sunxianshun
```

（推荐写入 `~/.zshenv`，它由 zsh **所有**会话加载——登录、交互、非交互、脚本；或由 `.env` 加载。**不要只写 `~/.zshrc`**：它只在交互式 zsh 加载，GUI 应用、服务或脚本启动的 Agent 会因变量缺失而静默收不到通知。）

### 5. 正常使用，通知自动触发

跑 `$ai-workflow-harness`、`$ai-git-handoff`、`$ai-knowledge-governance` 时，到达 Review Gate / Blocked / governance / git handoff 节点会自动推送，**无需额外操作**。开 run 时指定多个操作者：

```bash
ai-workflow workflow init --repo "$PWD" \
  --source-revision "$(git rev-parse HEAD)" \
  --requirement "实现订单导出模块" \
  --operators "sunxianshun,wangxiaofei"
```

### 已安装用户常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `wecom notify` 命令不存在 | Helper 未更新（命令在 Helper，不在 skill） | 切到 `wecom-notify-gates` 分支 + `pip install -e '.[dev]'` |
| skill 自动调用但没收到微信 | `wecom:` 未配 / `WECOM_WEBHOOK_URL` 未设（如变量只在 `~/.zshrc`，GUI/非交互启动时缺失） | 按第 3、4 步配置，变量写入 `~/.zshenv`；软失败原因会打到 stderr |
| Windows 更新 skill 后仍是旧版 | copy 安装不跟随仓库 | 重跑 `init.sh` |
| `--operators` 没生效 | `WECOM_CREATOR_USERID` 未设置 | 设置后重新 `workflow init` |

## 一、企业微信侧准备

需要企业微信群主/群成员权限，配置一次：

1. 在企业微信里建一个群（或拉一个通知专用群），把需要收到通知的成员拉进来。
2. 群设置 → 群机器人 → 添加机器人 → 复制 **Webhook 地址**。
   - 形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx`
3. 把该地址填入环境变量 `WECOM_WEBHOOK_URL`。

> 你只需要一个群机器人的 **Webhook 地址**：URL 本身自带 key，把机器人拉进通知群即可，全程无需其他企业微信凭据。

## 二、配置 `.ai-workflow.yaml`

在项目根目录 `.ai-workflow.yaml` 添加 `wecom:` 块：

```yaml
repository: your-repo
wecom:
  enabled: true
  webhook_url_env: WECOM_WEBHOOK_URL    # 环境变量名（不是值！）
  creator_userid_env: WECOM_CREATOR_USERID
  gates: [review, blocked, governance, git_handoff, terminal]   # 可只保留部分节点
```

字段说明：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `enabled` | 是 | 是否启用通知（默认 false） |
| `webhook_url_env` | 是 | 群机器人 Webhook URL 的**环境变量名** |
| `creator_userid_env` | 否 | 创建者 userid 的环境变量名（默认 `WECOM_CREATOR_USERID`） |
| `gates` | 否 | 启用通知的节点，默认全部五个 |

## 三、设置环境变量

Webhook 地址只从环境变量读取，`wecom:` 块中存放的是变量名：

```bash
export WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx
export WECOM_CREATOR_USERID=sunxianshun   # 你的企微 userid，init 默认操作者
```

> **环境变量加载位置（重要）**：`~/.zshrc` 只在**交互式** zsh 加载。Codex/Claude Code 若由 GUI 应用、服务或脚本启动，将拿不到只写在 `~/.zshrc` 的变量，通知会静默失败。推荐把上述 export 写入 `~/.zshenv`（zsh 所有会话都加载）。GUI 应用当前会话可执行 `launchctl setenv <变量名> <值>` 立即注入（重启后失效，需重新设置或配合登录项）；修改后需重启 Codex/Claude 应用才生效。

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

`$ai-workflow-harness`、`$ai-git-handoff`、`$ai-knowledge-governance` 三个 skill 已内置：到达 Review Gate / Terminal Completion / governance / git handoff 节点时自动调用通知；**Blocked 由 `workflow block` 命令在 Helper 层机械自动推送**（不依赖 skill 调用）。正常跑工作流即可，无需手动操作。

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

# Terminal Completion（终态验收）
ai-workflow wecom notify --repo "$PWD" --run-id RUN-xxx \
  --gate terminal \
  --action "请验收 run 终态（completed/aborted）"

# 不真发，只看消息内容（调试）
ai-workflow wecom notify --repo "$PWD" --run-id RUN-xxx \
  --gate review --phase plan --action "x" --dry-run
```

命令参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--repo` | 是 | 仓库根目录 |
| `--run-id` | 是 | 目标 run |
| `--gate` | 是 | `review` / `blocked` / `governance` / `git_handoff` / `terminal` |
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

> 注：当前「开启者 / 授权操作者」以纯文本 `@名字` 展示，**不会在企微里真正 @ 到人**。若需真 @ 提醒（`<@userid>` 语法），需扩展 `render_message`。

## 七、行为细节

| 特性 | 行为 |
| --- | --- |
| 幂等去重 | key = `(run_id, gate, phase, 内容摘要)`；同内容不重复推送 |
| `--force` | 跳过去重强制重发 |
| `--dry-run` | 只打印不发送 |
| 软失败 | 网络/API/环境变量缺失 → `{"sent": false, "error": ...}` 且 exit 0，不影响工作流 |
| 未配置时 | `enabled: false`、gate 未启用或无 `webhook_url_env` → no-op，不报错 |
| 记录位置 | `.ai-workflow/notifications/<run_id>.json`（已 gitignore） |
| secret | 只从环境变量读，配置文件里是变量名 |

## 八、当前限制（Plan 2 未做）

- 目前**只能推送，不能在微信里回复处理**。"回复即处理"（accept / resume / promote / commit / MR 二次确认）依赖 `ai-workflow wecom serve` 回调服务，属于 Plan 2，尚未实现。
- 因此人工节点仍需开跑者在**本地终端**处理，微信通知仅作提醒与授权标注。
- 阿里云服务器、回调域名、回调 `Token`/`EncodingAESKey` 当前都用不上。
