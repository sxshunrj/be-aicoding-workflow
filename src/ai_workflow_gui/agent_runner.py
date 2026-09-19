from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import os
import shlex
import signal
import subprocess
import threading
import time

from ai_workflow.errors import AppError

DEFAULT_AGENT_COMMAND = "claude -p {prompt} --dangerously-skip-permissions"
MAX_TAIL_LINES = 500


def build_prompt(profile: str, run_id: str, requirement: str) -> str:
    skill = "$ai-workflow-harness-grill" if profile == "grill" else "$ai-workflow-harness"
    return (
        f"加载 {skill} 技能，接管 run {run_id}，把它推进到终态或到达等待人工审批的 review gate 为止。"
        "先读取该 run 的持久化状态（state.yaml / events.jsonl）：若从未 begin（version 0 / events 为空），"
        "从初始阶段开始执行；否则按技能的 resume 流程继续。"
        "阶段执行、子任务派发、结果提交、阶段聚合与流转全部按技能指示通过 ai-workflow CLI 完成，"
        "不要向用户询问确认。"
        f"需求原文：{requirement}"
    )


@dataclass
class DriverJob:
    run_id: str
    command: str
    prompt: str
    started_at: float
    lines: deque[str]
    process: subprocess.Popen
    exit_code: int | None = None
    finished_at: float | None = None


class AgentDriver:
    """Per-run headless agent subprocess supervision (thread-based, loop-independent)."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self._jobs: dict[str, DriverJob] = {}
        self._lock = threading.Lock()
        self._log_dir = log_dir or (Path.home() / ".ai-workflow-gui" / "agent-logs")

    def status(self, run_id: str, tail: int = 200) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return {
                    "active": False,
                    "command": None,
                    "pid": None,
                    "exit_code": None,
                    "started_at": None,
                    "finished_at": None,
                    "tail": [],
                }
            return {
                "active": job.exit_code is None,
                "command": job.command,
                "pid": job.process.pid,
                "exit_code": job.exit_code,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "tail": list(job.lines)[-tail:],
            }

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(run_id)
            return job is not None and job.exit_code is None

    def start(
        self, *, run_id: str, repo_root: Path, template: str, prompt: str
    ) -> dict[str, object]:
        with self._lock:
            existing = self._jobs.get(run_id)
            if existing is not None and existing.exit_code is None:
                raise AppError("driver_busy", "该 run 的 agent 已在运行中")
            if "{prompt}" not in template:
                raise AppError(
                    "invalid_arguments", "agent 命令模板必须包含 {prompt} 占位符"
                )
            argv: list[str] = []
            for token in shlex.split(template):
                if "{prompt}" in token:
                    argv.append(token.replace("{prompt}", prompt))
                else:
                    argv.append(token)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            log_path = self._log_dir / f"{run_id}-{timestamp}.log"
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=str(repo_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    text=True,
                    errors="replace",
                )
            except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
                raise AppError(
                    "agent_spawn_failed",
                    f"无法启动 agent 命令「{argv[0]}」：{error}。请在装机与诊断页检查命令模板。",
                ) from error
            job = DriverJob(
                run_id=run_id,
                command=template,
                prompt=prompt,
                started_at=time.time(),
                lines=deque(maxlen=MAX_TAIL_LINES),
                process=process,
            )
            self._jobs[run_id] = job
        reader = threading.Thread(target=self._pump, args=(job, log_path), daemon=True)
        reader.start()
        return self.status(run_id)

    def stop(self, run_id: str) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None or job.exit_code is not None:
                raise AppError("invalid_arguments", "该 run 没有正在运行的 agent")
            try:
                os.killpg(job.process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    job.process.terminate()
                except ProcessLookupError:
                    pass
        return self.status(run_id)

    def _pump(self, job: DriverJob, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            assert job.process.stdout is not None
            for line in job.process.stdout:
                line = line.rstrip("\n")
                job.lines.append(line)
                log.write(line + "\n")
                log.flush()
        code = job.process.wait()
        job.exit_code = code
        job.finished_at = time.time()
