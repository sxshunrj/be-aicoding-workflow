from pathlib import Path

from ai_workflow.doctor import run_doctor
from ai_workflow.install import install_skills


EXPECTED_WAVE2 = {
    "ai-workflow-harness-grill",
    "ai-integration-test-checklists",
    "ai-integration-test-generator",
    "ai-integration-test-v2",
    "ai-ci-failure-triage",
}


def test_wave2_reference_parity_local_suite_installs_and_documents_routes(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    source_root = repo / "skills"

    report = install_skills(
        source_root=source_root,
        home=tmp_path / "home",
        clients=("codex", "claude"),
        mode="link",
    )
    doctor = run_doctor(
        source_root=source_root,
        home=tmp_path / "home",
        repo=repo / "examples" / "language-neutral",
        clients=("codex", "claude"),
    )

    assert report.failed == ()
    assert doctor.failed == ()
    assert EXPECTED_WAVE2 <= {path.name for path in source_root.iterdir() if path.is_dir()}
    assert "plan -> implement -> verify" in (
        source_root / "ai-workflow-harness-grill" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "$ai-integration-test-v2" in (
        source_root / "ai-ci-failure-triage" / "references" / "failure-routing.md"
    ).read_text(encoding="utf-8")
