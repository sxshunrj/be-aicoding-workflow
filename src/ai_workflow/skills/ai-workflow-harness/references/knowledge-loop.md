# Knowledge loop：packet-only consumption

## Phase Child 读取

Child 只能从 dispatch `prompt_file` 内的 `knowledge_packet.path` 读取 Helper 生成的 bounded packet，并核对 `sha256`。禁止搜索、读取或引用 `raw Wiki Markdown`、`wiki/approved`、`wiki/candidates`；Harness 也不得把 raw 内容粘入 prompt。

packet 的 `selected_ids` 是本次允许引用的全集：

- 只把实际影响结论的 selected ID 写入 `knowledge_citations`。
- 每条引用在 artifact 中说明它支持的具体决策；packet 只是候选上下文，不自动等于事实。
- 未使用知识时返回空数组；禁止为提高“复用率”伪造引用。
- packet 缺失、digest 不符或所需知识不在 packet 时，返回有 evidence 的 `unable_to_complete` 或 finding，由 Harness 恢复；不要直接读 Wiki。

`workflow stage` 会验证 citation 是否属于该 Child packet。citation 拒绝只能由原 Child 修复自己的 artifact/ChildResult。

## Terminal knowledge

terminal reflection 只消费 run 中记录的 requirement、artifacts、findings、commands、review decisions、rerun reasons 与 citations。`knowledge-reflection.json` 的每个结论必须反向指向这些 evidence。

Candidate 仅通过 `$ai-knowledge-reflection` 提议；approved 生命周期仅通过 `$ai-knowledge-governance` 与人类 gate 变更。Harness 和 Child 都不得直接 promote 或写 approved 内容。
