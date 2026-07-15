# Test Runner contract

按 Dispatch Packet 的 `child` 选择唯一 artifact：

| child | artifact |
| --- | --- |
| `build` | `build-report.md` |
| `unit_test` | `unit-test-report.md` |
| `integration_test` | `integration-test-report.md` |

## 执行

只执行 packet `commands` 中属于当前 child 的 argv，保持参数顺序；不得把 shell 字符串重新解释、发明命令、编辑产品代码或修测试 case。记录命令、退出码、关键 stdout/stderr、失败测试与环境作为 `evidence`。报告路径以 `allowed_output_path` 为准。

## Result

- `completed`：命令确实执行且满足 test strategy 的通过标准，artifact digest 正确；无命令时必须有 owner contract 明确的可验证替代证据。
- `unable_to_complete`：命令失败、超时、环境缺失或结果不可信；如实记录 evidence，artifact 可为 `null`，不得把失败改写为成功。

stale 时不查 status、不 claim attempt、不 stage；只返回/修复本 ChildResult。Harness 决定 rerun。
