import hashlib
import json
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.workflow.models import Phase


def _config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")


def _skill_dir(root: Path) -> Path:
    path = root / "skill" / "references" / "agents"
    path.mkdir(parents=True)
    for name in ("common-phase-contract.md", "spec-writer.md"):
        (path / name).write_text(f"# {name}\n", encoding="utf-8")
    return path.parents[1]


def _call(capsys, argv: list[str]) -> tuple[int, dict[str, object]]:
    status = main(argv)
    return status, json.loads(capsys.readouterr().out)


def test_cli_init_begin_stage_finalize_lifecycle(tmp_path: Path, capsys) -> None:
    _config(tmp_path)
    skill_dir = _skill_dir(tmp_path)
    status, init = _call(
        capsys,
        [
            "workflow",
            "init",
            "--repo",
            str(tmp_path),
            "--source-revision",
            "abc123",
            "--requirement",
            "Specify the change",
        ],
    )
    assert status == 0
    assert init["data"]["profile"] == "full"
    run_id = init["data"]["run_id"]

    status, begin = _call(
        capsys,
        [
            "workflow",
            "begin",
            "--repo",
            str(tmp_path),
            "--run-id",
            run_id,
            "--phase",
            "spec",
            "--skill-dir",
            str(skill_dir),
        ],
    )
    assert status == 0
    attempt_id = begin["data"]["attempt_id"]
    assert begin["data"]["dispatch_plan"][0]["child"] == "spec"

    artifact_path = tmp_path / "artifacts" / "spec-spec.md"
    artifact_path.parent.mkdir()
    artifact_path.write_text("# Spec\n", encoding="utf-8")
    result_path = tmp_path / "spec-result.json"
    ChildResult(
        run_id=run_id,
        phase=Phase.SPEC,
        child="spec",
        attempt_id=attempt_id,
        execution_mode="fresh",
        status="completed",
        summary="specified",
        artifact=ArtifactRef(
            path="artifacts/spec-spec.md",
            sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            schema_version=2,
            phase=Phase.SPEC,
            child="spec",
            source_revision="abc123",
        ),
        findings=(),
    ).write(result_path)

    status, staged = _call(
        capsys,
        [
            "workflow",
            "stage",
            "--repo",
            str(tmp_path),
            "--run-id",
            run_id,
            "--attempt-id",
            attempt_id,
            "--child",
            "spec",
            "--result",
            str(result_path),
        ],
    )
    assert status == 0
    assert staged["data"]["child"] == "spec"

    status, finalized = _call(
        capsys,
        [
            "workflow",
            "finalize",
            "--repo",
            str(tmp_path),
            "--run-id",
            run_id,
            "--attempt-id",
            attempt_id,
        ],
    )
    assert status == 0
    assert finalized["data"]["status"] == "completed"

    status, shown = _call(
        capsys,
        ["workflow", "status", "--repo", str(tmp_path), "--run-id", run_id],
    )
    assert status == 0
    assert shown["data"]["current_phase"] == "spec"
    assert shown["data"]["run_graph"]["spec.spec"]["validity"] == "valid"


def test_cli_submit_command_is_removed(tmp_path: Path, capsys) -> None:
    status, payload = _call(
        capsys,
        ["workflow", "submit", "--repo", str(tmp_path), "--run-id", "x"],
    )

    assert status != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"


def test_cli_stage_failure_uses_json_error_and_nonzero_status(
    tmp_path: Path, capsys
) -> None:
    status, payload = _call(
        capsys,
        [
            "workflow",
            "stage",
            "--repo",
            str(tmp_path),
            "--run-id",
            "RUN-20260715-120000-abcdef",
            "--attempt-id",
            "spec-1-abcdef",
            "--child",
            "spec",
            "--result",
            str(tmp_path / "missing.json"),
        ],
    )

    assert status != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_result"
