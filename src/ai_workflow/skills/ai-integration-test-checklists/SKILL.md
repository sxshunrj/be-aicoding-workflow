---
name: ai-integration-test-checklists
description: Use when 用户要求把需求、设计、PRD、diff 或实现说明转换成 integration-test checklist。
---

# AI Integration Test Checklists

把需求来源、设计、PRD、代码 diff 或实现说明转换成 evidence-mapped checklist。不要生成泛泛 checklist。

## Inputs

先收集并标注证据来源：

- 需求来源：用户描述、PRD、issue、验收标准。
- 设计来源：spec、plan、架构说明、接口契约。
- 代码 diff：变更文件、入口、分支、错误路径、数据模型。
- 已有测试资产：已有 case、fixture、mock、测试命令。

## Output

按 [checklist schema](references/checklist-schema.md) 输出：

- Scope：本次 checklist 覆盖的 repo、service、接口、路径。
- Evidence Map：每条需求或风险对应到具体 evidence。
- Checklist Items：每项都必须指向 evidence，写清 setup、action、expected result。
- Gap Analysis：明确缺口、风险和无法覆盖原因。
- Verification Commands：列出可执行命令或说明为什么当前没有命令。

## Rules

- 每个覆盖项必须能追溯到 evidence。
- 对无 evidence 的猜测，放入缺口或 open question，不写成测试项。
- 优先覆盖跨模块交互、外部接口、状态迁移、错误处理、幂等、权限和数据一致性。
- 不修改代码、不生成测试文件、不改 workflow state；这里只产出 checklist。
