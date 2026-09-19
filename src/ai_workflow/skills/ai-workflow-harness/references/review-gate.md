# Review Gate

Review Gate 位于 `finalize` 和 `transition` 之间；Helper 只校验提案，Harness 负责语义判断，人类拥有要求人工的决定。

Review Gate 的输入只来自最新持久化状态、phase aggregate、ChildResult summary/findings、用户反馈和 Harness 推导的 proposed rerun。不要打开 child artifact 正文来补做 child 判断；需要更多证据时 rerun 对应 child。

## 1. 形成 actionable node reasons

读取 phase aggregate、Child `findings`、报告证据和 `status.run_graph`。对需要 rerun 的每个 node 生成 `NODE=REASON`：

- NODE 必须是当前或更早的具体 node，如 `implement.code`，不是 phase 名。
- REASON 必须描述可执行修复与证据；禁止空白、`TODO`、`fix it` 或 Helper 的 placeholder。
- `unable_to_complete` 必须转换为有证据的 actionable reason，不能直接沿用 `child unable to complete; workflow must provide an actionable reason`。

没有 rerun 也必须调用 `workflow review`。

```text
ai-workflow workflow review --repo REPO --run-id RUN [--rerun NODE=REASON ...]
```

`--rerun` 是 proposed rerun，只在 review gate 中校验和固化；它不是 transition 参数。Review Gate accept 前不得调用 transition。

## 1.1 Rerun mapping

| evidence / feedback | proposed rerun node |
| --- | --- |
| 需求缺失、验收标准变更、scope 冲突 | `spec.spec` |
| 实现方案拆解、风险、文件边界、回滚策略问题 | `plan.solution` |
| 验证命令、测试范围、集测策略问题 | `plan.test_strategy` |
| 代码实现缺陷、编译错误、review 指向实现问题 | `implement.code` |
| build 命令或构建环境证据不足 | `verify.build` |
| 单测失败、单测缺口、单测质量问题 | `verify.unit_test` |
| 集测 case、mock、dataset、集成路径问题 | `verify.integration_test` |
| correctness/security/performance review 结论问题 | `verify.code_review` |

同一条用户反馈若跨多个 node，拆成多条 proposed rerun。不能用 phase 名代替 node；不能把 verification finding 直接写成 “rerun implementation” 除非 finding 证据明确指向 implementation defect。

reason 模板：

```text
<node>=因为 <evidence> 表明 <具体问题>，请在下一轮 <动作>，并用 <验证/证据> 证明。
```

例子：

```text
implement.code=因为 verify.unit_test 报告 UT-1 显示 None 输入会崩溃，请补充空值处理并更新对应单测证据。
verify.integration_test=因为用户指出缺少跨仓 mock 场景，请补充该场景的 case/mocking 证据并更新 integration-test-report。
```

## 2. wait / accept

- `decision=human_review`：向人类展示 phase、evidence、effective reruns 和 `digest`，等待“接受此 digest”或修改意见。沉默不是接受。
- `decision=accept`：只接受 Helper 已持久化的 auto-accept；Harness 不自行构造。
- verify 的 terminal review 永远是 human review。任何配置都不能跳过它。
- `auto_accept` 只适用于普通 phase gate；blocked、terminal completion、knowledge governance、Git handoff 不受影响。
- `human_review` 时必须停止等待用户，不得一边展示菜单一边 transition。

人类明确接受时记录同一 digest：

```text
ai-workflow workflow review-accept --repo REPO --run-id RUN --expected-digest DIGEST
```

展示模板：

```text
当前 phase 已 finalize，等待 Review Gate 决策。

Gate digest: <digest>
当前产物摘要:
- <artifact/result summary>

需要重跑的节点:
- <node>: <reason>

请选择:
1. 同意
2. 修改（请补充修改反馈）
3. 同意本轮，并将后续普通 phase Review Gate 改为自动同意

请直接回复 1 / 2 / 3。
```

没有 effective reruns 时，“需要重跑的节点”写 `none`。不要展示 valid/pending 未变化节点。

### 用户选择

- 选 1：`workflow review-accept --expected-digest <digest>`，然后 transition。
- 选 2：把反馈映射为 proposed rerun，再重新 `workflow review`；不要直接改 child artifact。
- 选 3：先按 Helper 支持的 review policy 入口切换后续普通 phase gate，再接受当前 digest。若当前 Helper 版本没有 policy 切换入口，说明暂不支持自动切换，不手改配置。
- 非 1/2/3：继续澄清。

## 3. mismatch / stale 恢复

两条路线互斥，先按 Helper 的 `error.code` 选择：

| error.code | exact route | 禁止动作 |
| --- | --- | --- |
| `review_gate_mismatch` | `workflow status -> workflow review` | 不进入 block |
| `stale_review_gate` | `workflow status -> workflow block -> human resume/abort` | 禁止继续 review |

- `review_gate_mismatch` 表示 caller 提供的 digest 不匹配。`status` 读取当前持久 gate 后重新 `review`，再向人类展示新 digest。
- `stale_review_gate` 表示 gate 与 state version 不再一致。`status` 确认后直接 `workflow block --reason "stale review gate cannot be refreshed"`；不得继续 review 循环。只在人类明确选择 `resume` 或 `abort` 后继续，旧 acceptance 永久作废。

## 4. transition

只有 gate 已持久化接受后才调用：

```text
ai-workflow workflow transition --repo REPO --run-id RUN
ai-workflow workflow status --repo REPO --run-id RUN
```

`transition` 只消费已接受 gate：无 rerun 时推进 phase，有 rerun 时回到最早 node 并使下游 pending。不得把 rerun 参数传给 transition。

transition 后必须立刻 `workflow status`。不要根据 transition 前的预期继续 begin 下一 phase。

## 5. Terminal completion gate

当 current phase 已是最终 verify 且无 effective reruns，仍必须 human_review。Harness 展示最终产物、verification evidence 和 remaining risks，等待人类明确接受 terminal completion。

terminal completion 接受后才进入 terminal cleanup。terminal cleanup 仍有自己的 human gates：reflection/governance/Git handoff，不因前一个 gate 接受而自动执行写操作。

## 6. RED flags

| 说法 | 正确规则 |
| --- | --- |
| “review_mode 是 auto_accept，所以 blocked 也 resume” | blocked 不受 auto_accept 影响。 |
| “用户已经口头说继续，跳过 review-accept” | 必须用 digest 调 `review-accept`。 |
| “transition 时顺便传 rerun” | proposed rerun 属于 `workflow review`。 |
| “打开 code-review-report 细看后我来判断是否 rerun” | Harness 不补做 child 判断；需要重审就 rerun child。 |
| “terminal gate 已接受，直接 commit/push” | Git handoff 是独立人类 gate。 |
