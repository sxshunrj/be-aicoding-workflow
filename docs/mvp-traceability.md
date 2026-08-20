# MVP Traceability

This document maps the ten MVP acceptance criteria from the design spec to concrete tests and release-verification commands.

## Requirement-to-evidence map

| Criterion | Command or test | Evidence |
| --- | --- | --- |
| 1. `workflow init` can attach any Git repository through `.ai-workflow.yaml`. | `tests/unit/test_config.py::test_loads_language_neutral_repository_config` and `tests/contract/test_workflow_cli.py::test_cli_init_begin_stage_finalize_lifecycle` | The config loader resolves the repository root and `workflow init` returns a persisted `run_id` envelope from the CLI. |
| 2. One task completes `spec -> plan -> implement -> verify` with validated artifacts. | `tests/e2e/test_mvp_acceptance.py::test_complete_run_recovery_rerun_and_knowledge_growth` | The end-to-end run reaches terminal completion with accepted artifacts for every phase. |
| 3. Every phase can receive a bounded knowledge packet derived from scope and keywords. | `tests/e2e/test_phase_knowledge_packet.py::test_begin_writes_child_packet_and_stage_validates_citations` and `tests/unit/wiki/test_packets.py::test_packet_is_bounded_and_digest_matches_canonical_content` | The packet is created from the wiki, remains bounded, and validates its digest before submission. |
| 4. Phase artifacts can cite knowledge IDs and the run records those citations. | `tests/e2e/test_phase_knowledge_packet.py::test_begin_writes_child_packet_and_stage_validates_citations` | The test proves a valid cited ID is accepted, an unknown cited ID is rejected, and `workflow summary` returns the recorded citation tuple. |
| 5. A completed run can generate a valid candidate knowledge entry. | `tests/e2e/test_mvp_acceptance.py::test_complete_run_recovery_rerun_and_knowledge_growth` | The end-to-end run finishes verify, calls `agent.propose_knowledge(run["run_id"])`, and creates a candidate proposal from the completed run. |
| 6. A human can promote the candidate and the promoted knowledge becomes searchable. | `tests/e2e/test_candidate_promotion.py::test_candidate_promotion_round_trip` and `tests/contract/test_wiki_search_cli.py::test_wiki_search_and_packet_cli` | Promotion uses digest protection, moves the entry into approved knowledge, and the approved entry is returned by search. |
| 7. A run can be resumed from persisted state in a new conversation. | `tests/e2e/test_workflow_recovery.py::test_service_recovers_staged_and_finalized_phase_from_disk` | A fresh service instance loads the same run from disk and continues from the persisted phase state. |
| 8. Verification can send work back to Implementation without restarting the run. | `tests/unit/workflow/test_service.py::test_failed_submission_can_be_followed_by_rerun_transition` and `tests/e2e/test_mvp_acceptance.py::test_complete_run_recovery_rerun_and_knowledge_growth` | A failed verify submission leaves the run runnable, and a rerun decision moves the current phase back to implement. |
| 9. Codex and Claude Code use the same Python core and protocol fixture. | `skills/ai-workflow-harness/SKILL.md`, `skills/ai-workflow-harness/references/helper-cli.md`, `tests/contract/test_skill_contract.py::test_each_phase_fixture_parses_as_child_result`, and the fresh-process status proof below | Both adapters use the same `ai-workflow` CLI core and protocol fixtures. |
| 10. The entire suite passes offline. | `python -m pytest -q`, `python -m compileall -q src tests/e2e/fake_agent.py`, `ai-workflow wiki lint --wiki wiki`, `git diff --check` | All commands completed successfully in this workspace with no network access. |

## Adapter verification record

The workspace does not provide separate Codex/Claude Code runtime binaries, so the verification here is recorded at the shared-core contract level with two distinct fresh-process proofs.

| Client | Version / contract reference | Result |
| --- | --- | --- |
| Codex | Client version: shared-core adapter contract `v54a400a`; `skills/ai-workflow-harness/SKILL.md` and `skills/ai-workflow-harness/references/helper-cli.md` (Skill renamed from `ai-workflow` to `ai-workflow-harness` in Wave 1) | A fresh process ran `workflow begin` followed by `workflow status` and observed the persisted run ID `RUN-20260715-140854-e8241f`, state version `1`, and current phase `spec`. |
| Claude Code | Client version: shared-core adapter contract `v54a400a`; `skills/ai-workflow-harness/SKILL.md` and `skills/ai-workflow-harness/references/helper-cli.md` (Skill renamed from `ai-workflow` to `ai-workflow-harness` in Wave 1) | A separate fresh process ran the same contract and observed the persisted run ID `RUN-20260715-140854-1c542e`, state version `1`, and current phase `spec`. |

## Release verification

- `python -m pytest -q` → `574 passed` (2026-08-20, includes Wave 1/Wave 2 and WeCom notify suites)
- `python -m compileall -q src tests/e2e/fake_agent.py` → passed
- `ai-workflow wiki lint --wiki wiki` → `{"ok": true, "data": {"valid": true, "issues": []}}`
- `git diff --check` → passed
