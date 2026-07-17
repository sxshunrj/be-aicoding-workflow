# Dispatch

implement 和 verify 使用 child-backed 执行。

- 只把 Helper 生成的 `prompt_file` 交给 child。
- child 只返回 schema-v2 `ChildResult`。
- 主 Agent serially `stage` 每个 child result。
- `barrier` 未满足时不得 `finalize`。
- `finalize` 后才进入 review gate。

Grill 的 dispatch 继承 `$ai-workflow-harness` 的 child-backed 规则。本文件只记录 Grill 特有的 plan-owned -> implement/verify child-backed 交接。

## From PRD to implement

plan phase 完成后，Helper state 中应存在 workflow-owned PRD artifact。Implement child 的 prompt_file 必须引用该 artifact；Harness 不把聊天记录或 PRD 摘要手写进 dispatch query。

Dispatch query 固定保持：

```text
Read <prompt_file>, follow it exactly, and return only the schema-v2 ChildResult JSON.
```

dispatch 不追加隐藏上下文。用户在 plan Review Gate 后的新反馈，先映射为 plan rerun 或 implement rerun，不直接塞进 child prompt。

## Implement child

Implement child 负责：

- 读取 prompt_file 中的 Dispatch Packet；
- 读取 workflow-owned PRD artifact；
- 读取 allowed input paths；
- 做 scoped code edits；
- 写 implementation artifact；
- 返回 ChildResult。

Harness 禁止：

- 直接写代码；
- 直接跑实现验证来替 child 证明 completed；
- 修改 implementation artifact；
- stage 非当前 attempt 的 result；
- 在 child 仍运行时进入 verify。

## Verify child

Verify child 负责 build/unit/integration/review 等各自 owner contract。Verification 必须锚定当前 implementation checkpoint；如果 Helper 尚未提供 checkpoint，Harness block 或回到 implementation accept 后创建 checkpoint，不让 verify 自行猜 source revision。

Verification finding 的调度归 Harness Review Gate：

- 实现缺陷 -> proposed rerun `implement.code`；
- 测试命令/测试资产问题 -> proposed rerun 对应 verify child；
- PRD 验收不清 -> proposed rerun plan-owned PRD；
- 环境不可用 -> block。

Verify child 不写调度建议，不展示 Review Gate 菜单。

## Barrier

每个 child phase 都必须 barrier：

1. dispatch all sibling children；
2. wait；
3. stage each ChildResult serially；
4. only after all required children are staged, finalize；
5. then Review Gate。

一个早回 child 的 completed 结果不代表 phase completed。silence is not failure；wait 超时只说明继续等待或检查进程，不伪造 `unable_to_complete`。

## Review Gate

Implement 和 verify finalize 后都进入 Review Gate。

- `human_review`：展示 digest、artifact summary、需要重跑的节点和 reason，等待用户。
- `accept`：继续 transition。
- mismatch/stale 按 Helper code 恢复。
- terminal verify 完成后仍需人类确认，再进入 terminal cleanup。

Review Gate 不从 child artifact 正文重新做判断；需要更多证据就 rerun child。

## Checkpoint

Implement Review Gate 接受后创建或激活 checkpoint。Verify dispatch 使用 checkpoint 作为 source revision anchor。新的 implement rerun 创建新 checkpoint，并使旧 verify 结果失效。

Checkpoint 不包含：

- `.ai-workflow/**`；
- workflow artifact/result/prompt/log/report；
- Git metadata；
- adapter report paths；
- protected paths；
- 无关 dirty changes。

如果 checkpoint scope 与用户已有 dirty changes 重叠，fail closed 并 block，等待人类处理。

## Blocked and terminal

Blocked 不自动恢复。Harness 只展示继续/终止菜单，并根据用户选择调用 resume/abort。

Terminal 后执行 summary、reflection、knowledge governance 和 Git handoff。terminal Git handoff 需要人类明确选择，不自动 commit、branch、push 或 MR。

## Anti-patterns

| Anti-pattern | Correct action |
| --- | --- |
| 把 PRD 摘要复制进 child query | 只传 prompt_file |
| plan 结束后手写 ChildResult | 调 workflow-owned staging 入口 |
| verify 未拿到 checkpoint 也运行 | block 或回 implementation checkpoint |
| 用户说“这个实现可以了”，跳过 verify | 仍 dispatch verify child |
| 一个 verify child 通过就 terminal | 等全部 verify barrier + Review Gate |
