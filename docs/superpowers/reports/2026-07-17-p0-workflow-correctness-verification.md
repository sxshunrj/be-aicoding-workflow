# P0 Workflow Correctness Verification

## Summary

本地自动化验证已覆盖 P0 workflow correctness 批次的核心目标：profile-aware graph、earliest-node recovery、workflow-owned PRD、path authorization、temporary-index checkpoint、verification checkpoint anchor、checkpoint recovery、dirty overlap block，以及 Grill behavioral E2E。

本报告只记录本地自动化证据；未声明真实 Codex / Claude Code 客户端 reference parity。

## Verification Commands

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests/unit/test_config.py tests/unit/test_path_authorization.py -q` | PASS, 45 passed |
| `.venv/bin/python -m pytest tests/unit/workflow/test_graph.py tests/unit/workflow/test_machine.py tests/unit/workflow/test_checkpoint.py -q` | PASS, 42 passed |
| `.venv/bin/python -m pytest tests/unit/workflow/test_service.py tests/unit/workflow/test_review.py tests/unit/workflow/test_staging.py -q` | PASS, 143 passed |
| `.venv/bin/python -m pytest tests/contract/test_cli_envelope.py tests/contract/test_workflow_cli.py tests/contract/test_grill_harness_skill.py -q` | PASS, 20 passed |
| `.venv/bin/python -m pytest tests/e2e/test_grill_workflow.py tests/e2e/test_workflow_checkpoint.py -q` | PASS, 5 passed |
| `.venv/bin/python -m pytest -q` | PASS, 487 passed |
| `.venv/bin/ai-workflow wiki lint --wiki wiki` | PASS, `{"valid": true, "issues": []}` |
| `git diff --check` | PASS, no output |

Note: the original plan referenced `tests/contract/test_config_cli.py`; this repository currently uses `tests/contract/test_cli_envelope.py` for the config CLI envelope and `authorize-path` contract coverage.

## Traceability Matrix

| Design target | Evidence |
| --- | --- |
| full/grill graph and initial phase | `tests/unit/workflow/test_graph.py::test_builds_grill_profile_graph_with_prd_initial_phase`; `tests/unit/workflow/test_service.py::test_init_grill_profile_persists_plan_prd_graph`; full focused graph suite PASS |
| Unknown profile fail-closed before state creation | `tests/unit/workflow/test_service.py::test_init_rejects_unknown_profile_before_creating_run_directory`; `tests/contract/test_workflow_cli.py::test_cli_init_unknown_profile_uses_stable_json_error` |
| Earliest-node recovery | `tests/unit/workflow/test_machine.py::test_rerun_moves_back_and_resets_downstream_phase_nodes`; `tests/unit/workflow/test_machine.py::test_grill_plan_prd_rerun_clears_implement_and_verify`; `tests/unit/workflow/test_service.py::test_transition_drops_downstream_rerun_when_upstream_is_rerun` |
| Workflow-owned PRD import | `tests/unit/workflow/test_staging.py::test_begin_returns_workflow_owned_prd_target_without_dispatch_files`; `tests/unit/workflow/test_staging.py::test_stage_owned_prd_finalizes_with_synthesized_child_result`; `tests/contract/test_workflow_cli.py::test_cli_stage_owned_grill_prd_then_finalize` |
| Path authorization and protected descendants | `tests/unit/test_path_authorization.py`; `tests/contract/test_cli_envelope.py::test_cli_authorize_path_fails_closed_for_protected_paths`; focused path suite PASS |
| Helper-owned run artifact input | `tests/unit/test_path_authorization.py::test_helper_owned_run_artifact_is_allowed_as_input` |
| Temporary-index checkpoint creation | `tests/unit/workflow/test_checkpoint.py::test_checkpoint_uses_temporary_index_and_preserves_user_git_state` |
| HEAD, branch ref, and user index preservation | `tests/unit/workflow/test_checkpoint.py::test_checkpoint_uses_temporary_index_and_preserves_user_git_state`; `tests/e2e/test_workflow_checkpoint.py::test_dirty_overlap_blocks_without_moving_head_branch_or_index` |
| Dirty baseline ambiguity block | `tests/unit/workflow/test_checkpoint.py::test_checkpoint_rejects_dirty_overlap`; `tests/e2e/test_workflow_checkpoint.py::test_dirty_overlap_blocks_without_moving_head_branch_or_index` |
| Hidden ref immutability | `tests/unit/workflow/test_checkpoint.py::test_existing_checkpoint_ref_is_immutable` |
| Second checkpoint parent and previous pointer | `tests/unit/workflow/test_checkpoint.py::test_second_checkpoint_parent_is_previous_active`; `tests/e2e/test_workflow_checkpoint.py::test_implementation_rerun_creates_new_checkpoint_and_invalidates_all_verify` |
| Human Review Gate checkpoint activation | `tests/unit/workflow/test_service.py::test_verify_dispatch_uses_active_checkpoint_source_revision`; `tests/e2e/test_workflow_checkpoint.py::test_checkpoint_survives_new_process_and_anchors_verification` |
| Verification dispatch anchor | `tests/unit/workflow/test_service.py::test_verify_dispatch_uses_active_checkpoint_source_revision`; `tests/e2e/test_grill_workflow.py::test_grill_run_stages_owned_prd_and_completes_plan_implement_verify` |
| Verification rerun reuses checkpoint and siblings | `tests/e2e/test_workflow_checkpoint.py::test_verify_child_rerun_reuses_checkpoint_and_valid_siblings` |
| New-process recovery | `tests/e2e/test_workflow_checkpoint.py::test_checkpoint_survives_new_process_and_anchors_verification` |
| Grill happy path | `tests/e2e/test_grill_workflow.py::test_grill_run_stages_owned_prd_and_completes_plan_implement_verify` |
| Skill contract surface | `tests/contract/test_grill_harness_skill.py`; `tests/contract/test_skill_contract.py`; `tests/skill_scenarios/grill-harness.md` |

## Residual Scope

The following items remain explicitly outside this P0 local verification report:

- real Codex / Claude Code client trial evidence;
- CI provider collection;
- whitebox provider integration;
- external telemetry exporter;
- repository CI/release automation.
