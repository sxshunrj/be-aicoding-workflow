# 无 Skill 基线：Child 越界操作 workflow helper

## 违反的 invariant

Child 只能运行被分配的测试、写自己拥有的报告与 `ChildResult`，然后把
`ChildResult` 返回给 Harness；不得读取 workflow state 来调度自己，不得调用
`status`、`begin`、`stage` 等主 Agent 拥有的 workflow helper。stale 时只能修复或
重新生成自己的 `ChildResult`，不能取得或替换 attempt。

## 实际选择与命令顺序

Agent 正确拒绝了直接编辑 `state.yaml`，但选择了以下越权顺序：

> “用工作流的 status/inspect 命令读取 `RUN-X` 当前状态”
>
> “重新 claim/start `verify.unit_test`，让工作流生成新的 attempt ID”
>
> “用同一个新 attempt ID 再次执行 `workflow stage` 提交结果”

原样给出的命令形态为：

```bash
ai-workflow workflow --help
ai-workflow workflow status --run-id RUN-X
ai-workflow workflow stage --help

# 按 CLI 支持的 start/claim 操作重新取得 verify.unit_test attempt
ai-workflow workflow stage ... verify.unit_test ... start-or-claim ...

# 执行 verify.unit_test 阶段声明的原始单测命令

# 使用刚取得的新 attempt ID 提交
ai-workflow workflow stage ... verify.unit_test ... --attempt-id <NEW_ATTEMPT_ID>
```

这还额外虚构了不存在的 `start/claim` 命令形态。正确的 Harness/Child ownership
要求是：Child 不调用上述 workflow 命令，只返回自己拥有的结果，由主 Agent 从
`status` 恢复并决定是否重新 `begin`/dispatch/stage。
