---
name: ai-workflow-harness-grill
description: Use when 用户显式要求 PRD-driven plan/implement/verify workflow，或要求 ai-workflow grill harness。
---

# AI Workflow Harness Grill

Grill 是交互式 PRD 驱动 workflow。它只用于用户显式要求，不替代 `$ai-workflow-harness`。

## Control loop

`plan -> implement -> verify`

- plan phase 由主 Agent 交互式拥有：一次只问一个问题，澄清目标、范围、acceptance criteria、non-goals 和 open questions。
- plan phase 写 run-local PRD artifact；PRD issue identifier 是内容标识，不是 dynamic run-graph node。
- `plan 不派 child`：plan 是 workflow-owned PRD，不创建 child prompt，不要求 ChildResult。
- plan 完成后由 Helper 的 `stage-owned` 或等价 workflow-owned staging 入口登记 PRD；不得直接构造 ChildResult。
- implement 和 verify 仍然 child-backed，遵守 prompt_file、ChildResult、stage、barrier、finalize、review gate。
- 不得直接编辑 `.ai-workflow/runs/**`；所有状态变化只通过 Helper CLI。
- 如果需求扩大到多条独立 workflow，先拆分 PRD，不要在一个 Grill run 里混合。
- 每个 phase 后仍经过 Review Gate；blocked 不自动恢复，terminal Git handoff 必须等待人类决定。

## When to use

使用 Grill 的信号：

- 用户明确要 PRD-driven workflow；
- 用户想先对齐需求、验收标准和 non-goals，再执行实现；
- 任务不需要完整 `spec -> plan -> implement -> verify` 的双计划阶段；
- 需要可恢复 run state、child-backed implement/verify、Review Gate 和 terminal handoff。

不要用于：

- 普通问答；
- 单文件小改且用户指定 `$ai-small-tdd-change`；
- 需要完整 spec/plan/test-strategy 拆分的高风险任务；
- 多个互不依赖的项目混在一次 run 中。

## Bootstrap

1. 读取当前 repository config 和 profile。
2. 若已有可恢复 run，先按 Helper status 展示候选并让用户选择恢复或新建。
3. 新建 run 时记录原始 requirement 和 source revision。
4. plan phase 从主 Agent 开始，不派 child。
5. 任何 state 变化都走 Helper CLI；禁止手写 `.ai-workflow/runs/**`。

## Exact command path

Grill 的最小命令顺序固定如下，主 Agent 不得跳步：

```text
workflow init --profile grill
workflow status
workflow begin --phase plan
read dispatch item: plan.prd, execution_kind=workflow_owned
write temporary PRD outside .ai-workflow/runs/**
workflow stage-owned
workflow finalize
workflow review
workflow review-accept when human_review
workflow transition
workflow status
workflow begin --phase implement
```

`workflow begin --phase plan` 返回的 `plan.prd` 是 workflow-owned item：

- `execution_kind=workflow_owned`
- `prompt_file=null`
- `packet_file=null`
- `allowed_artifact_path=<run_dir>/attempts/<attempt_id>/artifacts/prd.md`

主 Agent 写完 PRD 后必须调用：

```text
ai-workflow workflow stage-owned --repo REPO --run-id RUN --attempt-id ATTEMPT --phase plan --child prd --artifact FILE --summary TEXT
```

禁止直接构造 ChildResult，禁止编辑 state，禁止把 PRD 写进 `.ai-workflow/runs/**` 再当作 source 导入。

## Plan phase

Plan phase 的唯一目标是得到 workflow-owned PRD artifact。

流程：

1. 一次只问一个问题。
2. 收敛 requirement summary。
3. 明确 repository scope。
4. 明确 acceptance criteria。
5. 明确 non-goals。
6. 记录 resolved questions。
7. 记录 blocking questions。
8. 如果 blocking questions 仍影响实现或验收，继续提问，不进入 implement。
9. 写临时 PRD 到 run storage 外的普通路径。
10. 调 workflow-owned staging 入口登记 PRD。

PRD 必须可执行，不是会议纪要。它要让 implement child 不再依赖聊天记录。

## Implement phase

Implement 是 child-backed。Harness 只调用 Helper begin，取得 `prompt_file`，再派发 child。

Harness 不写代码、不跑测试、不修 lint。实现 child 负责：

- 读取 PRD artifact；
- 按 allowed inputs 和 owner contract 改 scoped code；
- 写 implementation report；
- 返回 schema-v2 ChildResult。

实现失败、环境阻塞或 PRD 不足时，child 返回 `unable_to_complete`；Harness stage/finalize/review 后把问题映射到 plan 或 implement rerun。

## Verify phase

Verify 是 child-backed。每个 verification child 只验证自己的范围。

Harness 不直接跑测试、不打开报告补做判断、不修 case。verification child 返回 build/unit/integration/review 报告和 ChildResult。

Verification 发现 implementation 缺陷时，Harness 在 Review Gate 中把 finding 映射到 `implement.code` rerun；如果只是测试资产问题，映射到对应 verify child rerun。

## Node recovery routing

所有反馈都映射到具体 node：

| 反馈 / 失败 | 路由 |
| --- | --- |
| PRD/acceptance 变化 | `plan.prd` |
| implementation 缺陷 | `implement.code` |
| build 验证缺陷 | `verify.build` |
| unit test 验证缺陷 | `verify.unit_test` |
| integration test 验证缺陷 | `verify.integration_test` |
| code review 验证缺陷 | `verify.code_review` |
| 环境、权限、工具失败 | `workflow block` |

单项验证缺陷只回对应 `verify.*`，不要重跑整个 verify phase。implementation 缺陷回 `implement.code` 后，下游 verify 节点由 Helper 清成 pending。

## Review Gate

每个 phase finalize 后进入 Review Gate：

- 有 proposed rerun：展示需要重跑的节点与 reason。
- 无 proposed rerun：展示产物摘要和 digest。
- `human_review` 时等待用户明确选择。
- 进入 `human_review` 时，`workflow review` 命令会自动推送 `gate=review` 的 WeCom 通知（Helper 机械保证，不依赖 skill 调用；phase 由 Helper 自动填写）。失败仅写 warning，不影响主流程。
- `accept` 时可继续 transition。
- terminal completion 仍需要人类确认，`workflow transition` / `workflow abort` 命令会自动推送 `gate=terminal` 的 WeCom 通知（Helper 机械保证，不依赖 skill 调用）。失败仅写 warning，不影响主流程。

人类反馈必须映射到 node reason，不能由 Harness 直接实现或验证。

## Blocked / terminal

Blocked 菜单只允许继续或终止。blocked 不自动恢复，不受 auto_accept 影响。`workflow block` 命令会自动推送 `gate=blocked` 的 WeCom 通知（Helper 机械保证，不依赖 skill 调用；phase 由 Helper 自动填写）；失败仅写 warning，不影响主流程。

Terminal 完成后执行：

1. summary；
2. reflection；
3. knowledge governance；
4. terminal Git handoff。

terminal Git handoff 不自动 commit、branch、push 或 MR。knowledge governance / Git handoff 的人工通知由 `$ai-knowledge-governance` / `$ai-git-handoff` 各自触发，无需重复调用。

## References

- [PRD loop](references/prd-loop.md)
- [Dispatch](references/dispatch.md)
