---
name: ai-workflow-harness-grill
description: Use when 用户显式要求 PRD-driven plan/implement/verify workflow，或要求 ai-workflow grill harness。
---

# AI Workflow Harness Grill

Grill 是交互式 PRD 驱动 workflow。它只用于用户显式要求，不替代 `$ai-workflow-harness`。

## Control loop

`plan -> implement -> verify`

- plan phase 由主 Agent 交互式拥有：一次只问一个问题，澄清目标、范围、acceptance criteria、non-goals 和 open questions。
- plan phase 写 run-local PRD artifact；PRD issue identifier 是内容标识，不是 dynamic run-graph node。
- implement 和 verify 仍然 child-backed，遵守 prompt_file、ChildResult、stage、barrier、finalize、review gate。
- 不得直接编辑 `.ai-workflow/runs/**`；所有状态变化只通过 Helper CLI。
- 如果需求扩大到多条独立 workflow，先拆分 PRD，不要在一个 Grill run 里混合。

## References

- [PRD loop](references/prd-loop.md)
- [Dispatch](references/dispatch.md)
