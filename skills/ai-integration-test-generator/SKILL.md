---
name: ai-integration-test-generator
description: Use when 用户要求基于 repository adapter 生成或更新 integration-test assets。
---

# AI Integration Test Generator

基于 repository adapter 生成或更新 integration-test assets。不要在缺少 adapter 的仓库里猜测路径。

## Required adapter

先读取 `.ai-workflow.yaml`，确认 repository adapter 存在：

- `source_paths`
- `test_paths`
- `generated_test_destinations`
- `report_paths`
- `commands.integration_test`
- `protected_paths`

## Rules

- 只写被 adapter 授权的测试路径，优先写入 `generated_test_destinations`。
- 不得修改生产代码，不得改 workflow state，不得写 protected paths。
- 生成前先读取已有测试资产，避免重复 case。
- 每个新 case 必须对应 checklist evidence 或明确需求来源。
- 如果 adapter 不足，停止并列出缺失字段，不要猜测目录。

## Output

结束时输出变更摘要和验证命令：

- 新增或更新的测试文件
- 对应 evidence/checklist item
- 需要运行的 `commands.integration_test`
- 未覆盖缺口和原因

详细 adapter 字段见 [repository adapter](references/repository-adapter.md)。
