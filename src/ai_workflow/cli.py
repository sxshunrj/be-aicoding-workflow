import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Sequence

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
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
    config = commands.add_parser("config")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    show = config_commands.add_parser("show")
    show.add_argument("--repo", type=Path, required=True)
    workflow = commands.add_parser("workflow")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    init = workflow_commands.add_parser("init")
    init.add_argument("--repo", type=Path, required=True)
    init.add_argument("--source-revision", required=True)
    init.add_argument("--requirement", required=True)
    init.add_argument("--profile", default="full")
    for name in ("status", "resume", "abort", "summary"):
        command = workflow_commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--run-id", required=True)
    begin = workflow_commands.add_parser("begin")
    begin.add_argument("--repo", type=Path, required=True)
    begin.add_argument("--run-id", required=True)
    begin.add_argument("--phase", type=Phase, choices=list(Phase), required=True)
    begin.add_argument("--skill-dir", type=Path, required=True)
    stage = workflow_commands.add_parser("stage")
    stage.add_argument("--repo", type=Path, required=True)
    stage.add_argument("--run-id", required=True)
    stage.add_argument("--attempt-id", required=True)
    stage.add_argument("--child", required=True)
    stage.add_argument("--result", type=Path, required=True)
    finalize = workflow_commands.add_parser("finalize")
    finalize.add_argument("--repo", type=Path, required=True)
    finalize.add_argument("--run-id", required=True)
    finalize.add_argument("--attempt-id", required=True)
    transition = workflow_commands.add_parser("transition")
    transition.add_argument("--repo", type=Path, required=True)
    transition.add_argument("--run-id", required=True)
    transition.add_argument("--accept", action="store_true")
    transition.add_argument("--rerun", action="append", default=[])
    block = workflow_commands.add_parser("block")
    block.add_argument("--repo", type=Path, required=True)
    block.add_argument("--run-id", required=True)
    block.add_argument("--reason", required=True)
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


def _reruns(values: list[str]) -> dict[Phase, str]:
    reruns: dict[Phase, str] = {}
    for value in values:
        if "=" not in value:
            raise AppError("invalid_arguments", "--rerun must use PHASE=REASON")
        name, reason = value.split("=", 1)
        try:
            phase = Phase(name)
        except ValueError as error:
            raise AppError("invalid_arguments", f"unknown rerun phase: {name}") from error
        if not reason.strip():
            raise AppError("invalid_arguments", "rerun reason must not be empty")
        if phase in reruns:
            raise AppError("invalid_arguments", f"duplicate rerun phase: {name}")
        reruns[phase] = reason
    return reruns


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "config":
            data: object = _config_data(RepositoryConfig.load(args.repo))
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
            elif args.workflow_command == "finalize":
                data = service.finalize(args.run_id, args.attempt_id).to_dict()
            elif args.workflow_command == "summary":
                data = service.summary(args.run_id).to_dict()
            elif args.workflow_command == "transition":
                reruns = _reruns(args.rerun)
                if args.accept == bool(reruns):
                    raise AppError(
                        "invalid_arguments",
                        "transition requires exactly one of --accept or --rerun",
                    )
                data = service.transition(args.run_id, args.accept, reruns).to_dict()
            elif args.workflow_command == "block":
                data = service.block(args.run_id, args.reason).to_dict()
            elif args.workflow_command == "resume":
                data = service.resume(args.run_id).to_dict()
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
