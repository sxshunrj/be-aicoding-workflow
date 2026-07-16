---
name: ai-knowledge-reflection
description: Use when ai-workflow run is completed or aborted and terminal cleanup needs evidence-backed knowledge reflection.
---

# AI Knowledge Reflection

Terminal reflection 只把已记录的 run evidence 转成明确的 no-candidate decision 或一个 candidate proposal。它不是 governance。

## Sequence

`workflow reflect -> read packet -> search related approved knowledge -> write decision -> optional proposal -> workflow reflect-submit -> wiki propose`

只在 `workflow status` 为 `completed` 或 `aborted` 时运行。先调用 `ai-workflow workflow reflect --repo REPO --run-id RUN`，读取 packet，再通过 CLI 搜索相关 approved knowledge。不要把聊天记忆当证据。

按 [proposal contract](references/proposal-contract.md) 的精确结构写 `knowledge-reflection-decision.json`。如果 outcome 是 `no_candidate`，只用 `workflow reflect-submit` 提交 decision 文件并报告原因。

如果 outcome 是 `candidate`，再写一个保持 schema-v1 不变的 `CandidateProposal` JSON：`knowledge-proposal.json`。proposal 必须包含当前 run source。先用 `workflow reflect-submit` 提交 decision 和 proposal；只有提交成功后，才能调用 `wiki propose`。

## Boundaries

- 永远不要调用 `wiki promote`
- 永远不要直接写 `wiki/approved`
- reflection acceptance 不是 governance approval
- 不要编造 claim
- 不要包含 secrets
- 如果和已有 approved knowledge 有冲突，在 proposal 中说明，不要自行解决冲突
