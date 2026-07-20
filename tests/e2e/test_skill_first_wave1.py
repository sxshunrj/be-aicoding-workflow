from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys

from ai_workflow.cli import main
from ai_workflow.config import RepositoryConfig
from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService


def _copy_project(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "examples" / "language-neutral"
    target = tmp_path / "language-neutral"
    shutil.copytree(source, target)
    wiki = RepositoryConfig.load(target).wiki_path
    if wiki.exists():
        shutil.rmtree(wiki)
    for name in ("approved", "candidates", "archive"):
        (wiki / name).mkdir(parents=True, exist_ok=True)
    (wiki / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure, diagnostic, workflow]\n"
        "phases: [spec, plan, implement, verify]\n",
        encoding="utf-8",
    )
    _skill_dir(target)
    (target / "src").mkdir(exist_ok=True)
    (target / "src" / "app.py").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "E2E User"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.email", "e2e@example.com"], cwd=target, check=True)
    subprocess.run(["git", "add", "."], cwd=target, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=target, check=True, capture_output=True)
    return target


def _skill_dir(repo: Path) -> Path:
    contracts = repo / ".test-skill" / "references" / "agents"
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


def _service(repo: Path) -> WorkflowService:
    return WorkflowService(repo, id_factory=lambda: "abcdef")


def _stage_with_fake_agent(repo: Path, prompt_file: str, result_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("fake_agent.py")),
            "--prompt-file",
            prompt_file,
            "--result",
            str(result_path),
        ],
        check=True,
        cwd=repo,
    )


def _run_child(repo: Path, item: dict[str, object], result_dir: Path) -> Path:
    packet_file = str(item["packet_file"])
    packet = DispatchPacket.load(packet_file)
    result_path = result_dir / f"{packet.attempt_id}-{packet.child}.json"
    assert isinstance(item["prompt_file"], str)
    _stage_with_fake_agent(repo, item["prompt_file"], result_path)
    return result_path


def _review_transition(repo: Path, run_id: str) -> None:
    service = _service(repo)
    decision = service.review(run_id, {})
    if decision.decision == "human_review":
        _service(repo).record_review_acceptance(run_id, decision.digest)
    _service(repo).transition(run_id)


def _data(argv: list[str]) -> dict[str, object]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        status = main(argv)
    payload = json.loads(buffer.getvalue())
    assert status == 0, payload
    assert payload["ok"] is True
    return payload["data"]


def test_skill_first_wave_one_local_acceptance(tmp_path: Path) -> None:
    repo = _copy_project(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    run = _service(repo).init(repo, head, "Exercise Wave 1 locally", "full")
    run_id = run.run_id

    spec = _service(repo).begin(run_id, Phase.SPEC, _skill_dir(repo))
    spec_result = _run_child(repo, spec.dispatch_plan[0].to_dict(), tmp_path)
    _service(repo).stage(run_id, spec.attempt_id, "spec", spec_result)
    _service(repo).finalize(run_id, spec.attempt_id)
    _review_transition(repo, run_id)

    plan = _service(repo).begin(run_id, Phase.PLAN, _skill_dir(repo))
    first, second = plan.dispatch_plan
    first_result = _run_child(repo, first.to_dict(), tmp_path)
    _service(repo).stage(run_id, plan.attempt_id, first.child, first_result)
    try:
        _service(repo).finalize(run_id, plan.attempt_id)
    except Exception as error:
        assert "missing child result" in str(error)
    second_result = _run_child(repo, second.to_dict(), tmp_path)
    _service(repo).stage(run_id, plan.attempt_id, second.child, second_result)
    _service(repo).finalize(run_id, plan.attempt_id)
    _review_transition(repo, run_id)

    implement = _service(repo).begin(run_id, Phase.IMPLEMENT, _skill_dir(repo))
    implement_result = _run_child(repo, implement.dispatch_plan[0].to_dict(), tmp_path)
    _service(repo).stage(run_id, implement.attempt_id, "code", implement_result)
    _service(repo).finalize(run_id, implement.attempt_id)
    _review_transition(repo, run_id)

    verify = _service(repo).begin(run_id, Phase.VERIFY, _skill_dir(repo))
    assert [item.child for item in verify.dispatch_plan] == ["build", "unit_test", "code_review"]
    for item in verify.dispatch_plan:
        result = _run_child(repo, item.to_dict(), tmp_path)
        _service(repo).stage(run_id, verify.attempt_id, item.child, result)
    _service(repo).finalize(run_id, verify.attempt_id)
    _review_transition(repo, run_id)

    assert _service(repo).status(run_id).status == "completed"

    packet = _service(repo).reflection_packet(run_id)
    decision = tmp_path / "knowledge-reflection-decision.json"
    proposal = tmp_path / "knowledge-proposal.json"
    decision.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "evidence_digest": packet.evidence_digest,
                "outcome": "candidate",
                "reason": "The local Wave 1 sequence is reusable.",
            }
        ),
        encoding="utf-8",
    )
    proposal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Wave 1 local acceptance sequence",
                "type": "workflow",
                "summary": "Run the Wave 1 acceptance sequence through reflection and governance.",
                "body": "# Wave 1 local acceptance\n\nUse the local sequence before real-client trial.",
                "scope": {
                    "repos": ["language-neutral-example"],
                    "services": ["example"],
                    "paths": [],
                    "languages": [],
                    "phases": ["spec", "verify"],
                },
                "tags": ["wave-1", "acceptance"],
                "sources": [{"kind": "run", "ref": run_id}],
                "reuse_reason": "This is the standard local gate for future trials.",
                "confidence": "high",
                "possible_conflicts": [],
                "suggested_owners": ["ai-workflow"],
                "review_after": "2026-10-16",
            }
        ),
        encoding="utf-8",
    )
    _service(repo).submit_reflection(run_id, decision, proposal)

    wiki_root = RepositoryConfig.load(repo).wiki_path
    wiki = WikiService(WikiRepository(wiki_root))
    candidate = wiki.propose(proposal)
    review = wiki.review_candidate(candidate.id)
    promoted = wiki.promote(candidate.id, "alice", review["candidate"]["digest"])
    assert promoted.status.value == "approved"

    new_run = _service(repo).init(repo, head, "Use wave one knowledge", "full")
    next_spec = _service(repo).begin(new_run.run_id, Phase.SPEC, _skill_dir(repo))
    dispatch = DispatchPacket.load(next_spec.dispatch_plan[0].packet_file)
    packet_data = json.loads(Path(dispatch.knowledge_packet["path"]).read_text())
    assert promoted.id in packet_data["selected_ids"]

    assert not list((wiki_root / "approved").glob("*.tmp"))
    assert not (repo / ".ai-workflow" / "runs" / run_id / "state.yaml.tmp").exists()
