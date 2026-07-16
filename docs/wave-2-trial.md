# Wave 2 Real-Client Trial

本指南用于 Wave 2 reference-parity 的真实客户端验证。当前只完成本地 conformance，不能把仓库标记为 `reference-parity`，直到 Codex/Claude Code evidence 回填。

## Install

```bash
cd /Users/bytedance/ai-coding-workflow
source .venv/bin/activate
ai-workflow install --source-root "$PWD/skills" --client all --scope user
ai-workflow doctor --source-root "$PWD/skills" --repo "$PWD/examples/language-neutral" --client all
```

确认 `/skills` 能看到 11 个 Skill：

```text
AI Workflow Init
AI Workflow Harness
AI Workflow Harness Grill
AI Small TDD Change
AI Integration Test Checklists
AI Integration Test Generator
AI Integration Test V2
AI CI Failure Triage
AI Git Handoff
AI Knowledge Reflection
AI Knowledge Governance
```

## Grill Harness Trial

```text
使用 $ai-workflow-harness-grill，在 examples/language-neutral 上启动 PRD-driven plan/implement/verify workflow。一次只问一个问题，先产出 PRD artifact，再 child-backed implement/verify。
```

## Integration Checklist Trial

```text
使用 $ai-integration-test-checklists，基于 docs/wave-1-traceability.md 和最近 diff 生成 evidence-mapped integration-test checklist。
```

## Integration Generator Trial

```text
使用 $ai-integration-test-generator，根据 examples/language-neutral 的 repository adapter 和上一条 checklist，生成或更新 integration-test assets；如果 adapter 不足，请停止并列出缺失字段。
```

## Integration Test V2 Trial

```text
使用 $ai-integration-test-v2，执行并诊断 integration-test failure。不要把 expected output 改成 broken behavior。
```

## CI Failure Triage Trial

```text
使用 $ai-ci-failure-triage，收集一个失败 job 的 job URL、commit、stage、command、exit status 和 bounded logs，分类后路由到正确 Skill。
```

## Evidence Template

```text
client:
client_version:
repo_commit:
installed_skill_digests:
grill_run_id:
prd_artifact_path:
checklist_output_path:
generator_changed_files:
integration_v2_rerun_evidence:
ci_triage_failure_class:
ci_triage_route:
manual_interventions:
doctor_result:
notes:
```
