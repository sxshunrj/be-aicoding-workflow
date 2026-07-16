# Wave 1 Traceability

本文件只记录本地离线证据。真实 Codex/Claude Code trial 证据必须由 `docs/wave-1-trial.md` 的 evidence template 补充后才能标记为通过。

## Local Evidence

| Requirement | Evidence |
| --- | --- |
| Wave 1 Skills 可安装 | `ai-workflow install --source-root "$PWD/skills" --client all --scope user` 在 isolated HOME 中安装 6 个 Skill 到 `.agents/skills` 与 `.claude/skills`。 |
| doctor 能诊断安装、CLI、repo config、Wiki | `ai-workflow doctor --source-root "$PWD/skills" --repo "$PWD/examples/language-neutral" --client all` 在 isolated HOME 中无 failed checks。 |
| language-neutral profile 使用 schema v2 | `examples/language-neutral/.ai-workflow.yaml` 声明 `schema_version: 2`、`unit_test` 命令与 `disabled_nodes: [verify.integration_test]`。 |
| 四阶段本地流程可完成 | `tests/e2e/test_skill_first_wave1.py` 覆盖 init、spec、plan barrier、implement、verify、terminal completion。 |
| 新会话恢复只依赖持久化状态 | E2E 在 phase 间创建新的 `WorkflowService` 实例并继续 run。 |
| terminal reflection 有证据包和提交 gate | E2E 调用 `reflection_packet` 与 `submit_reflection`，并提交 decision/proposal。 |
| governance 使用 digest-protected promote | E2E 调用 `review_candidate` 后用 candidate digest promote。 |
| 后续 run 可检索 promoted knowledge | E2E 新 run 的 spec knowledge packet 包含 promoted knowledge ID。 |
| fake Agent 不写 workflow state 或 approved Wiki | `tests/e2e/fake_agent.py` CLI 只写 dispatch packet 授权 artifact 和 result path；E2E 检查无临时 workflow state/approved Wiki 写入残留。 |

## Commands

```bash
python -m pytest -q
python -m compileall -q src tests/e2e/fake_agent.py skills/ai-workflow-init/scripts/install.py
ai-workflow wiki lint --wiki wiki
git diff --check
```

## Real-Client Status

- Codex: pending user trial.
- Claude Code: pending, same protocol after Codex evidence.
- Wave 2: do not start until real-client feedback is recorded.
