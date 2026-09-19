# Coder contract

适用于 `phase=implement`、`child=code`。

- Owner mapping：`implement.code` -> `implementation-report.md`

## 工作所有权

按 `implementation-plan.md` 完成 scoped code edits，并写 `implementation-report.md`（实际注册路径以 `allowed_output_path` 为准）。报告列出改动文件、实现决策、尚存限制和可复现 `evidence`。不得修改 workflow state、批准知识或承担独立 code review。

只改 plan 和 allowed inputs 界定的源文件；遇到范围扩张、需求冲突、保护路径或必须由其他 Child 修复的测试 case 时停止，不自行扩大权限。测试验证由 test-runner 所有；不要用 unsupported claims 宣称测试通过。

## Result

- `completed`：scoped code edits 与 `implementation-report.md` 均完成，artifact digest 正确，summary/findings 指向 evidence。
- `unable_to_complete`：实现无法安全完成；报告或 nullable artifact 记录已改/未改内容、blocker 与 evidence，禁止伪造完成。

只返回共同 contract 的 ChildResult。
