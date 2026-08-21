# Subagent dispatch 与 phase barrier

本文件描述 child-backed phase 的执行方式。Harness 负责派发和收口；Child 负责自己的 artifact 和 ChildResult。workflow 不重写 prompt，不追加隐藏上下文，不把 sibling 输出塞给另一个 child。

## begin 后读取 dispatch plan

`workflow begin` 返回唯一 `attempt_id` 和有序 `dispatch_plan`。逐项处理：

- `action=dispatch` 或 `action=rerun`：使用该项的 `prompt_file` 创建 fresh Child。
- `action=already_staged`：不要重派；该 sibling 已在持久化 barrier 中。
- `prompt_file` 是 dispatch API 传给 Child 的唯一初始上下文。不要附加聊天摘要、brief、预期答案或其他 sibling 输出；Child 自己按文件内 packet 路径读取 contract/allowed inputs。
- 传入 Helper 返回的绝对 `prompt_file`。Child 以该路径中 `.ai-workflow/runs/` 之前的前缀为 repository root，解析 packet 内 repository-relative 的 allowed paths；不能依赖调用者当前 cwd。
- `execution_mode=fresh` 时只做本轮 owner 工作；`execution_mode=rerun` 时优先处理 packet reason；不存在“顺便修 sibling”。
- `prompt_file` 不可被 Harness 改写。若 prompt 或 dispatch packet evidence 损坏，按 recovery/status 处理，不手工补文件。

## Dispatch query shape

给 child 的消息保持极简：

```text
Read <prompt_file>, follow it exactly, and return only the schema-v2 ChildResult JSON.
```

不要在 query 中添加：

- “我认为你应该怎么做”；
- sibling 的原始报告正文；
- 用户最新反馈的二次解释；
- Harness 自己推断的 allowed paths；
- 任何与 packet 不一致的 attempt、reason、command。

如果用户反馈发生在 child 运行中，Harness 不打断 child 去改 prompt。等本 phase finalize 后映射为 rerun proposal，或在确实阻塞时 block。

## dispatch all before wait

同一 phase 必须 `dispatch all sibling children before waiting`。先创建每个需要运行的 sibling，再调用 wait；不得因为一个 Child 早回或用户催促而提前 finalize/review/transition。

`silence is not failure`：运行中、暂时无消息或单次 wait 超时都不等于 `unable_to_complete`。继续等待；只有 Child 明确返回当前 attempt 的合法 schema-v2 `ChildResult` 才算返回。

推荐顺序：

1. 从 dispatch plan 收集所有 `dispatch` / `rerun` item。
2. 全部派发。
3. 记录每个 child 的 prompt file 和 agent id（如有）。
4. 等待任一 child 完成。
5. 校验它返回的是当前 run/phase/child/attempt 的 ChildResult。
6. stage 该 child。
7. 回到等待，直到 barrier 满足。

并行只用于 sibling child 执行。Helper CLI 写命令仍串行：多个 child 几乎同时返回，也逐个 stage。

## ChildResult-only completion 与 stage

1. 接收 Child 原样 JSON；不要替它补字段、改 attempt 或把自然语言包装成成功。
2. 将返回的精确 JSON bytes 保存为 Harness-owned 临时 result 文件；不要放进或修改 `.ai-workflow/runs/**`。
3. 校验 `run_id/phase/child/attempt_id/execution_mode` 与 dispatch item 一致。
4. 每收到一个合法结果，就由 Harness 主 Agent串行调用 `workflow stage`。Child 不得调用 helper。
5. `unable_to_complete` 也是合法 ChildResult，照常 stage；不能把 tool error、异常退出或沉默替换成该状态。

stage 失败时按 code 路由：

| error.code | route |
| --- | --- |
| `attempt_owner_mismatch` | `status -> begin -> redispatch owner child` |
| `invalid_result` | 把错误返回 owner child 修复 ChildResult |
| `artifact_digest_mismatch` | owner child 修复 artifact/digest |
| `path_not_authorized` | fail closed，不扩大路径 |
| `result_conflict` | 保留冲突证据，报告人类。**进入人工等待前**，若已配置通知通道，调用 `ai-workflow wecom notify --repo REPO [--run-id RUN] --gate blocked --action "staged result 冲突，需人工处置"` 通知团队；失败仅写 warning，不影响主流程。 |

不要把 stage 失败转成 child failure；stage 是 Harness/Helper 校验失败，需要按持久状态恢复。

## barrier 与 finalize

barrier = 当前 attempt 的每个有效 sibling 都已 stage。一个早回的结果只关闭自己的槽位。全部 sibling 未关闭时只 wait，不执行 `finalize`。

全部关闭后调用一次 `workflow finalize`。若返回 `barrier_incomplete`，从错误 details/随后 `status` 找到缺失 sibling，继续等待；不要伪造结果。finalize 只聚合并标记 node validity，不推进 phase。

finalize 输出 phase aggregate 后，Harness 才能进入 Review Gate。不要在 finalize 前展示“整体通过/失败”。单个 child completed 只说明该 child 的 artifact 完成。

如果 phase aggregate 中有 `unable_to_complete` child，Helper 会把该 node 标为 rerun 或给出占位 reason。Harness 仍要在 Review Gate 前把 reason 改成 actionable：说明 blocker、证据和下一轮 child 应做什么。

## Rerun dispatch

rerun 不是“继续上一次聊天”。Helper 会生成新的 prompt file 或恢复当前 attempt 中未完成项。Child 只读取 packet reason；Harness 不把过去聊天粘贴过去。

rerun 的目的有三类：

- 修复该 child 自身 artifact/ChildResult；
- 验证 upstream 改动后的新 checkpoint；
- 回应用户 Review Gate 反馈。

rerun 不授权 child 接管主控：即使 reason 提到 stale、review、blocked，child 也不调用 workflow helper。

## Audit notes

Harness 最终汇报时记录每个 child 的：

- node/child；
- action：dispatch/rerun/reuse/already_staged；
- prompt_file；
- stage result；
- finalize aggregate 中的 status；
- 失败或 blocked 的 exact `error.code`。

不记录完整 prompt 或大型报告正文，避免把 child 上下文带回 Harness。

## RED flags / 规避理由

| 说法 | 规则 |
| --- | --- |
| “用户认可了早回结果，先继续” | 用户认可不能跳过 sibling barrier。 |
| “我只是 Child，自己查 status/stage 更快” | 查询、取得 attempt、stage 都属于 Harness；Child 只返回结果。 |
| “stale 时改一下 attempt ID” | attempt 是 Helper 所有；Child 只修复/重产自己的 ChildResult。 |
| “一直没说话，按失败处理” | silence is not failure；继续 wait。 |
| “我给 prompt 加一句用户反馈让它更懂” | dispatch 不追加隐藏上下文；反馈进入下一轮 rerun reason。 |
| “一个 child 已经 passed，phase 就 passed” | phase 通过由 barrier + finalize + review gate 决定。 |
