from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import pytest

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult, Finding
from ai_workflow.contracts.packets import DispatchPacket, ReflectionPacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def _config(repo: Path, *, knowledge_limit: int = 12000) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "review_mode: auto_accept\n"
        "knowledge:\n"
        "  max_entries: 8\n"
        f"  max_characters: {knowledge_limit}\n",
        encoding="utf-8",
    )


def _skill_dir(repo: Path) -> Path:
    contracts = repo / "skill" / "references" / "agents"
    contracts.mkdir(parents=True, exist_ok=True)
    for name in (
        "common-phase-contract.md",
        "spec-writer.md",
        "planner.md",
        "coder.md",
        "test-runner.md",
        "code-reviewer.md",
    ):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    return contracts.parents[1]


def _wiki(repo: Path) -> None:
    wiki = repo / "wiki"
    for name in ("approved", "candidates", "archive"):
        (wiki / name).mkdir(parents=True)
    (wiki / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure, diagnostic, workflow]\n"
        "phases: [spec, plan, implement, verify]\n",
        encoding="utf-8",
    )
    (wiki / "approved" / "KW-rule-demo-001.md").write_text(
        "---\n"
        "id: KW-rule-demo-001\n"
        "title: Demo rule\n"
        "type: rule\n"
        "status: approved\n"
        "summary: Demo implementation should cite reusable knowledge.\n"
        "scope:\n"
        "  repos: [demo]\n"
        "  services: []\n"
        "  paths: []\n"
        "  languages: []\n"
        "  phases: [spec]\n"
        "tags: [demo]\n"
        "owners: [team-demo]\n"
        "reviewers: [alice]\n"
        "created_at: 2026-07-01\n"
        "reviewed_at: 2026-07-02\n"
        "review_after: 2026-10-01\n"
        "sources:\n"
        "  - kind: human\n"
        "    ref: alice\n"
        "supersedes: []\n"
        "conflicts_with: []\n"
        "---\n"
        "# Demo rule\n\nCite this rule when the spec depends on demo knowledge.\n",
        encoding="utf-8",
    )


def _start_service(repo: Path) -> tuple[WorkflowService, str]:
    _config(repo)
    _wiki(repo)
    service = WorkflowService(
        repo,
        clock=lambda: datetime(2026, 7, 16, 12, 0, 0),
        id_factory=lambda: "abcdef",
    )
    run = service.init(repo, "abc123", "Ship a reflected workflow")
    return service, run.run_id


def _run_phase(
    service: WorkflowService,
    repo: Path,
    run_id: str,
    phase: Phase,
    *,
    cite: tuple[str, ...] = (),
    finding_detail: str | None = None,
) -> None:
    attempt = service.begin(run_id, phase, _skill_dir(repo))
    for item in attempt.dispatch_plan:
        assert item.packet_file is not None
        packet = DispatchPacket.load(item.packet_file)
        artifact = None
        findings = ()
        status = "completed"
        summary = f"{phase.value} {item.child} completed"
        artifact_path = repo / packet.allowed_output_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(f"# {phase.value} {item.child}\n", encoding="utf-8")
        artifact = ArtifactRef(
            packet.allowed_output_path,
            hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            2,
            phase,
            item.child,
            "abc123",
        )
        if finding_detail is not None and item.child == "code_review":
            findings = (Finding("verify-gap", "Verification gap", finding_detail),)
            summary = "verification recorded a bounded finding"
        result = ChildResult(
            run_id,
            phase,
            item.child,
            attempt.attempt_id,
            packet.execution_mode,
            status,
            summary,
            artifact,
            findings,
            cite if item.child == "spec" else (),
        )
        result_path = repo / f"{phase.value}-{item.child}.json"
        result.write(result_path)
        service.stage(run_id, attempt.attempt_id, item.child, result_path)
    service.finalize(run_id, attempt.attempt_id)


def _review_transition(service: WorkflowService, run_id: str) -> None:
    decision = service.review(run_id, {})
    if decision.decision == "human_review":
        service.record_review_acceptance(run_id, decision.digest)
    service.transition(run_id)


def _terminal_run(repo: Path) -> tuple[WorkflowService, str]:
    service, run_id = _start_service(repo)
    _run_phase(service, repo, run_id, Phase.SPEC, cite=("KW-rule-demo-001",))
    _review_transition(service, run_id)
    _run_phase(service, repo, run_id, Phase.PLAN)
    _review_transition(service, run_id)
    _run_phase(service, repo, run_id, Phase.IMPLEMENT)
    _review_transition(service, run_id)
    _run_phase(
        service,
        repo,
        run_id,
        Phase.VERIFY,
        finding_detail="x" * 5000,
    )
    _review_transition(service, run_id)
    assert service.status(run_id).status == "completed"
    return service, run_id


def _decision(path: Path, run_id: str, digest: str, outcome: str, reason: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "evidence_digest": digest,
                "outcome": outcome,
                "reason": reason,
            }
        ),
        encoding="utf-8",
    )
    return path


def _proposal(path: Path, run_id: str, *, kind: str = "workflow") -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Terminal reflection workflow",
                "type": kind,
                "summary": "Terminal reflection should preserve run evidence before proposing knowledge.",
                "body": "# Terminal reflection\n\nPreserve terminal evidence before proposal.",
                "scope": {
                    "repos": ["demo"],
                    "services": [],
                    "paths": [],
                    "languages": [],
                    "phases": ["verify"],
                },
                "tags": ["reflection"],
                "sources": [{"kind": "run", "ref": run_id}],
                "reuse_reason": "The workflow applies to future terminal runs.",
                "confidence": "medium",
                "possible_conflicts": [],
                "suggested_owners": ["team-demo"],
                "review_after": (datetime.now().date() + timedelta(days=30)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_reflection_packet_contains_terminal_evidence_and_digest(tmp_path: Path) -> None:
    service, run_id = _terminal_run(tmp_path)

    packet = service.reflection_packet(run_id)

    assert packet.run_id == run_id
    assert packet.status == "completed"
    assert packet.requirement == "Ship a reflected workflow"
    assert packet.source_revision == "abc123"
    assert packet.phase_results
    assert packet.transition_events
    assert packet.cited_knowledge_ids == ("KW-rule-demo-001",)
    packet_path = tmp_path / ".ai-workflow" / "runs" / run_id / "reflection-packet.json"
    assert ReflectionPacket.load(packet_path) == packet
    assert packet.evidence_digest == ReflectionPacket.compute_digest(packet.to_unsigned_dict())


def test_reflection_rejects_non_terminal_runs(tmp_path: Path) -> None:
    service, run_id = _start_service(tmp_path)

    with pytest.raises(AppError, match="terminal"):
        service.reflection_packet(run_id)


def test_reflection_packet_bounds_findings_by_knowledge_limit(tmp_path: Path) -> None:
    _config(tmp_path, knowledge_limit=2000)
    _wiki(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123", "Bound reflection evidence")
    run_id = run.run_id
    _run_phase(service, tmp_path, run_id, Phase.SPEC, cite=("KW-rule-demo-001",))
    _review_transition(service, run_id)
    _run_phase(service, tmp_path, run_id, Phase.PLAN)
    _review_transition(service, run_id)
    _run_phase(service, tmp_path, run_id, Phase.IMPLEMENT)
    _review_transition(service, run_id)
    _run_phase(service, tmp_path, run_id, Phase.VERIFY, finding_detail="y" * 5000)
    _review_transition(service, run_id)

    packet = service.reflection_packet(run_id)

    serialized = json.dumps(packet.to_dict(), sort_keys=True)
    assert len(serialized) < 6000
    assert "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy" not in serialized


def test_reflection_submit_accepts_no_candidate_decision(tmp_path: Path) -> None:
    service, run_id = _terminal_run(tmp_path)
    packet = service.reflection_packet(run_id)
    decision = _decision(
        tmp_path / "decision.json",
        run_id,
        packet.evidence_digest,
        "no_candidate",
        "Evidence is run-specific and not reusable.",
    )

    record = service.submit_reflection(run_id, decision)

    assert record["outcome"] == "no_candidate"
    accepted = tmp_path / ".ai-workflow" / "runs" / run_id / "reflection-decision.json"
    assert accepted.is_file()
    assert not (accepted.parent / "knowledge-proposal.json").exists()


def test_reflection_submit_accepts_candidate_with_current_run_source(tmp_path: Path) -> None:
    service, run_id = _terminal_run(tmp_path)
    packet = service.reflection_packet(run_id)
    decision = _decision(
        tmp_path / "decision.json",
        run_id,
        packet.evidence_digest,
        "candidate",
        "Run exposed reusable workflow guidance.",
    )
    proposal = _proposal(tmp_path / "proposal.json", run_id)

    record = service.submit_reflection(run_id, decision, proposal)

    assert record["outcome"] == "candidate"
    assert record["proposal_path"].endswith("knowledge-proposal.json")


@pytest.mark.parametrize(
    ("decision_update", "proposal", "match"),
    [
        ({"run_id": "RUN-20260716-120000-badbad"}, True, "run ID"),
        ({"evidence_digest": "b" * 64}, True, "evidence digest"),
        ({"outcome": "candidate"}, False, "proposal is required"),
        ({"outcome": "no_candidate"}, True, "proposal is only allowed"),
    ],
)
def test_reflection_submit_rejects_invalid_decision_or_proposal_shape(
    tmp_path: Path,
    decision_update: dict[str, object],
    proposal: bool,
    match: str,
) -> None:
    service, run_id = _terminal_run(tmp_path)
    packet = service.reflection_packet(run_id)
    decision_path = _decision(
        tmp_path / "decision.json",
        run_id,
        packet.evidence_digest,
        "candidate",
        "Run exposed reusable workflow guidance.",
    )
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload.update(decision_update)
    decision_path.write_text(json.dumps(payload), encoding="utf-8")
    proposal_path = _proposal(tmp_path / "proposal.json", run_id) if proposal else None

    with pytest.raises(AppError, match=match):
        service.submit_reflection(run_id, decision_path, proposal_path)


def test_reflection_submit_rejects_candidate_without_current_run_source(tmp_path: Path) -> None:
    service, run_id = _terminal_run(tmp_path)
    packet = service.reflection_packet(run_id)
    decision = _decision(
        tmp_path / "decision.json",
        run_id,
        packet.evidence_digest,
        "candidate",
        "Run exposed reusable workflow guidance.",
    )
    proposal = _proposal(tmp_path / "proposal.json", "RUN-20260716-120000-111111")

    with pytest.raises(AppError, match="current run source"):
        service.submit_reflection(run_id, decision, proposal)
