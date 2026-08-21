---
name: ai-integration-test-v2
description: Use when 用户要求执行、诊断或收敛 integration tests，且不能让 case 迎合错误代码。
---

# AI Integration Test V2

用于执行、诊断和收敛集成测试。核心纪律：不能让 case 迎合错误代码。

## Loop

`execute -> diagnose -> classify -> fix -> rerun`

## Discipline

- 先执行 repository adapter 中的 integration-test 命令，保留 Rerun evidence。
- 先定位失败归因，再修改；每次只改一个归因。
- 归因类别：`implementation bug`、`test asset bug`、`environment issue`、`mock/fixture drift`。
- 如果是 implementation bug，修实现或退回 `$ai-workflow-harness` 的 implement rerun。
- 如果是 test asset bug，修 case、fixture、mock 或初始化数据。
- 如果是 environment issue，进入 blocked 或要求用户提供环境，不伪造成代码失败。**要求用户提供环境/进入人工等待前**，若已配置通知通道，调用 `ai-workflow wecom notify --repo REPO --gate blocked --action "集成测试环境问题，需人工提供环境或决策" --summary "<环境失败摘要>"` 通知团队；失败仅写 warning，不影响主流程。
- 如果是 mock/fixture drift，先证明真实契约，再更新测试资产。

## Hard rules

- 不要为了通过测试而把 expected output 改成 broken behavior。
- 不要一次混改实现、case、mock 和环境配置。
- 不要删除失败 case 来制造通过。
- 每次 rerun 都报告命令、退出码、关键日志和仍未解决的问题。

详见 [convergence](references/convergence.md)。
