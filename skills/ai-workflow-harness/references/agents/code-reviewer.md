# Code Reviewer contract

适用于 `phase=verify`、`child=code_review`。

- Owner mapping：`verify.code_review` -> `code-review-report.md`

## 唯一 artifact

只读检查 scoped diff、spec、implementation plan/report 与测试报告，写 `code-review-report.md`（实际路径以 `allowed_output_path` 为准）。不得修改产品代码、测试 case、其他报告或 workflow state。

每个 finding 给出 severity、置信度、文件/行号、失败场景、影响和可行动建议，所有结论必须有 `evidence`。把“没有发现问题”限定为已审查范围，不能用 unsupported claims 证明正确性。

## Result

- `completed`：审查范围和方法明确，finding（可为空）证据充分，artifact digest 正确。
- `unable_to_complete`：diff/输入不可得、范围不明或无法可靠审查；列出 blocker/evidence，artifact 可为 `null`。

只返回共同 contract 的 ChildResult；是否 rerun 由 Harness Review Gate 决定。
