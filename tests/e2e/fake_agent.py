from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from io import StringIO
import argparse
import json
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import subprocess

from ai_workflow.cli import main
from ai_workflow.config import RepositoryConfig
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult, Finding
from ai_workflow.contracts.packets import DispatchPacket


@dataclass(frozen=True, slots=True)
class ProjectTemplate:
    source: Path

    def copy_to(self, target: Path) -> Path:
        shutil.copytree(self.source, target)
        wiki_root = target.parent.parent / "wiki"
        if wiki_root.exists():
            shutil.rmtree(wiki_root)
        for name in ("approved", "candidates", "archive"):
            (wiki_root / name).mkdir(parents=True, exist_ok=True)
        (wiki_root / "taxonomy.yaml").write_text(
            "schema_version: 1\n"
            "types: [rule, decision, pattern, pitfall, procedure]\n"
            "phases: [spec, plan, implement, verify]\n",
            encoding="utf-8",
        )
        contracts = target / ".test-skill" / "references" / "agents"
        contracts.mkdir(parents=True)
        for name in (
            "common-phase-contract.md",
            "spec-writer.md",
            "planner.md",
            "coder.md",
            "test-runner.md",
            "code-reviewer.md",
        ):
            (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
        (target / "src").mkdir(exist_ok=True)
        (target / "src" / "app.py").write_text("original\n", encoding="utf-8")
        _git(target, "init")
        _git(target, "config", "user.name", "E2E User")
        _git(target, "config", "user.email", "e2e@example.com")
        _git(target, "add", ".")
        _git(target, "commit", "-m", "initial")
        return target


class CliDriver:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def workflow_init(
        self, *, source_revision: str | None = None, profile: str = "full"
    ) -> dict[str, object]:
        source_revision = source_revision or self.git_rev_parse("HEAD")
        return self._data(["workflow", "init", "--repo", str(self.project_root),
                           "--source-revision", source_revision, "--requirement",
                           "Exercise the full workflow lifecycle", "--profile", profile])

    def workflow_begin(self, run_id: str, phase: str) -> dict[str, object]:
        return self._data(["workflow", "begin", "--repo", str(self.project_root),
                           "--run-id", run_id, "--phase", phase, "--skill-dir",
                           str(self.project_root / ".test-skill")])

    def workflow_stage_owned(
        self,
        run_id: str,
        attempt_id: str,
        phase: str,
        child: str,
        artifact: Path,
        summary: str,
    ) -> dict[str, object]:
        return self._data([
            "workflow", "stage-owned", "--repo", str(self.project_root),
            "--run-id", run_id, "--attempt-id", attempt_id, "--phase", phase,
            "--child", child, "--artifact", str(artifact), "--summary", summary,
        ])

    def workflow_stage(self, run_id: str, result_path: Path) -> dict[str, object]:
        result = ChildResult.load(result_path)
        return self._data(["workflow", "stage", "--repo", str(self.project_root),
                           "--run-id", run_id, "--attempt-id", result.attempt_id,
                           "--child", result.child, "--result", str(result_path)])

    def workflow_finalize(self, run_id: str, attempt_id: str) -> dict[str, object]:
        return self._data(["workflow", "finalize", "--repo", str(self.project_root),
                           "--run-id", run_id, "--attempt-id", attempt_id])

    def workflow_review_transition(
        self, run_id: str, *, reruns: dict[str, str] | None = None
    ) -> dict[str, object]:
        argv = [
            "workflow",
            "review",
            "--repo",
            str(self.project_root),
            "--run-id",
            run_id,
        ]
        reruns = reruns or {}
        for node, reason in reruns.items():
            argv.extend(["--rerun", f"{node}={reason}"])
        decision = self._data(argv)
        if decision["decision"] == "human_review":
            self._data(
                [
                    "workflow",
                    "review-accept",
                    "--repo",
                    str(self.project_root),
                    "--run-id",
                    run_id,
                    "--expected-digest",
                    decision["digest"],
                ]
            )
        return self._data(
            [
                "workflow",
                "transition",
                "--repo",
                str(self.project_root),
                "--run-id",
                run_id,
            ]
        )

    def workflow_review(self, run_id: str, *, reruns: dict[str, str] | None = None) -> dict[str, object]:
        argv = [
            "workflow",
            "review",
            "--repo",
            str(self.project_root),
            "--run-id",
            run_id,
        ]
        for node, reason in (reruns or {}).items():
            argv.extend(["--rerun", f"{node}={reason}"])
        return self._data(argv)

    def workflow_review_accept_status(self, run_id: str, digest: str) -> tuple[int, dict[str, object]]:
        return self._raw_data(
            [
                "workflow",
                "review-accept",
                "--repo",
                str(self.project_root),
                "--run-id",
                run_id,
                "--expected-digest",
                digest,
            ]
        )

    def workflow_status(self, run_id: str) -> dict[str, object]:
        return self._data(["workflow", "status", "--repo", str(self.project_root),
                           "--run-id", run_id])

    def git_rev_parse(self, revision: str) -> str:
        return _git(self.project_root, "rev-parse", revision)

    def snapshot_git_state(self) -> dict[str, object]:
        head = self.git_rev_parse("HEAD")
        symbolic = _git(self.project_root, "symbolic-ref", "-q", "HEAD")
        branch_ref = self.git_rev_parse(symbolic)
        index = (self.project_root / ".git" / "index").read_bytes()
        return {
            "head": head,
            "symbolic": symbolic,
            "branch_ref": branch_ref,
            "index": index,
        }

    def load_packet(self, item: dict[str, object]) -> DispatchPacket:
        packet_file = item["packet_file"]
        assert isinstance(packet_file, str)
        return DispatchPacket.load(packet_file)

    def wiki_propose(self, proposal_path: Path) -> dict[str, object]:
        return self._data(["wiki", "propose", "--wiki", str(self._wiki_root()),
                           "--proposal", str(proposal_path)])

    def wiki_promote(self, entry_id: str, digest: str, *, reviewer: str) -> dict[str, object]:
        return self._data(["wiki", "promote", "--wiki", str(self._wiki_root()), "--id", entry_id,
                           "--reviewer", reviewer, "--expected-digest", digest])

    def wiki_search(self, *, text: str, repository: str) -> list[dict[str, object]]:
        return self._data(["wiki", "search", "--wiki", str(self._wiki_root()),
                           "--repository", repository, "--text", text])

    def _wiki_root(self) -> Path:
        return RepositoryConfig.load(self.project_root).wiki_path

    def _data(self, argv: list[str]) -> dict[str, object] | list[dict[str, object]]:
        status, payload = self._raw_data(argv)
        if not payload.get("ok", False):
            raise AssertionError(f"command failed: {payload}")
        data = payload["data"]
        if isinstance(data, list):
            return data
        return data

    def _raw_data(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        buffer = StringIO()
        with redirect_stdout(buffer):
            status = main(argv)
        payload = json.loads(buffer.getvalue())
        return status, payload


class FakeAgent:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run(self, packet_path: Path, finding: str | None = None) -> Path:
        packet = DispatchPacket.load(packet_path)
        result_dir = self.project_root / "child-results" / packet.attempt_id
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{packet.child}.json"
        artifact_path = self.project_root / packet.allowed_output_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if finding is None:
            if packet.phase.value == "implement" and packet.child == "code":
                (self.project_root / "src" / "app.py").write_text(
                    f"implemented {packet.attempt_id}\n", encoding="utf-8"
                )
            artifact_text = self._artifact_text(packet)
            result_status = "completed"
            summary = f"{packet.phase.value} phase completed."
            findings: tuple[Finding, ...] = ()
        else:
            artifact_text = self._artifact_text(packet, finding=finding)
            result_status = "unable_to_complete"
            summary = f"{packet.phase.value} phase found a gap."
            findings = (Finding(f"{packet.phase.value}-gap", "Missing retry branch", finding),)
        artifact = None
        if finding is None:
            artifact_path.write_text(artifact_text, encoding="utf-8")
            artifact = ArtifactRef(
                packet.allowed_output_path,
                self._digest(artifact_path),
                2,
                packet.phase,
                packet.child,
                packet.source_revision,
            )
        result = ChildResult(
            run_id=packet.run_id,
            phase=packet.phase,
            child=packet.child,
            attempt_id=packet.attempt_id,
            execution_mode=packet.execution_mode,
            status=result_status,
            summary=summary,
            artifact=artifact,
            findings=findings,
            knowledge_citations=(),
        )
        result.write(result_path)
        return result_path

    def propose_knowledge(self, run_id: str) -> Path:
        proposal_path = self.project_root / f"{run_id}-proposal.json"
        repository = self.project_root.name
        proposal = {
            "schema_version": 1,
            "title": "Retry branch recovery",
            "type": "rule",
            "summary": "The retry branch should be restored and covered by tests.",
            "body": "# Retry branch recovery\n\nKeep the retry branch in the implementation and protect it with tests.",
            "scope": {
                "repos": [repository],
                "services": ["example"],
                "paths": [],
                "languages": [],
                "phases": ["implement", "verify"],
            },
            "tags": ["retry", "branch"],
            "sources": [{"kind": "run", "ref": run_id}],
            "reuse_reason": "The run exposed a missing retry branch that should remain documented.",
            "confidence": "high",
            "possible_conflicts": [],
            "suggested_owners": ["example-team"],
            "review_after": (date.today() + timedelta(days=30)).isoformat(),
            "raw_logs": "bounded example log excerpt",
        }
        proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
        return proposal_path

    def _artifact_text(self, packet: DispatchPacket, *, finding: str | None = None) -> str:
        titles = {
            "spec": "Technical Spec",
            "plan": "Implementation Plan",
            "implement": "Implementation Report",
            "verify": "Verification Report",
        }
        title = f"{titles[packet.phase.value]}: {packet.child}"
        suffix = ""
        if finding is not None:
            suffix = f"\n\nFinding: {finding}\n"
        return (
            f"# {title}\n\nRun {packet.run_id} / {packet.attempt_id}\n"
            f"\nThis artifact is deterministic.{suffix}"
        )

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()


def _dispatch_from_prompt(path: Path) -> DispatchPacket:
    text = path.read_text(encoding="utf-8")
    marker = "```json\n"
    start = text.index(marker) + len(marker)
    end = text.index("\n```", start)
    return DispatchPacket.from_bytes(text[start:end].encode("utf-8"))


def _safe_repo_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise SystemExit(f"unsafe output path: {value}")
    return path


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    packet = _dispatch_from_prompt(args.prompt_file)
    relative = _safe_repo_path(packet.allowed_output_path)
    artifact_path = Path.cwd() / relative
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    if packet.phase.value == "implement" and packet.child == "code":
        source = Path.cwd() / "src" / "app.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"implemented {packet.attempt_id}\n", encoding="utf-8")
    artifact_path.write_text(
        f"# {packet.phase.value} {packet.child}\n\n"
        f"Run {packet.run_id} / {packet.attempt_id}\n",
        encoding="utf-8",
    )
    result = ChildResult(
        run_id=packet.run_id,
        phase=packet.phase,
        child=packet.child,
        attempt_id=packet.attempt_id,
        execution_mode=packet.execution_mode,
        status="completed",
        summary=f"{packet.phase.value} {packet.child} completed.",
        artifact=ArtifactRef(
            packet.allowed_output_path,
            sha256(artifact_path.read_bytes()).hexdigest(),
            2,
            packet.phase,
            packet.child,
            packet.source_revision,
        ),
        findings=(),
        knowledge_citations=(),
    )
    args.result.parent.mkdir(parents=True, exist_ok=True)
    result.write(args.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
