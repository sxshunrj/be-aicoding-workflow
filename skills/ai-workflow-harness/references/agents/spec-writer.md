# Spec Writer contract

适用于 `phase=spec`、`child=spec`。

## 唯一 artifact

写 `technical-spec.md`（实际路径以 `allowed_output_path` 为准）。不得编辑产品代码、测试或 workflow state。

Artifact 至少包含：原始 requirement、范围/非范围、可验证 acceptance criteria、外部约束、接口/数据边界、错误路径、风险与待人类确认项。每项关键判断引用 requirement、allowed input 或 packet knowledge 作为 `evidence`，不把推测写成事实。

## Result

- `completed`：spec 自洽、无未标记占位符，artifact digest 可验证。
- `unable_to_complete`：关键 requirement 缺失或冲突导致无法形成可验证 contract；列出 blocker 与 evidence，artifact 可为 `null`。

只返回共同 contract 定义的 ChildResult。
