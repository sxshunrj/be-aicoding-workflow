import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Sequence

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    config = commands.add_parser("config")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    show = config_commands.add_parser("show")
    show.add_argument("--repo", type=Path, required=True)
    return parser


def _config_data(config: RepositoryConfig) -> dict[str, object]:
    data = asdict(config)
    data["wiki_path"] = str(config.wiki_path)
    return data


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        config = RepositoryConfig.load(args.repo)
        envelope: dict[str, object] = {"ok": True, "data": _config_data(config)}
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
