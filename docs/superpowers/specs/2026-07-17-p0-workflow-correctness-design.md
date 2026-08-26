# P0 工作流正确性与 Checkpoint 设计

**日期：** 2026-07-17

**状态：** 已实现并通过本地自动化验证

**范围：** Profile-aware Grill 执行、节点级恢复、不可变本地 Git checkpoint、仓库配置版本管理和路径授权

## 1. 背景与目的

当前仓库已经具备确定性的四阶段工作流 Core、不可变证据、节点级 rerun 状态和人工 Review Gate。现阶段最高优先级的问题不是增加更多产品入口，而是补齐以下正确性缺口：

- `grill` profile 虽然被持久化，但不会改变 run graph 或起始 phase；
- verification 尚未锚定到不可变的 implementation 代码快照；
- 仓库配置声明了 schema version，但加载时没有校验；
- protected path 只按顶层名称匹配，导致 `.git/**` 无法排除 `.git`；
- Wave 2 conformance 目前只证明 Skill 可安装和文档存在，没有证明真实三阶段生命周期。

本设计在不向通用 Core 写入业务领域、Java、内部 CI 或内部协作平台特定逻辑的前提下，关闭上述缺口。

## 2. 目标

1. 让 `workflow init --profile full|grill` 选择并持久化对应的 graph 和起始 phase。
2. 让故障恢复从最早受影响节点开始，而不是重新启动整个 run。
3. implementation 结果通过 Review Gate 后创建不可变的本地 Git checkpoint，同时不移动 `HEAD`、不更新业务分支、不修改用户 index、不 push。
4. 要求所有 verification dispatch 和结果都锚定到 active checkpoint。
5. 校验仓库配置 schema version，并提供从 v1 或缺少版本声明迁移到 v2 的显式命令。
6. 在 dispatch authorization 中机械执行 protected path 和 adapter path 规则。
7. 通过 unit、contract 和 end-to-end tests 证明上述行为。

## 3. 非目标

- 本批次不增加 CI provider、whitebox、Java、Maven 或内部协作平台遥测实现。
- 不修改用户可见的业务分支，也不 push checkpoint ref。
- checkpoint tree 不包含 `.ai-workflow`、workflow artifact、报告、日志、Git 元数据或无关的预存改动。
- state、schema 或 checkpoint 损坏后，不静默创建新 run 或从头重跑。
- 不整体重构 `WorkflowService`，只抽离新增的 checkpoint 职责。
- 在真实 Codex 和 Claude Code trial evidence 完成前，不声明 real-client reference parity。

## 4. Profile-aware Run Graph

只支持 `full` 和 `grill` 两种 profile。未知 profile 返回 `invalid_profile`。

### 4.1 Full profile

`full` profile 保持当前生命周期和 graph：

```text
spec.spec
-> plan.solution + plan.test_strategy
-> implement.code
-> verify.build + verify.unit_test + verify.integration_test + verify.code_review
```

起始 phase 为 `spec`。

### 4.2 Grill profile

`grill` profile 使用以下 graph：

```text
plan.prd
-> implement.code
-> verify.build + verify.unit_test + verify.integration_test + verify.code_review
```

起始 phase 为 `plan`。`plan.prd` 由 workflow 主 Agent 拥有：主 Agent 一次询问一个问题并产出 PRD，Helper 仍然是持久化 run evidence 的唯一写入者。

`workflow begin` 为 `plan.prd` 返回 `execution_kind=workflow_owned` 以及允许的 artifact 目标位置。Agent 在 `.ai-workflow/runs/**` 外部写入临时 PRD，然后调用以下命令导入：

```text
ai-workflow workflow stage-owned --repo REPO --run-id RUN --attempt-id ATTEMPT --phase plan --child prd --artifact FILE --summary TEXT
```

Helper 校验 artifact、不可变地复制文件、创建 staged result，并继续使用现有的 finalize/review/transition 协议。Agent 不直接修改 run state，也不自行构造 ChildResult。

PRD contract 必须包含稳定的 `ISSUE-001` 标识、tracer-bullet 纵向切片、acceptance criteria、non-goals、repository scope、verification commands，以及已经解决或明确构成阻塞的 open questions。

### 4.3 持久化事实

effective graph 和 initial phase 在创建 run 时写入持久化状态。恢复 run 或在新会话中继续时，只读取持久化状态，不根据当前配置或聊天记录重新构造现有 run。

## 5. 节点级恢复与失效传播

每个 rerun reason 必须归属具体 graph node。状态机移动到最早受影响的 phase，并遵循以下规则：

- 未受影响的上游节点保持 `valid`；
- 被请求重跑的节点置为 `rerun`，并携带非空、可执行的 reason；
- 更晚 phase 的节点全部置为 `pending`；
- 同 phase 内未受影响的 sibling，在输入锚点未变化时继续复用；
- 环境、权限或工具失败进入 `blocked`，不伪装成业务 rerun。

示例：

| 问题 | 恢复行为 |
| --- | --- |
| Integration-test case 自身有缺陷 | 只重跑 `verify.integration_test`；checkpoint 未变化时复用其他 verification sibling。 |
| Verification 发现 implementation 缺陷 | 重跑 `implement.code`；保留 spec/plan；创建新 checkpoint；使旧 checkpoint 对应的全部 verification 结果失效。 |
| PRD acceptance criteria 变化 | 重跑 `plan.prd`；使 implementation 和 verification 失效。 |
| Full profile 的 spec 变化 | 重跑 `spec.spec`；使全部下游节点失效。 |
| 环境失败 | 持久化为 `blocked`；人工 resume 后从受影响节点继续。 |
| State 损坏或 schema 不兼容 | 持久化或报告 fail-closed blocker；不静默创建替代 run。 |

## 6. 不可变本地 Git Checkpoint

### 6.1 组件边界

Checkpoint 机制放入独立的 `workflow/checkpoint.py` service。`WorkflowService` 只协调生命周期调用，不直接实现 Git plumbing。

Checkpoint service 输入：

- repository root；
- run 和 implementation attempt identity；
- source revision；
- implementation attempt baseline；
- protected paths 和 effective checkpoint scope。

输出 checkpoint record：

- checkpoint commit SHA；
- tree SHA；
- hidden ref name；
- source revision 和 parent commit；
- implementation attempt ID；
- included paths；
- previous checkpoint SHA（如存在）；
- creation timestamp。

### 6.2 Git plumbing

Implementation Review Gate 被接受后，Helper 执行：

1. 验证 `HEAD` 和业务分支没有发生非预期移动；
2. 计算本次 implementation attempt 的变更集合；
3. implementation rerun 时选择 active checkpoint 作为 base anchor，首次 implementation 使用 source revision；
4. 在用户 index 之外创建临时 Git index；
5. 从 base anchor 填充临时 index，只 stage 获得授权的 checkpoint paths；
6. 执行 `git write-tree`；
7. 执行 `git commit-tree`，并以 base anchor 为 parent；
8. 将 commit 写入 `refs/ai-workflow/checkpoints/<run_id>/<attempt_id>`；
9. 在 workflow state 中激活 checkpoint record。

该过程只写入本地 Git object 和带命名空间的 hidden ref。禁止执行普通 `git commit`、移动 `HEAD`、更新当前分支、修改 `.git/index` 或 push。

### 6.3 Scope 与 dirty worktree 安全

`implement.code` 执行 `begin` 时，Helper 记录 baseline：implementation rerun 相对 active checkpoint，首次 implementation 相对 source revision。Checkpoint scope 只包含相对该 baseline 在本次 attempt 中发生变化的路径。工作区中已经由 active checkpoint 表达的内容，在 implementation rerun 时不视为无关 dirty change。

预先存在且与本次任务无关的 dirty paths 被排除。如果 implementation 修改了 attempt 开始时已经 dirty 的路径，所有权存在歧义，checkpoint 创建返回 `checkpoint_scope_ambiguous`，run 进入 `blocked` 等待人工处理。Helper 不得静默捕获用户已有工作。

以下路径始终排除：

- `.git/**`；
- `.ai-workflow/**`；
- `.mimosa/**`（编辑器插件运行时状态，如 mimosa 安全扫描插件的 hook-state 在每次工具调用时被改写；属插件所有，非交付物变更。此前其 pre-existing dirty 快照在 attempt 期间变化会误触发 `checkpoint_scope_ambiguous` 并 blocked）；
- workflow artifact、result、generated prompt、临时日志和报告；
- 配置的 protected paths；
- repository 外部路径；
- 逃逸 repository 的 symlink。

如果 implementation 没有产生代码变更，默认不能创建新 checkpoint。只有 active implementation result 明确表示 no-code delivery 时，才直接将 source revision 记录为 checkpoint，且无需创建 hidden ref。

### 6.4 Verification 锚定

没有 active checkpoint 时，不允许开始 verification。为了保持现有 schema-v2 DispatchPacket 和 ChildResult contract，verification 的 `DispatchPacket.source_revision` 使用 active checkpoint commit，而不是 run 最初的 source revision。Verification artifact 的现有 `ArtifactRef.source_revision` 必须复制该 checkpoint commit。Active 和 previous checkpoint record 持久化在 workflow state 中。

Helper 在以下环节校验 checkpoint：

- verification `begin`；
- child result `stage`；
- phase `finalize`；
- sibling result reuse；
- transition 和 recovery reconciliation。

Checkpoint 不匹配返回 `checkpoint_mismatch`；记录的 commit 或 hidden ref 无法解析时返回 `checkpoint_unavailable`。两者都 fail closed。激活新 checkpoint 时，所有 verification node（包括此前 valid 的 sibling）都重置为 `pending`，因为旧结果验证的是另一棵 tree。

## 7. 仓库配置与路径授权

### 7.1 配置 schema

`.ai-workflow.yaml` 必须包含 `schema_version: 2`。缺失、非整数或不支持的版本返回 `unsupported_schema_version`，并提供可执行提示。

显式迁移命令：

```text
ai-workflow config migrate --repo REPO --to 2 [--dry-run]
```

该命令只支持缺少版本声明或 version 1 的仓库配置，保留其他 key 和 value，只修改 v2 所需的 schema 声明。`--dry-run` 打印拟生成的 YAML，不写文件；实际写入必须原子化。未知的未来版本不得被重写。

本批次中，持久化 workflow state 和 ChildResult 继续使用 schema v2，现有严格校验保持不变。

### 7.2 路径语义

路径授权基于 normalized repository-relative POSIX path，而不是只匹配顶层 entry name。

Helper 必须：

- 无条件排除 `.git` 和 `.ai-workflow`；
- 将 `protected_paths` 同时应用于目标 entry 及其 descendants；
- 拒绝 absolute path、`..` traversal、repository escape 和 escaping symlink；
- 配置 adapter `source_paths` 或 `test_paths` 时，只把匹配的 repository content 作为普通 readable inputs；两者均未配置时，为兼容现有仓库，保留经过 protected-path 过滤的顶层输入策略；
- 通过 `ai-workflow config authorize-path --repo REPO --kind input|generated-test|report --path PATH` 为 specialist Skills 提供机械授权入口；
- 只允许 `generated_test_destinations` 下的 generated-test path；
- 只允许 `report_paths` 或 Helper-owned run artifact destination 下的 report path。

Workflow dispatch 使用相同的 input authorizer。后续批次增加的 specialist provider 在写入 generated-test/report 前必须调用对应 authorizer。因此，本批次无需改变 schema-v2 DispatchPacket shape，也能让 adapter fields 从提示词约定升级为可执行的授权数据。

## 8. 错误处理

新增稳定 error codes：

| Error code | 含义 | 必须采取的处理 |
| --- | --- | --- |
| `invalid_profile` | Profile 不是 `full` 或 `grill`。 | 修正 caller 输入，不创建 state。 |
| `unsupported_schema_version` | Repository config version 缺失、非法或不受支持。 | 对 v1/缺失版本执行 migration，或人工更新配置。 |
| `checkpoint_scope_ambiguous` | Implementation 修改了 attempt 开始前已经 dirty 的路径。 | Block 并等待人工处理。 |
| `checkpoint_creation_failed` | Git plumbing 无法创建 tree、commit 或 ref。 | 携带 command evidence 进入 blocked。 |
| `checkpoint_unavailable` | 已记录的 commit/ref 无法解析。 | Block，不 dispatch verification。 |
| `checkpoint_mismatch` | Verification evidence 引用了其他 checkpoint。 | 拒绝 stale evidence，并从当前 state 恢复。 |
| `path_not_authorized` | Input/output 不在有效 adapter/protected-path policy 内。 | 拒绝操作，不扩大 scope。 |

错误继续使用现有 JSON envelope。Skills 按 `error.code` 路由，不匹配自然语言 message。

## 9. 测试策略

所有 production change 都遵循 red-green-refactor，现有测试必须保持通过。

### 9.1 Unit tests

- full/grill graph 构建与 initial phase；
- 拒绝 unknown profile；
- 同 phase sibling reuse 和 downstream invalidation；
- implementation rerun 使旧 checkpoint verification 失效；
- temporary-index checkpoint creation；
- hidden-ref preservation；
- `HEAD`、branch 和 user index 保持不变；
- dirty baseline ambiguity detection；
- protected-path descendant matching，以及无条件排除 Git/workflow 路径；
- config v2 validation、migration dry-run 和 write behavior。

### 9.2 Contract tests

- workflow-owned PRD staging contract；
- verification dispatch 和 ChildResult artifact 的 checkpoint anchor 语义；
- active/previous checkpoint state shape；
- 精确 error codes 和 JSON envelope；
- Grill Skill 的 PRD issue 和 recovery 约束；
- migration CLI surface。

### 9.3 End-to-end tests

1. Grill run 从 `plan.prd` 开始，依次导入 PRD、完成 implementation、创建 checkpoint、执行 verification 并完成 run。
2. Verification finding 只重跑一个 verification child，并在 checkpoint 未变化时复用其他 sibling。
3. Implementation finding 使流程回到 `implement.code`，创建新 checkpoint，并重跑全部 verification child。
4. 新进程不依赖聊天记录，恢复 active checkpoint 并继续运行。
5. 修改与 dirty baseline 重叠的路径时，checkpoint 创建进入 blocked，且不移动 branch、不修改 user index。

### 9.4 验收证据

- 所有现有测试通过；
- 所有新增 focused 和 end-to-end tests 通过；
- Wiki lint 和 `git diff --check` 通过；
- 测试证据证明 checkpoint 创建没有移动 `HEAD`、改变业务分支、修改 user index 或 push；
- 没有完成真实 trial evidence 时，任何测试或文档都不声明 Codex/Claude Code parity。

## 10. 交付边界

本 P0 批次在 profile-aware execution、node recovery、checkpoint、config migration、path authorization 和 behavioral E2E 全部完成后结束。CI provider collection、integration-test provider、外部 telemetry exporter、仓库自身 CI/release automation，以及更大范围的 `WorkflowService` 拆分，继续作为独立后续批次。
