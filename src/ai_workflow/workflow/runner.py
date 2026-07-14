from dataclasses import dataclass
from pathlib import Path
import subprocess
from time import monotonic

from ai_workflow.errors import AppError


@dataclass(frozen=True, slots=True)
class CommandEvidence:
    argv: tuple[str, ...]
    cwd: str
    exit_status: int
    duration_ms: int
    output: str
    output_truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {"argv": list(self.argv), "cwd": self.cwd, "exit_status": self.exit_status,
                "duration_ms": self.duration_ms, "output": self.output,
                "output_truncated": self.output_truncated}


class CommandRunner:
    def __init__(self, max_output_characters: int = 12000) -> None:
        self.max_output_characters = max_output_characters

    def run(self, argv: tuple[str, ...], cwd: Path, timeout_seconds: int) -> CommandEvidence:
        if not argv:
            raise AppError("invalid_command", "command argv must not be empty")
        started = monotonic()
        try:
            completed = subprocess.run(list(argv), shell=False, cwd=cwd, capture_output=True,
                                       text=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            raise AppError("command_timeout", f"command timed out after {timeout_seconds} seconds") from error
        output = completed.stdout + completed.stderr
        truncated = len(output) > self.max_output_characters
        return CommandEvidence(argv, str(cwd), completed.returncode,
                               int((monotonic() - started) * 1000),
                               output[:self.max_output_characters], truncated)
