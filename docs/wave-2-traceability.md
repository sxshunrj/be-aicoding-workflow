# Wave 2 Traceability

本文件记录 Wave 2 本地 reference-parity 证据。真实客户端 evidence 未回填前，不声明 `reference-parity` 已完成。

## Local Evidence

| Requirement | Evidence |
| --- | --- |
| Grill Harness completes PRD-driven three-phase model | `skills/ai-workflow-harness-grill/SKILL.md` 定义 `plan -> implement -> verify`，`tests/contract/test_grill_harness_skill.py` 验证 PRD loop 和 child-backed dispatch 边界。 |
| Integration checklist Skill produces evidence-mapped checklist | `skills/ai-integration-test-checklists/` 和 `tests/contract/test_integration_checklists_skill.py` 验证 Scope、Evidence Map、Checklist Items、Gap Analysis、Verification Commands。 |
| Integration generator composes through repository adapter | `RepositoryConfig` 新增 adapter 字段，`skills/ai-integration-test-generator/` 和 contract tests 验证 source/test/generated/report paths。 |
| Integration Test V2 converges without adapting expectations to broken code | `skills/ai-integration-test-v2/` 和 `tests/contract/test_integration_test_v2_skill.py` 验证 failure classes 与 prohibited shortcuts。 |
| CI triage collects facts and routes failures | `skills/ai-ci-failure-triage/` 和 `tests/contract/test_ci_failure_triage_skill.py` 验证 required facts 与 routing table。 |
| All eleven Skills install and are discoverable | `tests/contract/test_wave2_skill_suite.py` 和 `tests/unit/test_install.py::test_installs_full_wave2_skill_suite_from_repository`。 |
| Local conformance covers suite installation and routing docs | `tests/e2e/test_wave2_reference_parity.py`。 |

## Real-Client Status

- Codex: pending Wave 2 trial.
- Claude Code: pending same protocol.
- Release label remains `wave-1 trial` until evidence is supplied.
