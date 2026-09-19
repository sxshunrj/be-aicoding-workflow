# Helper CLI：机械能力与 caller ownership

Helper 只持久化、校验和转换状态；语义正确性、rerun reason、Child 工作和人类决定归 Agent/人类所有。JSON envelope 成功为 `{"ok":true,"data":...}`；失败为 `{"ok":false,"error":{"code":"...","message":"...","details":...}}` 且非零退出。始终先判断 `ok`，按 `error.code` 路由。

## Wave 1 command matrix

| 命令 | caller / 条件 |
| --- | --- |
| `ai-workflow config show --repo REPO` | Harness，只读 |
| `ai-workflow config authorize-path --repo REPO --kind input|generated-test|report --path PATH` | Harness 或 specialist Skill；机械路径授权 |
| `ai-workflow workflow init --repo REPO --source-revision SHA --requirement TEXT --profile PROFILE` | Harness；new run |
| `ai-workflow workflow status --repo REPO --run-id RUN` | Harness；每次入口、transition 后、任何 stale 后 |
| `ai-workflow workflow begin --repo REPO --run-id RUN --phase PHASE [--skill-dir SKILL_DIR]` | Harness；当前 phase；child-backed 必须传 skill-dir |
| `ai-workflow workflow stage --repo REPO --run-id RUN --attempt-id ATTEMPT --child CHILD --result FILE` | Harness；收到合法 ChildResult 后，逐个串行 |
| `ai-workflow workflow stage-owned --repo REPO --run-id RUN --attempt-id ATTEMPT --phase plan --child prd --artifact FILE --summary TEXT` | Harness；workflow-owned PRD 导入 |
| `ai-workflow workflow finalize --repo REPO --run-id RUN --attempt-id ATTEMPT` | Harness；barrier 满足后 |
| `ai-workflow workflow review --repo REPO --run-id RUN [--rerun NODE=REASON ...]` | Harness；finalize 后 |
| `ai-workflow workflow review-accept --repo REPO --run-id RUN --expected-digest SHA` | Harness；仅在人类明确接受该 digest 后 |
| `ai-workflow workflow transition --repo REPO --run-id RUN` | Harness；持久化 gate 已接受后 |
| `ai-workflow workflow block --repo REPO --run-id RUN --reason TEXT` | Harness；真实阻塞且证据充分 |
| `ai-workflow workflow resume --repo REPO --run-id RUN [--rerun NODE=REASON ...]` | 仅人类明确选择后由 Harness 代调用 |
| `ai-workflow workflow abort --repo REPO --run-id RUN` | 仅人类明确选择后由 Harness 代调用 |
| `ai-workflow workflow summary --repo REPO --run-id RUN` | Harness；terminal cleanup |

`dispatch` 是用 `prompt_file` 创建 Child Agent 的动作，`barrier` 是等待全部 sibling 合法结果的判断；二者都不是 CLI 子命令。

## Caller ownership

Helper CLI 是顺序协议，不是并发优化对象。所有 workflow 写动词只允许 Harness 主 Agent 串行调用。Child Agent 不调用 workflow helper，也不得让自己看起来像 `caller=workflow`。

| 能力 | 允许调用者 | 禁止 |
| --- | --- | --- |
| `workflow status` | Harness | Child 用它取得 attempt 或推断调度 |
| `workflow begin` | Harness | Child 自行 claim/start 新 attempt |
| `workflow stage` | Harness | Child stage 自己或 sibling result |
| `workflow stage-owned` | Harness | Child 或普通 phase 伪造 workflow-owned artifact |
| `workflow finalize` | Harness | Child 推进 phase |
| `workflow review` / `review-accept` | Harness | Child 触发或接受 gate |
| `workflow transition` | Harness | Child 或 Harness 在 gate 前推进 |
| `workflow block` / `resume` / `abort` | Harness 代人类决定 | 自动恢复、自动终止 |
| `config authorize-path` | Harness / specialist Skill | 未授权就读写路径 |

所有写状态的命令都必须在前一个命令完成并读完 JSON 后再执行。不要把 `begin`、多个 `stage`、`finalize`、`review`、`transition` 放进并行 tool call。

## config authorize-path

用途：把 repository adapter 和 protected path 从提示词约定升级成机械检查。任何 specialist Skill 在读 input、写 generated test、写 report 前都先调用。

```text
ai-workflow config authorize-path --repo REPO --kind input --path PATH
ai-workflow config authorize-path --repo REPO --kind generated-test --path PATH
ai-workflow config authorize-path --repo REPO --kind report --path PATH
```

成功 envelope：

```json
{"ok": true, "data": {"authorized": true, "kind": "input", "path": "src/app.py"}}
```

失败 envelope 以 `path_not_authorized` fail closed：

- 不读取该 input；
- 不写该 generated test/report；
- 不扩大到父目录；
- 不猜测替代路径；
- 不要求 Child 绕过 Helper。

`input` 使用 `adapter.source_paths ∪ adapter.test_paths`；两者为空时仅允许经过 protected-path 过滤的 fallback roots。`generated-test` 只允许 `adapter.generated_test_destinations`；`report` 只允许 `adapter.report_paths` 或 Helper 明确给出的 child-owned output。

## Workflow command details

### `workflow init`

创建 run。Harness 提供原始 requirement、source revision 和 profile。Helper 只校验 shape、初始化 graph 和 policy；不改写需求语义。

失败恢复：

| error.code | Harness action |
| --- | --- |
| `config_not_found` / `config_invalid` | 展示字段错误，等待用户修配置。 |
| `invalid_requirement` / `invalid_profile` | 修正 caller 输入后重试。 |
| `state_exists` | 走 bootstrap/status，不覆盖旧 run。 |

### `workflow status`

每次入口、transition 后、stale 后、新会话后都先调用。它是 `new-conversation status recovery` 的唯一入口。

Harness 只消费 JSON data 中的 run status、current phase、run graph、artifacts 和 review/block 信息。不要从聊天补充隐藏状态。

### `workflow begin`

开始或恢复当前 phase attempt。Child-backed phase 必须传 `--skill-dir`，因为 Helper 需要 owner/common contract 路径和 prompt file。返回值中的 `dispatch_plan` 是唯一调度依据。

`dispatch_plan` action：

| action | Harness action |
| --- | --- |
| `dispatch` | 派发 fresh child，传 `prompt_file`。 |
| `rerun` | 派发 child，强调只处理 packet reason。 |
| `already_staged` | 不重派；等待其他 sibling 或 finalize。 |

Helper 可能在恢复时返回同一 attempt。Harness 不自行生成 attempt ID。

workflow-owned item（当前为 Grill `plan.prd`）返回：

```json
{
  "node": "plan.prd",
  "child": "prd",
  "execution_kind": "workflow_owned",
  "action": "dispatch",
  "allowed_artifact_path": ".../attempts/<attempt_id>/artifacts/prd.md",
  "prompt_file": null,
  "packet_file": null
}
```

该 item 不派 child、不读 prompt、不构造 ChildResult。主 Agent 在 run storage 外写临时 PRD 后调用 `workflow stage-owned`。

### `workflow stage`

提交一个 ChildResult。Harness 保存 child 原始 JSON 到临时文件，再串行调用。不要修改 ChildResult 字段，也不要把自然语言总结包装成 result。

可恢复错误：

| error.code | Harness action |
| --- | --- |
| `attempt_owner_mismatch` | status -> begin -> 重新派发 owner child。 |
| `artifact_digest_mismatch` | 原 Child 修复 artifact/ChildResult。 |
| `invalid_result` | 原 Child 修复 schema/owner/evidence。 |
| `path_not_authorized` | fail closed；不扩大路径。 |
| `result_conflict` | 保留冲突证据，报告人类。 |

### `workflow stage-owned`

用途：导入 workflow-owned artifact。当前只用于 Grill `plan.prd`。

```text
ai-workflow workflow stage-owned --repo REPO --run-id RUN --attempt-id ATTEMPT --phase plan --child prd --artifact FILE --summary TEXT
```

规则：

- `FILE` 必须是 regular non-symlink file；
- `FILE` 必须位于 `.ai-workflow/runs/**` 外；
- `phase/child` 必须匹配当前 attempt 的 workflow-owned node；
- `summary` 非空；
- Helper 将 artifact 不可变复制到 `allowed_artifact_path`；
- Helper 合成 schema-v2 ChildResult 并走普通 staged result/barrier/finalize 协议；
- 禁止主 Agent 手写 ChildResult 或编辑 state。

失败恢复：

| error.code | Harness action |
| --- | --- |
| `attempt_owner_mismatch` | status -> begin，确认当前 attempt 和 node。 |
| `invalid_result` | 修正 PRD source 文件或 summary 后重试。 |
| `result_conflict` | 保留冲突证据，向人类报告，不覆盖。 |

### `workflow finalize`

只在 barrier 满足后调用。它聚合本 attempt 的 staged children，不推进 phase。

`barrier_incomplete` 不算 Child failure：status/begin 看缺哪个 sibling，继续 wait。

### `workflow review`

只在 finalize 后调用。Harness 先推导 proposed reruns，再传 `--rerun NODE=REASON`。没有 rerun 也调用 review。

返回：

| decision | Harness action |
| --- | --- |
| `human_review` | 展示 digest、产物摘要、需要重跑的节点，等待人类。 |
| `accept` | 说明已接受，继续 transition。 |

### `workflow review-accept`

只在人类明确接受当前 digest 后调用。digest 必须来自最新 `workflow review` 输出。

`review_gate_mismatch`：status -> review，重新展示 digest。
`stale_review_gate`：status -> block -> human resume/abort。

### `workflow transition`

只在 gate 已接受后调用。它消费持久化 gate，推进 phase 或回到最早 rerun node。当前实现不在 transition 传 rerun 参数；rerun proposal 已在 review gate 中固化。

transition 后立刻 status。不得凭 transition 前的预期继续下一步。

### `workflow block` / `resume` / `abort`

`block` 用于真实阻塞：环境不可用、state integrity、stale review gate、权限缺失、attempt limit。blocked 后不再自动执行任何 phase 命令。

`resume` 和 `abort` 只在人类选择后调用。`resume --rerun NODE=REASON` 的 reason 仍要 actionable。

### `workflow summary`

terminal cleanup 的纯读入口。summary 不是 cleanup checkpoint，不表示 Git handoff 或 knowledge governance 已完成。

Knowledge commands 由 named knowledge Skill 调用：

```text
ai-workflow wiki lint --wiki PATH
ai-workflow wiki search --wiki PATH [QUERY FILTERS]
ai-workflow wiki packet --wiki PATH --output FILE [QUERY FILTERS]
ai-workflow wiki propose --wiki PATH --proposal FILE
ai-workflow wiki promote --wiki PATH --id ID --reviewer NAME --expected-digest SHA
ai-workflow wiki reject --wiki PATH --id ID --reviewer NAME --reason TEXT --expected-digest SHA
ai-workflow wiki archive --wiki PATH --id ID --reviewer NAME --reason TEXT --expected-digest SHA
```

`promote`、`reject`、`archive` 必须经过 governance 人类决定。Child 永远不调用任何 workflow/wiki helper。

## error.code recovery routing

| code 类别 | 处理 |
| --- | --- |
| `barrier_incomplete` | 不算 Child failure；等待缺失 sibling，再 stage/finalize |
| `stale_state`、`attempt_owner_mismatch`、`review_gate_required` | 立即 `workflow status`，按 recovery 中的持久化证据继续 |
| `review_gate_mismatch` | `workflow status` 后重新 `workflow review`；不 block |
| `stale_review_gate` | `status` 后仍 stale 就 `workflow block`；等待人类 resume/abort，禁止 review loop |
| `result_conflict`、`dispatch_packet_conflict`、`dispatch_prompt_conflict`、`immutable_conflict` | 停止写入；`status` 后向人类呈现冲突，不覆盖文件 |
| `artifact_digest_mismatch`、`invalid_result`、`protected_artifact_path`、`path_not_authorized`、`unsupported_schema_version` | 拒绝该结果；只让原 Child 修复自己拥有的 artifact/ChildResult；`path_not_authorized` 不扩大路径 |
| `attempt_limit`、`command_timeout` | 收集证据，调用 `block`，等待人类 |
| `invalid_state`、`invalid_storage_path` | fail closed；禁止直接修 state，报告人工处置 |
| `invalid_arguments`、`invalid_command`、`invalid_profile`、`invalid_requirement`、`invalid_run_id`、`invalid_skill_dir`、`invalid_source_revision`、`config_invalid`、`config_not_found`、`repository_required` | 修正 caller 输入后重试；不得修改持久化状态 |
| `state_not_found`、`state_exists`、`invalid_transition`、`lifecycle_conflict` | 先 `status`/bootstrap，再依据真实状态路由 |

未列出的 code 也先 fail closed + `status`；禁止根据 message 文本伪造恢复动作。

## Recovery quick routes

| situation | route |
| --- | --- |
| 新会话或 context 丢失 | `workflow status -> workflow begin` |
| ChildResult stale | `workflow status -> workflow begin -> redispatch owner child` |
| barrier 未满 | 等待缺失 sibling，不 finalize |
| review digest mismatch | `workflow status -> workflow review` |
| stale review gate | `workflow status -> workflow block -> human resume/abort` |
| artifact path unauthorized | stop, return to owner child or adapter config |
| terminal run | `workflow summary -> terminal reflection -> governance -> Git handoff` |
