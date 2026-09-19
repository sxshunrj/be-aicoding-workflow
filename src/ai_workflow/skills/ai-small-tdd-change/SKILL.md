---
name: ai-small-tdd-change
description: Use only when 用户显式点名 $ai-small-tdd-change 或明确要求 lightweight/small TDD AI coding workflow。
---

# AI Small TDD Change

这是 explicit-only 小改动工作流；不要因“看起来很小”自动触发。

## Loop

`clarify -> failing focused test -> minimal implementation -> focused pass -> independent verification -> lightweight review`

## Scope gate

先做三问澄清：目标行为、可接受改动范围、验证命令。若调查发现需要改 `public API`、`shared data model`、`multi-module` 行为，或存在 `high-risk compatibility` 风险，必须 `stop before editing`，说明证据，并询问是否 switch to `$ai-workflow-harness`。

## TDD discipline

1. 写最小聚焦测试，运行并记录 `RED evidence`；失败必须来自缺失行为，不是语法或环境错误。
2. 只写让测试通过的最小实现，不顺手重构无关代码。
3. 运行同一聚焦测试并记录 `GREEN evidence`。
4. 执行 independent verification：用配置或仓库习惯的更宽验证命令确认没有破坏周边行为。
5. 做 lightweight review：检查测试是否覆盖需求、实现是否过宽、是否遗漏错误路径或兼容性影响。

## Handoff

结束时报告改动文件、RED/GREEN/independent verification 命令与结果、lightweight review 发现。不要提交、建分支、push 或改 workflow state；Git 收尾交给 `$ai-git-handoff` 或人类明确指令。
