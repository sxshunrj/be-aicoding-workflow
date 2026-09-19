# ai-workflow 桌面 GUI 设计

日期：2026-09-19
状态：已定稿（2026-09-19 用户确认：第一期仅单人本地；多人管理经讨论后明确搁置，不进任何一期）
范围里程碑：第一期（本 spec 覆盖，含本项目全部人类面功能）→ 第二期（扩展：桌面壳、分发、SSE）

## 1. 背景与产品定义

给 be-aicoding-workflow 做一个桌面 GUI，**严格围绕本仓库现有源码与功能面**，不引入新的 agent 引擎，不包装 zcode/codex 等 CLI 产品。

经澄清确认的边界：

- agent（在终端里跑 skills 写代码的角色）仍由用户在自己的终端运行，GUI 不介入、不驱动。
- GUI 的职责：发起 run → 监控状态 → 审批 review gate。
- 不做模型层（ai-workflow 本身不调用 LLM API）。
- 首批用户：作者本人，macOS 优先；后续随 whl 分发给团队（衔接既有 `pip install` 分发方案）。

GUI 的功能面 = CLI 已暴露的人类操作面：

| CLI 功能 | GUI 呈现 |
|---|---|
| `workflow init` | 发起 run 表单（repo、requirement、profile、source-revision） |
| `workflow status` | run 列表与 run 详情 |
| `workflow review-accept` / `block` / `repair-review-gate` | Review 审批屏（核心价值；`workflow review` 是 agent 侧命令，GUI 不调用） |
| `wiki review` / `promote` / `reject` / `archive` | 知识治理屏（第四屏；全功能审计后从"不做"改为第一期范围，见第 9 节） |
| `workflow resume --rerun` / `abort` / `summary` | Run 详情页操作按钮 |
| `install` / `doctor` | 装机与诊断页（第一期） |
| `wiki lint` | 诊断页 wiki 健康检查（第一期） |
| `config show` | repo 配置只读展示（第一期） |

Agent 专用命令（`begin` / `stage` / `stage-owned` / `finalize` / `transition` / `review` / `reflect` / `reflect-submit` / `wiki search` / `wiki packet` / `wiki propose` / `config authorize-path`）不由 GUI 暴露，理由见第 8 节。

## 2. 技术路线（已选定：方案 A）

**同仓 Python 子包 GUI：FastAPI + React + Vite。**

后端直接 in-process import `ai_workflow` 的公开函数与类（`WorkflowService`、`install_skills`、`RepositoryConfig`、`RunState` 等），不走 subprocess、不解析 CLI 文本输出。理由：

1. `WorkflowService` 全部方法返回带 `to_dict()` 的数据类，`AppError(code, message)` 是统一错误类型——JSON API 层近乎零转换。
2. 与既有 whl 分发方案闭环：`pip install ai-coding-workflow[gui]` 后 `ai-workflow-gui` 即可用。
3. 与仓库同语言（Python），单人可维护性最高。

被否决的备选：

- **B：Electron + TS，subprocess 调 CLI**——桌面质感最好，但双语言、双仓库割裂、迭代慢，且与"围绕本项目源码"隔了一层进程边界。
- **C：Tauri 2 + Python sidecar**——轻量质感好，但 Rust 工具链 + sidecar 打包调试对单人项目摩擦过大。

## 3. 总体架构

```
<repo>/                          # be-aicoding-workflow 仓库
├─ src/ai_workflow_gui/          # 新增 Python 子包
│  ├─ app.py                     # FastAPI 工厂 + main() 入口（uvicorn，绑 127.0.0.1）
│  ├─ runlist.py                 # 新增只读能力：枚举 runs
│  ├─ routes/
│  │  ├─ repos.py                # repo 注册与列表
│  │  ├─ runs.py                 # run 生命周期 + 审批
│  │  ├─ knowledge.py            # wiki 候选治理（第四屏）
│  │  └─ admin.py                # install / doctor / config 只读（第五屏）
│  └─ static/                    # 前端构建产物（构建后提交，pip 安装不依赖 Node）
├─ gui/                          # 前端源码（React + Vite + TypeScript，不进 wheel）
└─ pyproject.toml                # 新增 gui extra 与 ai-workflow-gui 入口
```

进程模型：`ai-workflow-gui` 启动 FastAPI → 自动打开浏览器访问 `http://127.0.0.1:<port>`。第一期即浏览器形态；pywebview 独立窗口壳在第二期，不改变架构。

GUI 自身配置：`~/.ai-workflow-gui/config.json`，记录注册的 repo 路径列表和审批人名 `reviewer`（知识治理的 promote/reject/archive 需要）。注册 repo 时用 `RepositoryConfig.load(path)` 校验，无 `.ai-workflow.yaml` 的目录拒绝注册。

端口：默认取空闲端口（uvicorn port=0 探测后回填展示），避免固定端口冲突。

## 4. 后端 API 层

原则：每个路由映射一个既有 `WorkflowService` 方法；GUI 不向 `.ai-workflow/` 写任何 service 之外的新文件。

| 路由 | 方法 | 调用目标 | 说明 |
|---|---|---|---|
| `/api/repos` | GET | GUI 配置文件 | 列出已注册 repo |
| `/api/repos` | POST | `RepositoryConfig.load` | 注册 repo，校验失败返回 `config_not_found` 引导 |
| `/api/repos/{id}/runs` | GET | **新增** `runlist.list_runs(repo)` | 枚举 `.ai-workflow/runs/*/state.yaml` → `RunState.from_dict`，按 run_id 倒序。唯一的新逻辑，纯只读 |
| `/api/repos/{id}/runs` | POST | `WorkflowService.init` | body：`requirement`(非空)、`profile`(full/grill)、`source_revision`(非空)。source_revision 由后端预填（subprocess 执行 `git -C <repo> rev-parse HEAD`，失败则前端手填）。 |
| `/api/repos/{id}/runs/{run_id}` | GET | `service.status` | 返回 `RunState.to_dict()`；审批 Tab 数据源即其中 `artifacts["review_gate"]` |
| `.../review-accept` | POST | `service.record_review_acceptance` | body：`expected_digest`（取自 gate 卡片，digest 乐观锁） |
| `.../block` | POST | `service.block` | body：`reason`(非空) |
| `.../repair-review-gate` | POST | `service.repair_review_gate` | |
| `.../resume` | POST | `service.resume` | body：`reruns: {node: reason}`（对应 CLI `NODE=REASON`，reason 必填） |
| `.../abort` | POST | `service.abort` | |
| `.../summary` | GET | `service.summary` | `RunSummary.to_dict()` |
| `/api/repos/{id}/wiki/candidates` | GET | `WikiRepository.list("candidate")` | 候选知识列表，既有方法，只读 |
| `.../wiki/candidates/{id}/review` | GET | `WikiService.review_candidate` | 候选详情 + 相关已批准条目 |
| `.../wiki/candidates/{id}/promote` | POST | `service.promote` | body：`reviewer`(GUI 配置)、`expected_digest` |
| `.../wiki/candidates/{id}/reject`、`/archive` | POST | `service.reject` / `service.archive` | body：`reviewer`、`reason`、`expected_digest` |
| `.../runs/{run_id}/events` | GET | 只读读 `events.jsonl` 尾部 | run 事件时间线数据源，纯只读 |
| `/api/repos/{id}/config` | GET | `RepositoryConfig.load` | `config show` 等价，只读展示 |
| `/api/install` | POST | `install_skills` | body：`client`、`scope`、`mode`、`repo`（repo scope 时）；`source_root` 取当前安装来源的 skills 目录 |
| `/api/doctor` | GET | `run_doctor` | query：`repo`、`client`；返回全部检查项与 failed 明细 |
| `/api/agent-config` | GET/PUT | GUI 配置 | agent 命令模板（必须含 `{prompt}`） |
| `.../runs/{run_id}/drive` | POST/GET/DELETE | **新增** AgentDriver | 启动/状态+控制台尾迹/终止 agent 子进程 |

GUI 不提供 `workflow review`（agent 阶段结束时调用以生成 decision；审批屏只消费 `status` 里的 gate）。

错误处理：FastAPI 全局 exception handler 把 `AppError.code` 映射为 HTTP 状态码（`*_not_found`/`invalid_run_id` → 404，`state_exists`/`immutable_conflict`/`stale_review_gate`/`stale_state` → 409，`config_*`/`invalid_*`/`repository_required` → 400，其余 → 500），响应体统一 `{"code": ..., "message": ...}`。前端 toast 展示；`stale_state`（GUI 与终端 agent 并发写导致版本过期）前端行为 = 静默刷新数据后让用户重试。

安全边界：只绑 127.0.0.1；无鉴权（本机自用，与终端 CLI 同一信任级别）；加 Host 头校验中间件（仅放行 `127.0.0.1:<port>`/`localhost:<port>`，防 DNS rebinding 与浏览器跨源简单请求）。写操作全部经过 `StateStore` 既有的 fcntl 锁，GUI 与终端 agent 可并发操作同一 run。

状态词汇表（源码核实，2026-09-19 终审）：**run 级状态** `RunState.status ∈ {pending, running, blocked, completed, aborted}`，终态 `{completed, aborted}`（`machine.TERMINAL_STATUSES`）；`blocked` = 等待人工（review gate 生成或手动 block 置位）。**节点级状态** `RunGraphNode.validity ∈ {pending, valid, rerun}` 三态（没有 running/blocked）。**图结构随 profile 变化**：full = 8 节点 4 阶段（spec×1、plan×2、implement×1、verify×4），grill = 7 节点 3 阶段（plan.prd 起步、无 spec）。

## 5. 前端设计（第一期五屏）

技术：React + Vite + TypeScript，无重型 UI 框架依赖偏好（组件库可选轻量级，如不上组件库则手写样式）；状态获取用轮询（5s）+ 操作后立即刷新；SSE 后置。优化稿（v2 mockup）确认的五处体验改进一并纳入：筛选 chips 与待审批高亮、创建时间列（从 run_id 解析）、阶段产物可读卡片、"N 秒前自动刷新"指示、驳回理由点击展开。

1. **Runs 仪表盘**：左侧 repo 列表（含「添加 repo」路径输入）；右侧当前 repo 的 run 列表（run_id、requirement 摘要、current_phase、status、创建时间、profile），筛选 chips 按状态词汇表定义（进行中={pending,running}、待处理={blocked}、已完成={completed}、已中止={aborted}），待处理行高亮置顶（`blocked` 有两个来源：pending review gate 或手动 block，详情页内区分——有 pending gate 引导到审批 Tab，无 gate 引导到 resume）；「发起 run」表单（requirement 多行文本、profile 下拉、source-revision 预填自 `GET /api/repos/{id}/head` 可改）。首次启动显示空状态引导（添加仓库 → 校验 `.ai-workflow.yaml`）。
2. **Run 详情**：顶部 meta 条（自动刷新指示、profile、source、创建时间、摘要/中止操作、run 级状态 badge）；**阶段进度区按 run_graph 动态渲染**——full 渲染 4 张阶段卡（spec→plan→implement→verify）、grill 渲染 3 张（无 spec），每张阶段卡内列出该阶段的节点（child 名 + validity 三态色 pending/valid/rerun + rerun reason），当前阶段高亮；阶段产物可读卡片（友好名称 + 查看入口，映射自 artifacts，不做原始路径罗列）；事件时间线折叠区（`events.jsonl` 只读尾部，行格式 `{"type","version","data","timestamp"?}`，按类型着色）。
3. **Review 审批**：并入 Run 详情页（独立 Tab），不设单独路由。数据源是 `service.status` 返回的 `RunState.artifacts["review_gate"]`：`decision == "human_review"` 且 `accepted_at` 为空即 pending gate，展示 phase、proposed_reruns、digest；卡片内置"本阶段产出摘要"（只读解析 artifacts 生成，审批人先知道批的是什么）；按钮：接受（`review-accept`）、驳回（`block`，点击后展开 reason 输入）、修复（`repair-review-gate`）。
4. **知识治理**：候选知识列表（`WikiRepository.list("candidate")`）→ 候选详情（`review_candidate` 返回条目内容 + 相关已批准条目对照）→ 治理操作：批准（promote）/ 驳回（reject，reason 必填）/ 归档（archive），均带 `reviewer`（GUI 设置中的审批人名）与 `expected_digest` 乐观锁。侧边导航入口与 Runs 平级。
5. **装机与诊断**：诊断页对选中 repo 运行 `doctor`，分组展示检查项（skill 安装、CLI、repo config、wiki lint），failed 项红色明细；装机页运行 `install`（client/scope/mode 选择，repo scope 时选 repo），渲染 installed/updated/skipped/failed 报告；`config show` 以只读表单展示 repo 配置（含 protected_paths、adapter 路径、commands）。

路由：`/`（仪表盘）、`/runs/:runId`（详情 + 审批 Tab）、`/knowledge`（知识治理）、`/diagnostics`（装机与诊断）。

## 6. 测试策略

- 后端：pytest + FastAPI TestClient，复用现有 `tests/` 的 repo fixture 模式。必测：repo 注册校验、list_runs 枚举与排序、init/status/审批路由 ↔ service 方法映射、知识治理路由（候选列表/详情/promote/reject/archive 的参数与 AppError 映射）、events 只读解析、install/doctor/config 路由、AppError → HTTP 映射。service 层本身已有测试，不重复覆盖。
- 前端：第一期不强制单测（自用优先），以手动验收为准；Vitest 引入与否留第二期决定。
- 不做 E2E（YAGNI）。

## 7. 里程碑

按"第一期做本项目全部功能，之后再扩展别的功能"切分（2026-09-19 用户确认）：

- **第一期（本 spec 的实施范围）**：本项目全部人类面功能——五屏前端（仪表盘 / Run 详情+审批 / 知识治理 / 装机与诊断）+ 全部对应路由（含 install / doctor / config show / events 只读）+ 浏览器自动打开 + 后端测试通过。
- **第二期（扩展，均为项目外能力或呈现优化）**：pywebview 桌面窗口壳、随 whl 打包分发（`[gui]` extra）、SSE 实时推送、前端单测。

## 8. 明确不做（YAGNI）

- ~~不驱动任何 agent~~ → **2026-09-19 用户决定跨过该边界**：GUI 以无人值守 headless 模式驱动配置的 agent CLI（命令模板可配，默认 `claude -p {prompt} --dangerously-skip-permissions`），一次驱动推进到终态或审批 gate。v1 为子进程监督 + 控制台尾迹，不内嵌交互终端、不实现自有 agent 循环。护栏：终态/运行中/待审批 gate 拒绝启动
- 不做模型 API 层
- 不做多用户/鉴权/远程访问
- 不改 `ai_workflow` 包的任何现有行为（GUI 只做消费者；唯一例外：pyproject 新增 extra 与 entry point）
- 不暴露 agent 专用命令：`workflow begin` / `stage` / `stage-owned` / `finalize` / `transition` / `review` / `reflect` / `reflect-submit`、`wiki search` / `packet` / `propose`、`config authorize-path`——这些由 skills 在终端会话中由 agent 调用，GUI 化它们等于重做 agent 控制回路，违背"agent 留在终端"的产品边界
- 不做 wiki 知识内容的编辑/撰写界面（GUI 只做候选治理：查看与 promote/reject/archive）

## 9. 全功能审计记录（2026-09-19）

对照 `cli.py` 全部子命令、`docs/mvp-traceability.md`、Wave 1/2 追溯文档逐一核对后的归类结论：

- **审计修正 1**：知识治理（`wiki review/promote/reject/archive` + 候选枚举）原 spec 误标为 YAGNI。它是 MVP 验收标准第 5、6 条（"完成 run 产出候选知识，人类批准后可被检索"）和 Wave 1 governance 证据链的一半，且全部操作是人类面——已改为 MVP 第四屏。
- **审计修正 2**：`review-accept` 需要 `expected-digest`（digest 乐观锁），原 API 表漏写；`resume --rerun` 实为 `NODE=REASON`（reason 必填），原表误写为 attempt。
- **审计修正 3**：`workflow review` 是 agent 侧命令（生成 decision），GUI 原表误列为自己的路由，已移除；审批屏只消费 `status` 的 gate。
- **审计修正 4**（范围确认后）：按用户决定"第一期做本项目全部功能"，原 M2 中的人类面功能（install/doctor 诊断页、`wiki lint`、`config show` 展示、events 时间线）全部并入第一期；第二期只留项目外能力与呈现优化（桌面壳、whl 分发、SSE、前端单测）。
- 其余归类（经审计修正 4 调整后）：agent 专用命令不暴露（第 8 节）；`src/ai_workflow/wecom/` 在 main 上为空目录（分支功能），不涉及；11 个 skills 均为 agent 面资产，由第一期的 install/doctor 覆盖安装诊断。
- GUI 的新增逻辑仍然只有两个只读枚举：`list_runs`（枚举 `.ai-workflow/runs/*/state.yaml`）与候选列表（复用现成 `WikiRepository.list`）。
