# dsh-tool-aicoding-workflow

DSH (DeepSeek Harness) 工具插件：把 [ai-coding-workflow](../../README.md) 的 Python helper CLI 暴露成模型可调用的、带 schema 校验的工具。

## 为什么需要它

Codex/Claude Code 模式下，主 Agent 靠读 242 行 `helper-cli.md` 再拼命令行来驱动 helper。这有三类代价：

1. **参数靠记忆**：拼错 flag 得到 `invalid_arguments`，白跑一轮；
2. **无跨客户端分发**：`install.py` 只认 `codex` / `claude` 两个目标目录；
3. **错误处理靠 prose**：`error.code` 路由规则写在 SKILL.md 里，没有机械保证。

工具插件用 **schema 校验的 tool call** 取代"读文档拼命令"，并把 helper 的 JSON envelope 原样返回，让模型继续按 `error.code` 路由。

## 暴露面：窄，是刻意的

helper 有 16 个 `workflow` 子命令。本插件默认只暴露**编排与检视层**：

| 工具 | helper 命令 | 语义 |
|---|---|---|
| `aiworkflow_status` | `workflow status` | 唯一恢复入口，纯读 |
| `aiworkflow_summary` | `workflow summary` | 终态摘要，纯读 |
| `aiworkflow_start` | `workflow init` | 建 run + 不可变 policy |
| `aiworkflow_review` | `workflow review` | 推导 review gate（`NODE=REASON`） |
| `aiworkflow_approve` | `workflow review-accept` | **人工**接受 gate，必须带 digest |
| `aiworkflow_block` | `workflow block` | 阻塞并留证据 |
| `aiworkflow_resume` | `workflow resume` | 解除阻塞，可带 rerun |
| `aiworkflow_abort` | `workflow abort` | 终止 |
| `aiworkflow_reflect` | `workflow reflect` | 终态反思 packet |
| `aiworkflow_wiki_search` | `wiki search` | 只搜已批准知识 |
| `aiworkflow_doctor` | `doctor` | 环境诊断 |

**不暴露** `begin` / `stage` / `stage-owned` / `finalize` / `transition`。

理由：helper 能校验产物的**形状**（归属、路径授权、digest），但**无法判断是谁写的**。把这四个原语交给模型，就等于重新打开"Harnes 自己写 child 结果"的口子——而这条正是 SKILL.md 里只能用 prose 禁止的事。它们必须由代码化的 orchestrator 独占。

需要保留 Codex 式手动模式的部署，可显式打开 `exposeRunControl: true`（默认关闭）。

## 挂载

```yaml
# profile 的插件配置层
- name: dsh-tool-aicoding-workflow
  cli: ['/abs/path/to/be-aicoding-workflow/.venv/bin/ai-workflow']
  timeoutMs: 120000
  exposeRunControl: false
```

`cli` 是启动 helper 的 argv 前缀。DSH 进程的 PATH 里通常没有 `.venv/bin`，**建议写绝对路径**；`cli` 为空或不可执行时，工具会返回 `helper_not_found` / `helper_not_configured`，而不是静默失败。

安装插件：

```bash
dsh plugin --profile <name> add ./integrations/dsh-tool-aicoding-workflow   # 转发给 profile 目录里的 pnpm
```

### 依赖版本必须与宿主一致

`peerDependencies` 锁在**宿主随包发布的版本**上（`@deepseek-ai/dsh-tools@0.2.0-rc.2`、`@deepseek-ai/cordis@^4.0.4`、`@deepseek-ai/schemastery@~3.18.4`）。

⚠️ npm 公开的 `@deepseek-ai/dsh-tools` 版本（实测为 `0.0.1-rc.1`）**落后于** DSH 应用内置的 `0.2.0-rc.2`。本地只做类型检查时可以用 npm 版本，但**实际挂载必须以宿主内置版本为准**，否则 `defineTool` 的选项可能不匹配。

## 设计要点

- **envelope 原样透传**：工具返回值就是 helper 的 `{ok, data, error}`，不重新包装、不翻译 message。模型按 `error.code` 路由，与 SKILL.md 的 error posture 一致。
- **transport 兜底**：helper 的 `main()` 只捕获 `AppError`，遇到非 `AppError` 会打印 traceback。插件把"stdout 不是 envelope"归类为 `helper_transport_error`（附 stderr 尾部），在工具边界上保住 envelope 契约。
- **客户端预校验**：`--rerun` 的 `NODE=REASON` 形状、重复 node 在前置校验里就报错（helper 仍会再校验一次，纵深防御）。
- **并发标注**：只读工具标记 `isConcurrencySafe`，可加入并行组；写工具不标记。

## 已知缺口（骨架阶段）

1. **没有 orchestrator**：默认面不包含 run control，所以目前没有代码在驱动 `begin → stage → finalize → transition`。插件解决的是"接口与权限"，不是"控制流"。
2. **未编译验证**：本目录尚无 `node_modules`；类型检查需要 `pnpm install` 拉取与宿主同版本的 `@deepseek-ai/*` 类型。
3. **`stage_owned` 未暴露**：grill profile 的 `plan.prd` 需要它；加入前要先决定它属于编排面还是 run-control 面。

## 验证

```bash
cd integrations/dsh-tool-aicoding-workflow
pnpm install
pnpm typecheck
```
