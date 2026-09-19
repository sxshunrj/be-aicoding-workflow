# Planner contract

按 Dispatch Packet 的 `child` 选择一个 owner；一次 dispatch 只写一个 artifact。

- Owner mapping：`plan.solution` -> `implementation-plan.md`
- Owner mapping：`plan.test_strategy` -> `test-strategy.md`

## `solution` -> `implementation-plan.md`

把 accepted technical spec 转为按依赖排序的实现步骤。为每步标出目标文件/组件、行为变化、验证方式、风险与回滚边界；引用 prior artifact 或代码路径作为 `evidence`。不得编码、执行测试或写 `test-strategy.md`。

## `test_strategy` -> `test-strategy.md`

独立定义 unit/integration/build/review 的覆盖矩阵、关键失败路径、测试数据、命令来源、通过标准与无法自动化的人工检查；引用 spec 与 repository profile 作为 `evidence`。不得写实现计划、测试代码或修 case。

## Result

- `completed`：所选 artifact 完整且 digest 可验证；另一 sibling 的输出不构成完成条件。
- `unable_to_complete`：输入不足或不可执行，列出 blocker/evidence，artifact 可为 `null`。

只返回共同 contract 的 ChildResult；`solution` 与 `test_strategy` 都必须各自返回，不能合并。
