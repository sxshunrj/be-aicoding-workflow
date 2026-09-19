# PRD Loop

plan phase 由主 Agent 拥有。一次只问一个问题，直到可以写出 PRD artifact。

plan 不派 child，不创建 prompt_file，不要求 schema-v2 ChildResult。plan 的输出是 workflow-owned PRD artifact，通过 `stage-owned` 或等价 Helper 入口登记。不得直接构造 ChildResult，不得直接编辑 `.ai-workflow/runs/**`。

## Inputs

- 用户原始需求；
- repository config/profile；
- 已恢复 run state（如有）；
- 必要的只读代码/文档证据；
- 用户逐轮回答。

不要把聊天记录当作后续 implement 的隐式输入。PRD artifact 必须自含 implement/verify 需要的上下文。

## Question loop

一次只问一个问题。每个问题必须服务于以下之一：

- requirement summary；
- repository scope；
- acceptance criteria；
- non-goals；
- open questions；
- verification commands；
- risk or rollback boundary。

优先问会阻塞实现或验收的问题。不要一次抛出长问卷。每次用户回答后，更新内部 PRD 草稿，再判断是否还有 blocking questions。

## Required sections

PRD artifact 必须包含：

- `ISSUE-001`：本 PRD 内部 issue identifier；它是内容标识，不是 dynamic run-graph node。
- tracer-bullet vertical slice：最小端到端行为切片，说明第一轮实现如何证明主路径。
- requirement summary
- acceptance criteria
- non-goals
- open questions
- resolved questions
- blocking questions
- repository scope
- verification commands

如果 open questions 仍影响实现或验收，停止并继续提问，不进入 implement。

推荐 Markdown 结构：

```markdown
# PRD: <short title>

## Issue Identifier
ISSUE-001

## Requirement Summary

## Tracer-Bullet Vertical Slice

## Repository Scope

## Acceptance Criteria

## Non-Goals

## Resolved Questions

## Blocking Questions

## Implementation Notes

## Verification Commands

## Risks And Rollback
```

## Acceptance criteria

Acceptance criteria 必须可验证。避免：

- “体验更好”；
- “尽量兼容”；
- “性能不错”；
- “看情况处理”。

改写为：

- “当输入 X 时，接口返回 Y，并记录 Z 日志”；
- “当配置缺失时，命令以 error code A fail closed”；
- “`pytest path::test_name` 通过”。

## Non-goals

Non-goals 用于保护实现范围。写清本 run 不做的内容，例如：

- 不改 public API；
- 不迁移历史数据；
- 不接入真实 CI provider；
- 不优化不相关模块。

如果用户后续反馈触碰 non-goal，Harness 在 Review Gate 中把它映射为 plan rerun 或新 run 决策，不让 implement child 自行扩大范围。

## Open / resolved / blocking questions

- `resolved questions`：已经由用户或代码证据回答，后续 child 可依赖。
- `open questions`：不阻塞实现但需要记录的不确定性。
- `blocking questions`：没有答案就无法实现或验收。

`blocking questions` 非空时，不进入 implement。继续一次只问一个问题。

## Stage-owned handoff

PRD 完成后：

1. 把 PRD 写到 `.ai-workflow/runs/**` 外的普通临时路径；
2. 调 Helper 的 workflow-owned staging 入口（计划名为 `stage-owned` 或当前实现等价入口）；
3. Helper 复制/登记 artifact；
4. Harness 进入 finalize/review；
5. Review Gate 接受后才 transition 到 implement。

临时 PRD 位于 `.ai-workflow/runs/**` 外。Helper 会把它不可变导入 run storage；主 Agent 不得把 run storage 内文件再作为 source。

不得：

- 手写 `.ai-workflow/runs/**`；
- 手写 ChildResult；
- 直接构造 ChildResult；
- 编辑 state 或 events；不得编辑 state；
- 把 PRD 作为 dynamic run-graph node；
- 让 child agent 替主 Agent 问 PRD 问题。

## Ready checklist

进入 implement 前，逐项确认：

- requirement summary 能被非对话读者理解；
- repository scope 指到具体目录/模块；
- acceptance criteria 可测试；
- non-goals 明确；
- resolved questions 足以支撑实现；
- blocking questions 为空；
- verification commands 或缺失原因已写明；
- PRD artifact 已通过 Helper 登记。
