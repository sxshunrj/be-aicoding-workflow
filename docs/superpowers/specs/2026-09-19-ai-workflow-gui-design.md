# ai-workflow 桌面 GUI 设计

日期：2026-09-19
状态：待用户评审
范围里程碑：G-MVP（本 spec 覆盖）→ M2 → M3（后两者仅列方向，不在本 spec 实施范围）

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
| `workflow review` / `review-accept` / `block` / `repair-review-gate` | Review 审批屏（核心价值） |
| `workflow resume --rerun` / `abort` / `summary` | Run 详情页操作按钮 |
| `install` / `doctor` | 装机与诊断页（M2） |
| wiki 子命令 | 不在 GUI 范围（YAGNI） |

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
│  │  └─ admin.py                # install / doctor（M2 接线，接口先留）
│  └─ static/                    # 前端构建产物（构建后提交，pip 安装不依赖 Node）
├─ gui/                          # 前端源码（React + Vite + TypeScript，不进 wheel）
└─ pyproject.toml                # 新增 gui extra 与 ai-workflow-gui 入口
```

进程模型：`ai-workflow-gui` 启动 FastAPI → 自动打开浏览器访问 `http://127.0.0.1:<port>`。MVP 即浏览器形态；pywebview 独立窗口壳是 M3，不改变架构。

GUI 自身配置：`~/.ai-workflow-gui/config.json`，记录注册的 repo 路径列表。注册时用 `RepositoryConfig.load(path)` 校验，无 `.ai-workflow.yaml` 的目录拒绝注册。

端口：默认取空闲端口（uvicorn port=0 探测后回填展示），避免固定端口冲突。

## 4. 后端 API 层

原则：每个路由映射一个既有 `WorkflowService` 方法；GUI 不向 `.ai-workflow/` 写任何 service 之外的新文件。

| 路由 | 方法 | 调用目标 | 说明 |
|---|---|---|---|
| `/api/repos` | GET | GUI 配置文件 | 列出已注册 repo |
| `/api/repos` | POST | `RepositoryConfig.load` | 注册 repo，校验失败返回 `config_not_found` 引导 |
| `/api/repos/{id}/runs` | GET | **新增** `runlist.list_runs(repo)` | 枚举 `.ai-workflow/runs/*/state.yaml` → `RunState.from_dict`，按 run_id 倒序。唯一的新逻辑，纯只读 |
| `/api/repos/{id}/runs` | POST | `WorkflowService.init` | body：`requirement`(非空)、`profile`(full/grill)、`source_revision`(非空)。source_revision 由后端预填（subprocess 执行 `git -C <repo> rev-parse HEAD`，失败则前端手填）。 |
| `/api/repos/{id}/runs/{run_id}` | GET | `service.status` | 返回 `RunState.to_dict()` |
| `/api/repos/{id}/runs/{run_id}/review` | POST | `service.review` | `reruns` 可选 |
| `.../review-accept` | POST | `service.record_review_acceptance` | |
| `.../block` | POST | `service.block` | body：`reason`(非空) |
| `.../repair-review-gate` | POST | `service.repair_review_gate` | |
| `.../resume` | POST | `service.resume` | body：`reruns: {node: attempt}` 可选 |
| `.../abort` | POST | `service.abort` | |
| `.../summary` | GET | `service.summary` | `RunSummary.to_dict()` |
| `/api/install`、`/api/doctor` | POST/GET | `install_skills` / doctor 模块 | M2 接线 |

错误处理：FastAPI 全局 exception handler 把 `AppError.code` 映射为 HTTP 状态码（`*_not_found`/`invalid_run_id` → 404，`state_exists`/`immutable_conflict` → 409，`config_*`/`invalid_*` → 400，其余 → 500），响应体统一 `{"code": ..., "message": ...}`。前端 toast 展示。

安全边界：只绑 127.0.0.1；无鉴权（本机自用，与终端 CLI 同一信任级别）。写操作全部经过 `StateStore` 既有的 fcntl 锁，GUI 与终端 agent 可并发操作同一 run。

## 5. 前端设计（MVP 三屏）

技术：React + Vite + TypeScript，无重型 UI 框架依赖偏好（组件库可选轻量级，如不上组件库则手写样式）；状态获取用轮询（5s）+ 操作后立即刷新；SSE 后置到 M2。

1. **Runs 仪表盘**：左侧 repo 列表（含「添加 repo」路径输入）；右侧当前 repo 的 run 列表（run_id、requirement 摘要、current_phase、status、profile）；「发起 run」表单（requirement 多行文本、profile 下拉、source-revision 预填可改）。
2. **Run 详情**：run_graph 四阶段节点图（spec → plan → implement → verify），节点状态五色映射 pending/running/valid/rerun/blocked；artifacts 列表；操作区（resume/abort/summary，按 status 条件显隐）。
3. **Review 审批**：并入 Run 详情页（独立 Tab），不设单独路由。数据源是 `service.status` 返回的 `RunState.artifacts["review_gate"]`：`decision == "human_review"` 且 `accepted_at` 为空即 pending gate，展示 phase、proposed_reruns、digest；按钮：接受（`review-accept`）、驳回（`block` + reason 输入）、修复（`repair-review-gate`）。历史审批记录依赖 events 时间线，放 M2。

路由：`/`（仪表盘）、`/runs/:runId`（详情 + 审批 Tab）。

## 6. 测试策略

- 后端：pytest + FastAPI TestClient，复用现有 `tests/` 的 repo fixture 模式。必测：repo 注册校验、list_runs 枚举与排序、init/status/审批路由 ↔ service 方法映射、AppError → HTTP 映射。service 层本身已有测试，不重复覆盖。
- 前端：MVP 不强制单测（自用优先），以手动验收为准；Vitest 引入与否留 M2 决定。
- 不做 E2E（YAGNI）。

## 7. 里程碑

- **G-MVP（本 spec 的实施范围）**：`ai_workflow_gui` 子包 + repos/runs/review 全部路由 + 三屏前端 + 浏览器自动打开 + 后端测试通过。
- **M2**：install/doctor 装机诊断页、events.jsonl 只读时间线、SSE 实时推送。
- **M3**：pywebview 桌面窗口壳、随 whl 打包分发（`[gui]` extra）、前端单测。

## 8. 明确不做（YAGNI）

- 不驱动任何 agent、不内嵌终端
- 不做模型 API 层
- 不做 wiki 管理界面
- 不做多用户/鉴权/远程访问
- 不改 `ai_workflow` 包的任何现有行为（GUI 只做消费者；唯一例外：pyproject 新增 extra 与 entry point）
