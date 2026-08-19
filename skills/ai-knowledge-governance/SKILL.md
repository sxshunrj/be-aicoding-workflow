---
name: ai-knowledge-governance
description: Use when reviewing ai-workflow candidate knowledge for human promotion, rejection, or leaving it unchanged.
---

# AI Knowledge Governance

Knowledge governance 是人类 gate。Agent 只负责收集事实、比较 material differences，并且只执行人类选择的 digest-protected lifecycle action。

## Sequence

`wiki review -> inspect candidate evidence, scope, reuse reason, conflicts, expiry, and related approved entries -> show digest and material differences -> human choice -> execute exactly one digest-protected lifecycle command -> report result`

先运行 `ai-workflow wiki review --wiki PATH --id ID`。读取 candidate digest、declared conflicts/supersedes 和 related approved entries。展示选择前必须按 [review checklist](references/review-checklist.md) 检查。

人类选择只有 `promote`、`reject` 或 `leave candidate unchanged`。No choice may default to promote；沉默等于保持不变。

展示人类选择前，若已配置通知通道，调用 `ai-workflow wecom notify --repo <repo> --run-id <run-id> --gate governance --action "请选择 promote / reject / 保持"` 通知团队；失败仅写 warning，不影响主流程。`<repo>` 为当前仓库路径、`<run-id>` 为当前 run（若本流程不在某个 run 内则省略 `--run-id`）。

如果人类选择 `promote`，用 candidate `expected-digest` 调用 `wiki promote`。如果人类选择 `reject`，用 `expected-digest` 和明确 reason 调用 `wiki reject`。不要在 candidate flow 中 archive approved entries，除非人类另行发起 approved-retirement action。

最后报告 approved path/searchability、archived path，或 unchanged candidate ID 和 digest。
