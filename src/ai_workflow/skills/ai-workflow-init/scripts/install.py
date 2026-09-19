from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", choices=("codex", "claude", "all"), default="all")
    parser.add_argument("--scope", choices=("user", "repo"), default="user")
    parser.add_argument("--repo")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--copy", action="store_true")
    mode.add_argument("--link", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    skill_dir = Path(__file__).resolve().parents[1]
    source_root = skill_dir.parent
    executable = _ai_workflow_executable()
    install_argv = [
        executable,
        "install",
        "--source-root",
        str(source_root),
        "--client",
        args.client,
        "--scope",
        args.scope,
    ]
    if args.repo:
        install_argv.extend(["--repo", args.repo])
    if args.copy:
        install_argv.append("--copy")
    if args.link:
        install_argv.append("--link")
    install_result = run(install_argv)
    sys.stdout.write(install_result.stdout)
    if install_result.stderr:
        sys.stderr.write(install_result.stderr)
    if install_result.returncode != 0:
        return install_result.returncode

    doctor_argv = [
        executable,
        "doctor",
        "--source-root",
        str(source_root),
        "--client",
        args.client,
    ]
    if args.repo:
        doctor_argv.extend(["--repo", args.repo])
    doctor_result = run(doctor_argv)
    sys.stdout.write(doctor_result.stdout)
    if doctor_result.stderr:
        sys.stderr.write(doctor_result.stderr)
    return doctor_result.returncode


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, shell=False, text=True, capture_output=True)


def _ai_workflow_executable() -> str:
    for name in ("ai-workflow", "ai-workflow.exe"):
        candidate = Path(sys.executable).with_name(name)
        if candidate.is_file():
            return str(candidate)
    return "ai-workflow"


if __name__ == "__main__":
    raise SystemExit(main())
