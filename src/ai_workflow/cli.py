import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Sequence

from ai_workflow.config import SCHEMA_VERSION, RepositoryConfig, migrate_repository_config
from ai_workflow.doctor import run_doctor
from ai_workflow.errors import AppError
from ai_workflow.install import install_skills
from ai_workflow.path_authorization import PathKind, RepositoryPathAuthorizer
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService
from ai_workflow.wiki.search import KnowledgeQuery, SearchLimits


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AppError("invalid_arguments", message)


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="ai-workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install")
    install.add_argument("--source-root", type=Path, required=True)
    install.add_argument("--client", choices=("codex", "claude", "all"), default="all")
    install.add_argument("--scope", choices=("user", "repo"), default="user")
    install.add_argument("--repo", type=Path)
    install_mode = install.add_mutually_exclusive_group()
    install_mode.add_argument("--copy", action="store_true")
    install_mode.add_argument("--link", action="store_true")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--source-root", type=Path, required=True)
    doctor.add_argument("--repo", type=Path)
    doctor.add_argument("--client", choices=("codex", "claude", "all"), default="all")
    run = commands.add_parser("run")
    run.add_argument("--repo", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--skill-dir", type=Path)
    run.add_argument(
        "--child-command",
        action="append",
        default=[],
        help="argv template for one child, e.g. 'codex exec {prompt_file} {result_file}'",
    )
    run.add_argument("--timeout-seconds", type=int, default=1800)
    run.add_argument("--max-steps", type=int, default=200)
    run.add_argument("--gate", choices=("refuse", "prompt"), default="refuse")
    run.add_argument("--progress", type=Path, help="write one NDJSON line per loop event")
    run.add_argument("--result-file", type=Path, help="final envelope path, with --detach")
    run.add_argument("--detach", action="store_true", help="drive the run in a background process")
    run_status = commands.add_parser("run-status")
    run_status.add_argument("--repo", type=Path, required=True)
    run_status.add_argument("--run-id", required=True)
    run_status.add_argument("--progress-limit", type=int, default=200)
    run.add_argument("--evidence", dest="evidence", action="store_true", default=True)
    run.add_argument("--no-evidence", dest="evidence", action="store_false")
    config = commands.add_parser("config")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    show = config_commands.add_parser("show")
    show.add_argument("--repo", type=Path, required=True)
    migrate = config_commands.add_parser("migrate")
    migrate.add_argument("--repo", type=Path, required=True)
    migrate.add_argument("--to", type=int, default=SCHEMA_VERSION)
    migrate.add_argument("--dry-run", action="store_true")
    authorize_path = config_commands.add_parser("authorize-path")
    authorize_path.add_argument("--repo", type=Path, required=True)
    authorize_path.add_argument(
        "--kind", choices=("input", "generated-test", "report"), required=True
    )
    authorize_path.add_argument("--path", required=True)
    workflow = commands.add_parser("workflow")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    init = workflow_commands.add_parser("init")
    init.add_argument("--repo", type=Path, required=True)
    init.add_argument("--source-revision", required=True)
    init.add_argument("--requirement", required=True)
    init.add_argument("--profile", default="full")
    for name in ("status", "abort", "summary", "reflect"):
        command = workflow_commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--run-id", required=True)
    resume = workflow_commands.add_parser("resume")
    resume.add_argument("--repo", type=Path, required=True)
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--rerun", action="append", default=[])
    begin = workflow_commands.add_parser("begin")
    begin.add_argument("--repo", type=Path, required=True)
    begin.add_argument("--run-id", required=True)
    begin.add_argument("--phase", type=Phase, choices=list(Phase), required=True)
    begin.add_argument("--skill-dir", type=Path)
    stage = workflow_commands.add_parser("stage")
    stage.add_argument("--repo", type=Path, required=True)
    stage.add_argument("--run-id", required=True)
    stage.add_argument("--attempt-id", required=True)
    stage.add_argument("--child", required=True)
    stage.add_argument("--result", type=Path, required=True)
    stage_owned = workflow_commands.add_parser("stage-owned")
    stage_owned.add_argument("--repo", type=Path, required=True)
    stage_owned.add_argument("--run-id", required=True)
    stage_owned.add_argument("--attempt-id", required=True)
    stage_owned.add_argument("--phase", type=Phase, choices=list(Phase), required=True)
    stage_owned.add_argument("--child", required=True)
    stage_owned.add_argument("--artifact", type=Path, required=True)
    stage_owned.add_argument("--summary", required=True)
    finalize = workflow_commands.add_parser("finalize")
    finalize.add_argument("--repo", type=Path, required=True)
    finalize.add_argument("--run-id", required=True)
    finalize.add_argument("--attempt-id", required=True)
    transition = workflow_commands.add_parser("transition")
    transition.add_argument("--repo", type=Path, required=True)
    transition.add_argument("--run-id", required=True)
    review = workflow_commands.add_parser("review")
    review.add_argument("--repo", type=Path, required=True)
    review.add_argument("--run-id", required=True)
    review.add_argument("--rerun", action="append", default=[])
    review_accept = workflow_commands.add_parser("review-accept")
    review_accept.add_argument("--repo", type=Path, required=True)
    review_accept.add_argument("--run-id", required=True)
    review_accept.add_argument("--expected-digest", required=True)
    block = workflow_commands.add_parser("block")
    block.add_argument("--repo", type=Path, required=True)
    block.add_argument("--run-id", required=True)
    block.add_argument("--reason", required=True)
    reflect_submit = workflow_commands.add_parser("reflect-submit")
    reflect_submit.add_argument("--repo", type=Path, required=True)
    reflect_submit.add_argument("--run-id", required=True)
    reflect_submit.add_argument("--decision", type=Path, required=True)
    reflect_submit.add_argument("--proposal", type=Path)
    wiki = commands.add_parser("wiki")
    wiki_commands = wiki.add_subparsers(dest="wiki_command", required=True)
    lint = wiki_commands.add_parser("lint")
    lint.add_argument("--wiki", type=Path, required=True)
    for name in ("search", "packet"):
        command = wiki_commands.add_parser(name)
        command.add_argument("--wiki", type=Path, required=True)
        command.add_argument("--repository")
        command.add_argument("--service", action="append", default=[])
        command.add_argument("--path", action="append", default=[])
        command.add_argument("--language", action="append", default=[])
        command.add_argument("--phase")
        command.add_argument("--type", action="append", default=[])
        command.add_argument("--tag", action="append", default=[])
        command.add_argument("--text", default="")
        command.add_argument("--max-entries", type=int, default=8)
        command.add_argument("--max-characters", type=int, default=12000)
        if name == "packet":
            command.add_argument("--output", type=Path, required=True)
    propose = wiki_commands.add_parser("propose")
    propose.add_argument("--wiki", type=Path, required=True)
    propose.add_argument("--proposal", type=Path, required=True)
    wiki_review = wiki_commands.add_parser("review")
    wiki_review.add_argument("--wiki", type=Path, required=True)
    wiki_review.add_argument("--id", required=True)
    wiki_review.add_argument("--max-related", type=int, default=8)
    for name in ("promote", "reject", "archive"):
        command = wiki_commands.add_parser(name)
        command.add_argument("--wiki", type=Path, required=True)
        command.add_argument("--id", required=True)
        command.add_argument("--reviewer", required=True)
        command.add_argument("--reason")
        command.add_argument("--expected-digest", required=True)
    return parser


def _config_data(config: RepositoryConfig) -> dict[str, object]:
    data = asdict(config)
    data["wiki_path"] = str(config.wiki_path)
    return data


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reruns(values: list[str]) -> dict[str, str]:
    reruns: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise AppError("invalid_arguments", "--rerun must use NODE=REASON")
        name, reason = value.split("=", 1)
        if not name.strip():
            raise AppError("invalid_arguments", "rerun node must not be empty")
        if not reason.strip():
            raise AppError("invalid_arguments", "rerun reason must not be empty")
        if name in reruns:
            raise AppError("invalid_arguments", f"duplicate rerun node: {name}")
        reruns[name] = reason
    return reruns


def _run_command(args: argparse.Namespace) -> dict[str, object]:
    """Drive one run to a terminal status or to a human decision point."""
    from ai_workflow.harness.evidence import EvidenceRecorder
    from ai_workflow.harness.gates import PromptHumanGate, RefusingGate
    from ai_workflow.harness.loop import RunLoop
    from ai_workflow.harness.runner import SubprocessChildRunner

    template = tuple(
        token for raw in args.child_command for token in shlex.split(raw)
    )
    if not template:
        raise AppError(
            "invalid_child_command",
            "--child-command is required; pass an argv template such as "
            "'codex exec {prompt_file} {result_file}'",
        )
    if args.detach and args.gate == "prompt":
        raise AppError(
            "invalid_arguments",
            "--detach cannot use --gate prompt: a detached run has no stdin",
        )
    service = WorkflowService(args.repo)
    if args.detach:
        return _start_detached(args, service)
    if args.result_file is not None:
        raise AppError(
            "invalid_arguments", "--result-file is only meaningful with --detach"
        )

    progress = args.progress
    stream = None
    if progress is not None:
        progress.parent.mkdir(parents=True, exist_ok=True)
        stream = progress.open("w", encoding="utf-8")

    def on_event(event) -> None:
        payload = json.dumps(event.data, ensure_ascii=False, sort_keys=True)
        print(f"[{event.kind}] {payload}", file=sys.stderr)
        if stream is not None:
            stream.write(
                json.dumps(
                    {
                        "time": datetime.now().isoformat(),
                        "kind": event.kind,
                        "data": event.data,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            stream.flush()

    runner = SubprocessChildRunner(
        template, repo_root=args.repo, timeout_seconds=args.timeout_seconds
    )
    gate = PromptHumanGate() if args.gate == "prompt" else RefusingGate()
    recorder = EvidenceRecorder() if args.evidence else None
    loop = RunLoop(
        service,
        runner,
        gate,
        skill_dir=args.skill_dir,
        evidence=recorder,
        max_steps=args.max_steps,
        on_event=on_event,
    )
    outcome = loop.run(args.run_id)
    if stream is not None:
        stream.write(
            json.dumps(
                {
                    "time": datetime.now().isoformat(),
                    "kind": "run_finished",
                    "data": {
                        "status": outcome.status,
                        "steps": outcome.steps,
                        "stopped_reason": outcome.stopped_reason,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        stream.close()
    return {
        "run_id": outcome.run_id,
        "status": outcome.status,
        "steps": outcome.steps,
        "stopped_reason": outcome.stopped_reason,
        "events": [
            {"kind": event.kind, "data": event.data} for event in outcome.events
        ],
    }


def _run_status_command(args: argparse.Namespace) -> dict[str, object]:
    """Read a run's persisted status plus its detached progress and result.

    The harness directory layout stays inside this module: an external driver
    polls one command instead of duplicating the on-disk paths.
    """
    service = WorkflowService(args.repo)
    state = service.status(args.run_id)
    harness = service.harness_directory(args.run_id)
    progress_path = harness / "run-progress.jsonl"
    result_path = harness / "run-result.json"
    events: list[object] = []
    if progress_path.is_file():
        lines = [
            line
            for line in progress_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for line in lines[-args.progress_limit :]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise AppError(
                    "invalid_state", "run progress line is malformed"
                ) from error
    result: object = None
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise AppError("invalid_state", "run result is malformed") from error
    return {
        "run_id": state.run_id,
        "status": state.status,
        "current_phase": state.current_phase,
        # Best effort: a detached driver writes the result when it stops, so an
        # absent result means the loop has not settled yet.
        "running": result is None
        and state.status not in {"completed", "aborted", "blocked"},
        "progress_path": str(progress_path),
        "result_path": str(result_path),
        "progress": events,
        "result": result,
    }


def _start_detached(
    args: argparse.Namespace, service: WorkflowService
) -> dict[str, object]:
    """Start the loop in a background process and return an observable handle.

    The detached process writes one NDJSON progress line per loop event and its
    final JSON envelope to the result file, so a driver (a DSH tool, a GUI, CI)
    can start a run and poll it without holding the process open.
    """
    harness = service.harness_directory(args.run_id)
    progress = args.progress or harness / "run-progress.jsonl"
    result_file = args.result_file or harness / "run-result.json"
    progress.parent.mkdir(parents=True, exist_ok=True)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    log_file = result_file.with_suffix(".log")
    argv = [
        sys.executable, "-m", "ai_workflow.cli", "run",
        "--repo", str(args.repo),
        "--run-id", args.run_id,
        "--progress", str(progress),
        "--timeout-seconds", str(args.timeout_seconds),
        "--max-steps", str(args.max_steps),
        "--gate", args.gate,
    ]
    for raw in args.child_command:
        argv.extend(["--child-command", raw])
    if args.skill_dir is not None:
        argv.extend(["--skill-dir", str(args.skill_dir)])
    if not args.evidence:
        argv.append("--no-evidence")
    env = dict(os.environ)
    # The child re-imports this package, so it needs the same import roots as the
    # parent: an editable install already provides them, a source checkout does not.
    env["PYTHONPATH"] = os.pathsep.join(entry for entry in sys.path if entry)
    with result_file.open("w", encoding="utf-8") as result_stream, log_file.open(
        "w", encoding="utf-8"
    ) as log_stream:
        process = subprocess.Popen(
            argv,
            stdout=result_stream,
            stderr=log_stream,
            stdin=subprocess.DEVNULL,
            cwd=str(args.repo),
            env=env,
            start_new_session=True,
        )
    return {
        "run_id": args.run_id,
        "status": "started",
        "pid": process.pid,
        "progress_path": str(progress),
        "result_path": str(result_file),
        "log_path": str(log_file),
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "install":
            clients = ("codex", "claude") if args.client == "all" else (args.client,)
            mode = "copy" if args.copy else "link" if args.link else "auto"
            report = install_skills(
                source_root=args.source_root,
                home=Path.home(),
                clients=clients,
                mode=mode,
                scope=args.scope,
                repo=args.repo,
            )
            data = report.to_dict()
            status = 1 if report.failed else 0
            print(json.dumps({"ok": not report.failed, "data": data}))
            return status
        elif args.command == "doctor":
            clients = ("codex", "claude") if args.client == "all" else (args.client,)
            report = run_doctor(
                source_root=args.source_root,
                home=Path.home(),
                repo=args.repo,
                clients=clients,
            )
            data = report.to_dict()
            status = 1 if report.failed else 0
            print(json.dumps({"ok": not report.failed, "data": data}))
            return status
        elif args.command == "run":
            data = _run_command(args)
        elif args.command == "run-status":
            data = _run_status_command(args)
        elif args.command == "config":
            if args.config_command == "migrate":
                # Migration must run before RepositoryConfig.load: a legacy file
                # has no schema_version and would be rejected by it.
                data: object = migrate_repository_config(
                    args.repo, to_version=args.to, dry_run=args.dry_run
                ).to_dict()
            else:
                config = RepositoryConfig.load(args.repo)
                if args.config_command == "show":
                    data = _config_data(config)
                else:
                    kind: PathKind = args.kind
                    authorized = RepositoryPathAuthorizer(
                        args.repo, config
                    ).authorize(kind, args.path)
                    data = {
                        "authorized": True,
                        "kind": kind,
                        "path": authorized,
                    }
        elif args.command == "wiki":
            service = WikiService(WikiRepository(args.wiki, validate_layout=False))
            if args.wiki_command == "lint":
                report = service.lint()
                print(json.dumps({"ok": True, "data": report.to_dict()}))
                return 0 if report.valid else 1
            elif args.wiki_command == "search":
                query = KnowledgeQuery(args.repository, tuple(args.service), tuple(args.path),
                                       tuple(args.language), args.phase, tuple(args.type),
                                       tuple(args.tag), args.text)
                limits = SearchLimits(args.max_entries, args.max_characters)
                data = [{"id": item.entry.id, "title": item.entry.title,
                         "score": item.score, "match_reasons": list(item.match_reasons),
                         "warnings": list(item.warnings)}
                        for item in service.search(query, limits)]
            elif args.wiki_command == "packet":
                query = KnowledgeQuery(args.repository, tuple(args.service), tuple(args.path),
                                       tuple(args.language), args.phase, tuple(args.type),
                                       tuple(args.tag), args.text)
                limits = SearchLimits(args.max_entries, args.max_characters)
                packet = service.create_packet(query, args.output, limits)
                data = {"path": str(args.output), "sha256": packet.digest,
                        "selected_ids": list(packet.selected_ids)}
            elif args.wiki_command == "propose":
                entry = service.propose(args.proposal)
                path = service.repository.root / "candidates" / f"{entry.id}.md"
                data = {"id": entry.id, "status": entry.status.value, "path": str(path),
                        "digest": _file_digest(path)}
            elif args.wiki_command == "review":
                data = service.review_candidate(args.id, args.max_related)
            elif args.wiki_command == "promote":
                entry = service.promote(args.id, args.reviewer, args.expected_digest)
                path = service.repository.root / "approved" / f"{entry.id}.md"
                data = {"id": entry.id, "status": entry.status.value, "path": str(path),
                        "digest": _file_digest(path)}
            elif args.wiki_command == "reject":
                if args.reason is None:
                    raise AppError("invalid_arguments", "--reason is required for reject")
                path = service.reject(args.id, args.reviewer, args.reason, args.expected_digest)
                data = {"id": args.id, "status": "archived", "path": str(path),
                        "digest": _file_digest(path)}
            else:
                if args.reason is None:
                    raise AppError("invalid_arguments", "--reason is required for archive")
                path = service.archive(args.id, args.reviewer, args.reason, args.expected_digest)
                data = {"id": args.id, "status": "archived", "path": str(path),
                        "digest": _file_digest(path)}
        else:
            service = WorkflowService(args.repo)
            if args.workflow_command == "init":
                data = service.init(
                    args.repo,
                    args.source_revision,
                    args.requirement,
                    args.profile,
                ).to_dict()
            elif args.workflow_command == "status":
                data = service.status(args.run_id).to_dict()
            elif args.workflow_command == "begin":
                data = service.begin(
                    args.run_id, args.phase, args.skill_dir
                ).to_dict()
            elif args.workflow_command == "stage":
                data = service.stage(
                    args.run_id, args.attempt_id, args.child, args.result
                ).to_dict()
            elif args.workflow_command == "stage-owned":
                data = service.stage_owned(
                    args.run_id,
                    args.attempt_id,
                    args.phase,
                    args.child,
                    args.artifact,
                    args.summary,
                ).to_dict()
            elif args.workflow_command == "finalize":
                data = service.finalize(args.run_id, args.attempt_id).to_dict()
            elif args.workflow_command == "summary":
                data = service.summary(args.run_id).to_dict()
            elif args.workflow_command == "reflect":
                packet = service.reflection_packet(args.run_id)
                data = {
                    "path": str(
                        service._store(args.run_id).reflection_packet_path()
                    ),
                    "evidence_digest": packet.evidence_digest,
                }
            elif args.workflow_command == "reflect-submit":
                data = service.submit_reflection(
                    args.run_id, args.decision, args.proposal
                )
            elif args.workflow_command == "review":
                data = service.review(
                    args.run_id, _reruns(args.rerun)
                ).to_dict()
            elif args.workflow_command == "review-accept":
                data = service.record_review_acceptance(
                    args.run_id, args.expected_digest
                ).to_dict()
            elif args.workflow_command == "transition":
                data = service.transition(args.run_id).to_dict()
            elif args.workflow_command == "block":
                data = service.block(args.run_id, args.reason).to_dict()
            elif args.workflow_command == "resume":
                data = service.resume(
                    args.run_id, _reruns(args.rerun)
                ).to_dict()
            else:
                data = service.abort(args.run_id).to_dict()
        envelope: dict[str, object] = {"ok": True, "data": data}
        status = 0
    except AppError as error:
        envelope = {
            "ok": False,
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        }
        status = error.exit_status
    print(json.dumps(envelope))
    return status


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover - entry point for detached runs
    entrypoint()
