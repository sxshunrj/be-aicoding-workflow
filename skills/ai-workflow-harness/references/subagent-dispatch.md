# Subagent dispatch 与 phase barrier

## begin 后读取 dispatch plan

`workflow begin` 返回唯一 `attempt_id` 和有序 `dispatch_plan`。逐项处理：

- `action=dispatch` 或 `action=rerun`：使用该项的 `prompt_file` 创建 fresh Child。
- `action=already_staged`：不要重派；该 sibling 已在持久化 barrier 中。
- `prompt_file` 是 dispatch API 传给 Child 的唯一初始上下文。不要附加聊天摘要、brief、预期答案或其他 sibling 输出；Child 自己按文件内 packet 路径读取 contract/allowed inputs。
- 传入 Helper 返回的绝对 `prompt_file`。Child 以该路径中 `.ai-workflow/runs/` 之前的前缀为 repository root，解析 packet 内 repository-relative 的 allowed paths；不能依赖调用者当前 cwd。

## dispatch all before wait

同一 phase 必须 `dispatch all sibling children before waiting`。先创建每个需要运行的 sibling，再调用 wait；不得因为一个 Child 早回或用户催促而提前 finalize/review/transition。

`silence is not failure`：运行中、暂时无消息或单次 wait 超时都不等于 `unable_to_complete`。继续等待；只有 Child 明确返回当前 attempt 的合法 schema-v2 `ChildResult` 才算返回。

## ChildResult-only completion 与 stage

1. 接收 Child 原样 JSON；不要替它补字段、改 attempt 或把自然语言包装成成功。
2. 将返回的精确 JSON bytes 保存为 Harness-owned 临时 result 文件；不要放进或修改 `.ai-workflow/runs/**`。
3. 校验 `run_id/phase/child/attempt_id/execution_mode` 与 dispatch item 一致。
4. 每收到一个合法结果，就由 Harness 主 Agent串行调用 `workflow stage`。Child 不得调用 helper。
5. `unable_to_complete` 也是合法 ChildResult，照常 stage；不能把 tool error、异常退出或沉默替换成该状态。

## barrier 与 finalize

barrier = 当前 attempt 的每个有效 sibling 都已 stage。一个早回的结果只关闭自己的槽位。全部 sibling 未关闭时只 wait，不执行 `finalize`。

全部关闭后调用一次 `workflow finalize`。若返回 `barrier_incomplete`，从错误 details/随后 `status` 找到缺失 sibling，继续等待；不要伪造结果。finalize 只聚合并标记 node validity，不推进 phase。

## RED flags / 规避理由

| 说法 | 规则 |
| --- | --- |
| “用户认可了早回结果，先继续” | 用户认可不能跳过 sibling barrier。 |
| “我只是 Child，自己查 status/stage 更快” | 查询、取得 attempt、stage 都属于 Harness；Child 只返回结果。 |
| “stale 时改一下 attempt ID” | attempt 是 Helper 所有；Child 只修复/重产自己的 ChildResult。 |
| “一直没说话，按失败处理” | silence is not failure；继续 wait。 |
