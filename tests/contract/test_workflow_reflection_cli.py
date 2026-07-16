import json
from pathlib import Path

from ai_workflow.cli import main
from tests.unit.workflow.test_reflection import _decision, _terminal_run


def _call(capsys, argv: list[str]) -> tuple[int, dict[str, object]]:
    status = main(argv)
    return status, json.loads(capsys.readouterr().out)


def test_workflow_reflection_cli_round_trip(tmp_path: Path, capsys) -> None:
    _, run_id = _terminal_run(tmp_path)

    status, reflected = _call(
        capsys,
        [
            "workflow",
            "reflect",
            "--repo",
            str(tmp_path),
            "--run-id",
            run_id,
        ],
    )

    assert status == 0
    assert reflected["ok"] is True
    packet_path = Path(reflected["data"]["path"])
    evidence_digest = reflected["data"]["evidence_digest"]
    assert packet_path.name == "reflection-packet.json"
    assert packet_path.is_file()

    decision = _decision(
        tmp_path / "decision.json",
        run_id,
        evidence_digest,
        "no_candidate",
        "Evidence is run-specific and not reusable.",
    )
    status, submitted = _call(
        capsys,
        [
            "workflow",
            "reflect-submit",
            "--repo",
            str(tmp_path),
            "--run-id",
            run_id,
            "--decision",
            str(decision),
        ],
    )

    assert status == 0
    assert submitted["data"]["outcome"] == "no_candidate"
    assert Path(submitted["data"]["decision_path"]).is_file()
