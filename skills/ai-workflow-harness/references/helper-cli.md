# Helper CLI：机械能力与 caller ownership

Helper 只持久化、校验和转换状态；语义正确性、rerun reason、Child 工作和人类决定归 Agent/人类所有。JSON envelope 成功为 `{"ok":true,"data":...}`；失败为 `{"ok":false,"error":{"code":"...","message":"...","details":...}}` 且非零退出。始终先判断 `ok`，按 `error.code` 路由。

## Wave 1 command matrix

| 命令 | caller / 条件 |
| --- | --- |
| `ai-workflow config show --repo REPO` | Harness，只读 |
| `ai-workflow workflow init --repo REPO --source-revision SHA --requirement TEXT --profile PROFILE` | Harness；new run |
| `ai-workflow workflow status --repo REPO --run-id RUN` | Harness；每次入口、transition 后、任何 stale 后 |
| `ai-workflow workflow begin --repo REPO --run-id RUN --phase PHASE --skill-dir SKILL_DIR` | Harness；当前 phase |
| `ai-workflow workflow stage --repo REPO --run-id RUN --attempt-id ATTEMPT --child CHILD --result FILE` | Harness；收到合法 ChildResult 后，逐个串行 |
| `ai-workflow workflow finalize --repo REPO --run-id RUN --attempt-id ATTEMPT` | Harness；barrier 满足后 |
| `ai-workflow workflow review --repo REPO --run-id RUN [--rerun NODE=REASON ...]` | Harness；finalize 后 |
| `ai-workflow workflow review-accept --repo REPO --run-id RUN --expected-digest SHA` | Harness；仅在人类明确接受该 digest 后 |
| `ai-workflow workflow transition --repo REPO --run-id RUN` | Harness；持久化 gate 已接受后 |
| `ai-workflow workflow block --repo REPO --run-id RUN --reason TEXT` | Harness；真实阻塞且证据充分 |
| `ai-workflow workflow resume --repo REPO --run-id RUN [--rerun NODE=REASON ...]` | 仅人类明确选择后由 Harness 代调用 |
| `ai-workflow workflow abort --repo REPO --run-id RUN` | 仅人类明确选择后由 Harness 代调用 |
| `ai-workflow workflow summary --repo REPO --run-id RUN` | Harness；terminal cleanup |

`dispatch` 是用 `prompt_file` 创建 Child Agent 的动作，`barrier` 是等待全部 sibling 合法结果的判断；二者都不是 CLI 子命令。

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
| `stale_state`、`attempt_owner_mismatch`、`review_gate_required`、`review_gate_mismatch` | 立即 `workflow status`，按 recovery 中的持久化证据继续 |
| `stale_review_gate` | `status` 后仍 stale 就 `workflow block`；等待人类 resume/abort，禁止 review loop |
| `result_conflict`、`dispatch_packet_conflict`、`dispatch_prompt_conflict`、`immutable_conflict` | 停止写入；`status` 后向人类呈现冲突，不覆盖文件 |
| `artifact_digest_mismatch`、`invalid_result`、`protected_artifact_path`、`unsupported_schema_version` | 拒绝该结果；只让原 Child 修复自己拥有的 artifact/ChildResult |
| `attempt_limit`、`command_timeout` | 收集证据，调用 `block`，等待人类 |
| `invalid_state`、`invalid_storage_path` | fail closed；禁止直接修 state，报告人工处置 |
| `invalid_arguments`、`invalid_command`、`invalid_profile`、`invalid_requirement`、`invalid_run_id`、`invalid_skill_dir`、`invalid_source_revision`、`config_invalid`、`config_not_found`、`repository_required` | 修正 caller 输入后重试；不得修改持久化状态 |
| `state_not_found`、`state_exists`、`invalid_transition`、`lifecycle_conflict` | 先 `status`/bootstrap，再依据真实状态路由 |

未列出的 code 也先 fail closed + `status`；禁止根据 message 文本伪造恢复动作。
