# 所有 Phase Child 的共同 contract

Owner contract 与本文件共同生效；冲突时返回 `unable_to_complete` 并说明冲突，不扩大权限。

## Ownership 与 allowed I/O

1. dispatch API 只传入 Helper 生成的绝对 `prompt_file`。先读其中的 Dispatch Packet；`common_contract_path`、`owner_contract_path`、`knowledge_packet.path` 是绝对路径。
2. `allowed_input_paths` 是 repository-relative：从绝对 `prompt_file` 中定位 `.ai-workflow/runs/`，其前缀就是 repository root；只在该 root 下解析 normalized relative path，拒绝逃逸。`allowed_output_path` 是唯一可 stage 的物理路径，它同样相对该 root。
3. Owner contract 中的 canonical filename 表示逻辑 artifact contract；若它与 packet 物理路径不同，内容仍遵守 owner contract，但 ChildResult 的 `artifact.path` 必须逐字使用 `allowed_output_path`，不得替换成 canonical filename。
4. 只写 owner contract 授权的 artifact；`implement.code` 可额外做 planner 已限定的 scoped code edits。不要读取未列出的输入。
5. 不读取 raw Wiki Markdown，不修改 `wiki/approved`。
6. 不读写 `.ai-workflow/runs/**/state.yaml`、events、attempt 或 packet；不调用任何 `workflow helper`（包括 `status`、`begin`、`stage`、`finalize`）。把结果返回 Harness，由 Harness stage。

## schema-v2 ChildResult

只返回一个 JSON object，不加 Markdown fence 或说明；字段必须恰好为：

```json
{
  "schema_version": 2,
  "run_id": "<packet.run_id>",
  "phase": "<packet.phase>",
  "child": "<packet.child>",
  "attempt_id": "<packet.attempt_id>",
  "execution_mode": "fresh|rerun",
  "status": "completed|unable_to_complete",
  "summary": "非空结论",
  "artifact": {
    "path": "<packet.allowed_output_path>",
    "sha256": "<64 lowercase hex>",
    "schema_version": 2,
    "phase": "<packet.phase>",
    "child": "<packet.child>",
    "source_revision": "<packet.source_revision>"
  },
  "findings": [{"id": "...", "title": "...", "detail": "..."}],
  "knowledge_citations": ["<packet selected ID>"]
}
```

## completed / unable_to_complete

- `completed`：artifact 必须存在于 `allowed_output_path`，sha256 与实际 bytes 相符；summary/findings 必须给出 command、文件或行号等 `evidence`，不能用 unsupported claims。
- `unable_to_complete`：artifact 可为 `null`；summary/findings 说明已尝试动作、真实 blocker 与 evidence。不得伪造成功或把沉默/tool failure 当结论。
- 两种 status 都只代表本 Child 的工作，不代表 phase 已通过；Harness barrier/review 决定后续。

## citation

`knowledge_citations` 只能包含 packet selected IDs，去重且非空字符串。artifact 要说明引用支持了哪个决策；没使用则 `[]`。

## rerun-response

当 `execution_mode=rerun` 时，只处理 packet 的 `rerun_reason`，保留新的 evidence，并原样返回当前 identity。stale/拒绝时不替换 `attempt_id`：停止，向 Harness 返回/重产自己拥有的 ChildResult；Harness 会恢复并重新 dispatch。
