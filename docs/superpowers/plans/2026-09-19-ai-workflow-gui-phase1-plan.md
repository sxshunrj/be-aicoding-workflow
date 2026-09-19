# ai-workflow GUI 第一期实施计划

日期：2026-09-19
依据 spec：`docs/superpowers/specs/2026-09-19-ai-workflow-gui-design.md`（已定稿，1dc9245）
范围：单人本地，五屏 + 全部人类面路由 + 后端测试

任务按依赖排序，编号即实施顺序。每个任务标验收标准；"测试"指 `uv run python -m pytest -q`（注意 uv run 会产生未跟踪 uv.lock，属已知现象，不提交）。

## A. 后端（Python 子包 `src/ai_workflow_gui/`）

### A1 脚手架与依赖
- pyproject 加 `[project.optional-dependencies] gui = ["fastapi>=0.115,<1", "uvicorn>=0.30,<1"]`；`[project.scripts]` 加 `ai-workflow-gui = "ai_workflow_gui.app:main"`。
- 建空包骨架：`app.py`、`config_store.py`、`runlist.py`、`routes/{repos,runs,knowledge,admin}.py`、`static/.gitkeep`。
- 验收：`uv run python -c "import ai_workflow_gui"` 通过；`uv run python -m pytest -q` 不回归。

### A2 GUI 配置存取 `config_store.py`
- `~/.ai-workflow-gui/config.json`：`{"repos": [{"id", "path", "name"}], "reviewer": str}`；读时容错（损坏视为空配置），写时临时文件 + `os.replace` 原子替换；repo id 用 path 的 sha256 前 8 位（稳定、免维护序号）。
- 验收：单元测试覆盖读写、损坏容错、原子性。

### A3 FastAPI 工厂 + 错误映射 `app.py`
- `create_app() -> FastAPI`：挂载四个 router；全局 `AppError` handler（`*_not_found`/`invalid_run_id`→404，`state_exists`/`immutable_conflict`/`stale_review_gate`/`stale_state`→409，`config_*`/`invalid_*`/`repository_required`→400，其余→500，响应体 `{"code","message"}`）；Host 头校验中间件（仅放行 `127.0.0.1:<port>`/`localhost:<port>`，防 DNS rebinding/跨源简单请求）；托管 `static/`，SPA fallback 用自定义 404 handler（非 `/api` 的 GET 一律返回 index.html——StaticFiles(html=True) 不支持 history 路由 fallback）。
- `main()`：uvicorn 绑 127.0.0.1、port=0 探测实际端口，webbrowser 打开 `http://127.0.0.1:<port>`，Ctrl-C 干净退出。
- 验收：TestClient 请求不存在的 run 得 404 JSON；测试用 `create_app()` 不触发浏览器。

### A4 repo 注册路由 `routes/repos.py`
- `GET /api/repos` 列配置；`POST /api/repos {path}`：resolve 后 `RepositoryConfig.load` 校验（失败 400 `config_not_found`），成功则持久化并返回条目；`DELETE /api/repos/{id}` 移除注册（不动磁盘任何东西）。
- `GET /api/repos/{id}` 顺带返回 `_config_data(config)` 等价信息（供第五屏只读展示，免单独路由）。
- 验收：测试覆盖注册成功/无配置拒绝/删除。

### A5 runs 枚举 `runlist.py`
- `list_runs(repo) -> list[dict]`：枚举 `<repo>/.ai-workflow/runs/RUN-*/state.yaml`，逐个 `RunState.from_dict`；单个损坏跳过并记入 `errors` 字段（不整体失败）；按 run_id 倒序。无 runs 目录返回空列表。
- 验收：测试覆盖正常枚举、损坏隔离、空目录。

### A6 run 生命周期与审批路由 `routes/runs.py`
- `GET /api/repos/{id}/runs` → `list_runs`。
- `GET /api/repos/{id}/head` → `git -C <repo> rev-parse HEAD`（非 git 目录返回 `{"head": null}`，前端表单据此提示手填）。
- `POST /api/repos/{id}/runs` `{requirement, profile, source_revision?}` → `WorkflowService(repo).init`；source_revision 缺省时后端同样执行 rev-parse HEAD 填充，无 HEAD 且未传 → 400 `invalid_source_revision`。
- `GET /api/repos/{id}/runs/{run_id}` → `status().to_dict()`。
- `POST .../review-accept` `{expected_digest}` → `record_review_acceptance`。
- `POST .../block` `{reason}`（非空）→ `block`。
- `POST .../repair-review-gate` → `repair_review_gate`。
- `POST .../resume` `{reruns?: {node: reason}}` → `resume`（reason 非空校验，复用 CLI `_reruns` 语义）。
- `POST .../abort` → `abort`；`GET .../summary` → `summary().to_dict()`。
- `GET .../events?limit=50` → 只读读 `events.jsonl` 尾部（StateStore events_path，存在性检查，逐行 json.loads，损坏行跳过）。行格式（store._serialize_event）：`{"type","version","data","timestamp"?}`，version 可用于展示顺序。
- 验收：用 `examples/language-neutral` 复制的临时 repo fixture 走通 init→status；审批三动作的参数与错误码各有断言（含 stale digest→409）。

### A7 知识治理路由 `routes/knowledge.py`
- wiki 路径取 `RepositoryConfig(repo).wiki_path`。
- `GET .../wiki/candidates` → `WikiRepository(wiki).list("candidate")` 序列化。注意 `KnowledgeEntry` 无现成 to_dict，手写字段映射（id/title/type/status/summary/scope/tags，`path` 取 `candidates/<id>.md`，`digest` 用 `repository.path_digest(path)`）。
- `GET .../wiki/candidates/{cid}/review` → `WikiService.review_candidate(cid, max_related)`。
- `POST .../wiki/candidates/{cid}/promote` `{expected_digest}` + `POST .../reject`/`.../archive` `{reason?, expected_digest}` → 对应方法，`reviewer` 取 GUI 配置。
- 验收：临时 wiki fixture（复制 examples 或 tests 现有 wiki fixture 模式）走 propose→list→review→promote 断言 digest 守卫生效（错 digest→409）。

### A8 装机诊断路由 `routes/admin.py`
- `GET /api/doctor?repo=<id>&client=all` → `run_doctor(source_root, home, repo, clients)` 的 `to_dict()`；source_root 定位顺序：GUI 配置里的 ai-workflow 仓库路径（若注册过本仓库）→ `Path(ai_workflow.__file__)` 向上找 `skills/`（editable 安装成立）→ 400 提示在前端手填。
- `POST /api/install {client, scope, mode, repo?}` → `install_skills` 同样定位 source_root；返回报告，failed 非空时响应仍 200，failed 细节在前端渲染。
- 验收：isolated HOME（tmp_path）下 install→doctor 全绿；无 skills 源时 400。

### A9 后端测试收口
- 汇总跑 `uv run python -m pytest -q`；新增测试放 `tests/gui/`（TestClient + tmp fixture，不起端口）。
- 验收：全绿，无网络依赖，无对用户 HOME 的真实写入（全部 tmp_path/isolated HOME）。

## B. 前端（`gui/`，React + Vite + TS）

### B1 脚手架
- Vite react-ts 模板；`npm run build` 输出配置到 `src/ai_workflow_gui/static/`（vite.config `build.outDir`，`emptyOutDir: true`）；路由用 react-router；不引重型组件库，手写样式（延续 mockup 的状态色系统）。
- 验收：build 产物被 FastAPI 成功托管（curl / 返回 index.html）。

### B2 API 客户端与基础设施
- `api.ts`（fetch 封装，统一解 `{"ok","data"|"error"}` 信封，错误抛带 code 的异常）；toast 组件；`usePolling(url, 5000)` hook（页面隐藏时暂停）；全局错误边界。
- 验收：手动冒烟——错误请求弹 toast、轮询可停。

### B3 应用壳
- 侧边栏（repo 列表 + 添加/删除 + 当前选中态；导航：Runs / 知识治理 / 装机与诊断）；设置区（reviewer 名编辑）；路由 `/`、`/runs/:runId`、`/knowledge`、`/diagnostics`。
- 验收：空配置时显示引导（先添加仓库）。

### B4 屏一：Runs 仪表盘
- run 表格（run_id/requirement 摘要/current_phase/status/创建时间/profile）；筛选 chips 按状态词汇表（进行中={pending,running}、待审批={status=="blocked"}、已完成={completed}、已中止={aborted}）；待审批行高亮置顶；行点击进详情；「发起 Run」弹层表单（requirement 多行、profile 下拉 full|grill、source-revision 预填自 `GET /api/repos/{id}/head`，null 时提示手填）。
- 验收：对 examples/language-neutral 真 repo 手动走通：发起→列表出现新 run。

### B5 屏二：Run 详情（概览）
- meta 条（自动刷新指示/profile/source/创建时间/摘要/中止按钮 + run 级状态 badge：pending/running/blocked/completed/aborted）；**阶段进度区按 run_graph 动态渲染**：把 run_graph 的 key 按 phase 前缀分组，full=4 张阶段卡、grill=3 张（无 spec），每卡内列节点（child 名 + validity 三态色 pending/valid/rerun + reason），当前阶段高亮——禁止硬编码四阶段五色（终审修正：节点无 running/blocked 态）；阶段产物可读卡片（artifacts 键→友好名映射：spec/plan/implement/verify 产物 + review_gate/run_policy）；事件时间线折叠区（events 接口，类型着色，最新在上）。
- 验收：对一个 fake_agent 推进的 run 手动核对节点状态与 events 一致。

### B6 屏二 Tab：审批
- gate 卡（decision/phase/proposed_reruns/state_version/digest/proposed_at）+ 本阶段产出摘要（由 status 的 artifacts 生成：当阶段 aggregate/staged 计数与 summary 若有）；接受（expected_digest 自动带入）、驳回（点击展开 reason 必填）、修复三个按钮；无 pending gate 时显示"无待审批"。
- 验收：手动构造 human review_mode 的 gate 走接受/驳回两路。

### B7 屏三：知识治理
- 候选列表（侧栏 badge 显示数量）→ 详情页（内容 + 相关已批准条目 + 元数据）→ 治理操作（promote / reject(reason 必填) / archive），操作前用当前 digest 做乐观锁；reviewer 显示为设置中的名字。
- 验收：用测试 wiki fixture 手动走 propose→promote 全程。

### B8 屏四：装机与诊断
- 三 Tab：Doctor（分组渲染检查项，failed 红）；Install（client/scope/mode 表单 + 四态报告）；Repo 配置（`GET /api/repos/{id}` 的只读键值表，wiki_path/commands/protected_paths/adapter 等）。
- 验收：真实环境 doctor 全绿；isolated 场景能渲染 failed 项。

## C. 集成与收尾

### C1 入口联调
- `ai-workflow-gui` 从终端启动 → 浏览器自动开 → 五屏可达；Ctrl-C 无残留进程。
### C2 文档
- README 增补：`pip install -e '.[gui]'` + `ai-workflow-gui` 两行用法 + 五屏截图位（截图可后补）。
### C3 第一期验收
- 后端测试全绿；五屏手动走查表（发起 run→审批→治理→诊断）逐项通过；spec 第 8 节"明确不做"无违反。

## 风险与对策
- **install 的 source_root 定位**在非 editable 安装下无 skills 源 → 已在设计上允许前端手填（A8 的 400 分支），UI 文案说明。
- **events.jsonl 格式演进** → 解析层容错（未知 type 原样展示，损坏行跳过）。
- **前端构建产物入库**导致 diff 噪音 → `.gitignore` 不忽略 `static/`（pip 用户无 Node），提交时机固定在 B8 后一次性提交。
