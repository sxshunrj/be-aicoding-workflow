import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Sequence

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


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
    for name in ("status", "resume", "abort", "summary"):
        command = workflow_commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--run-id", required=True)
    begin = workflow_commands.add_parser("begin")
    begin.add_argument("--repo", type=Path, required=True)
    begin.add_argument("--run-id", required=True)
    begin.add_argument("--phase", type=Phase, choices=list(Phase), required=True)
    submit = workflow_commands.add_parser("submit")
    submit.add_argument("--repo", type=Path, required=True)
    submit.add_argument("--run-id", required=True)
    submit.add_argument("--attempt-id", required=True)
    submit.add_argument("--result", type=Path, required=True)
    transition = workflow_commands.add_parser("transition")
    transition.add_argument("--repo", type=Path, required=True)
    transition.add_argument("--run-id", required=True)
    transition.add_argument("--accept", action="store_true")
    transition.add_argument("--rerun", action="append", default=[])
    block = workflow_commands.add_parser("block")
    block.add_argument("--repo", type=Path, required=True)
    block.add_argument("--run-id", required=True)
    block.add_argument("--reason", required=True)
    return parser


def _config_data(config: RepositoryConfig) -> dict[str, object]:
    data = asdict(config)
    data["wiki_path"] = str(config.wiki_path)
    return data


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
        else:
            service = WorkflowService(args.repo)
            if args.workflow_command == "init":
                data = service.init(args.repo, args.source_revision).to_dict()
            elif args.workflow_command == "status":
                data = service.status(args.run_id).to_dict()
            elif args.workflow_command == "begin":
                data = service.begin(args.run_id, args.phase).to_dict()
            elif args.workflow_command == "submit":
                data = service.submit(args.run_id, args.attempt_id, args.result).to_dict()
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
