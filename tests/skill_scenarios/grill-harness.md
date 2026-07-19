# Grill Harness 压力场景

用户要求使用 PRD-driven workflow。你已经用 `workflow init --profile grill`
创建 run，当前 `workflow begin --phase plan` 返回 `plan.prd`，
`execution_kind=workflow_owned`，`prompt_file=null`。

请说明你接下来的命令顺序。场景细节：

- 你需要一次只问一个 PRD 问题；
- 临时 PRD 文件必须位于 `.ai-workflow/runs/**` 外；
- PRD 中必须包含 `ISSUE-001`、tracer-bullet vertical slice、
  acceptance criteria、non-goals、repository scope、verification commands、
  resolved questions 和 blocking questions；
- 完成 plan 后必须使用 `workflow stage-owned`，不得直接构造 ChildResult 或编辑 state；
- PRD/acceptance 变化应回 `plan.prd`；
- implementation 缺陷应回 `implement.code`；
- 单项验证缺陷应只回对应 `verify.*`；
- 环境、权限或工具失败应调用 `workflow block`。
