from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import os
import shlex
import signal
import subprocess
import threading
import time

from ai_workflow.errors import AppError

DEFAULT_AGENT_COMMAND = (
    "claude -p {prompt} --model {model} --dangerously-skip-permissions"
)
MAX_TAIL_LINES = 400
TAIL_READ_BYTES = 32_000


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def render_argv(template: str, prompt: str, model: str = "") -> list[str]:
    """模板 → argv。{model} 为空时安全移除 --model/-m 与 = 形式占位。"""
    argv: list[str] = []
    for token in shlex.split(template):
        if "{prompt}" in token:
            argv.append(token.replace("{prompt}", prompt))
            continue
        if "{model}" in token:
            if model:
                argv.append(token.replace("{model}", model))
            elif argv and argv[-1] in ("--model", "-m"):
                argv.pop()
            continue
        argv.append(token)
    return argv


def _process_lstart(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _pid_matches(pid: int, lstart: str) -> bool:
    """防 PID 复用误伤：比对进程启动时间指纹（秒级，复用撞指纹的概率可忽略）。"""
    if not lstart:
        return False
    current = _process_lstart(pid)
    return current is not None and current == lstart


def _tail_file(path: Path, max_lines: int = 200) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size == 0:
        return []
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, size - TAIL_READ_BYTES))
            data = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > TAIL_READ_BYTES and lines:
        lines = lines[1:]
    return lines[-max_lines:]


@dataclass
class DriverJob:
    run_id: str
    repo_id: str
    command: str
    prompt: str
    binary: str
    pid: int
    lstart: str
    started_at: float
    log_path: Path
    process: subprocess.Popen | None = None  # None = 重启后收养的孤儿进程
    adopted: bool = False
    exit_code: int | None = None
    finished_at: float | None = None

    def state(self) -> str:
        if self.exit_code is not None:
            return "exited"
        if self.process is None:
            return "running" if _pid_alive(self.pid) else "unknown"
        code = self.process.poll()
        if code is not None:
            self.exit_code = code
            self.finished_at = time.time()
            return "exited"
        return "running"


class AgentDriver:
    """Per-run headless agent supervision.

    stdout 直写日志文件（不经管道）：GUI 重启后 agent 存活且日志完整，
    通过 job 文件收养存活进程继续监督与停止。
    """

    def __init__(self, log_dir: Path | None = None) -> None:
        self._log_dir = log_dir or (Path.home() / ".ai-workflow-gui" / "agent-logs")
        self._jobs: dict[str, DriverJob] = {}
        self._lock = threading.Lock()
        self._recover()

    # ---- 持久化 ----

    def _job_file(self, run_id: str) -> Path:
        return self._log_dir / f"{run_id}.job.json"

    def _persist(self, job: DriverJob) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": job.run_id,
            "repo_id": job.repo_id,
            "pid": job.pid,
            "command": job.command,
            "prompt": job.prompt,
            "binary": job.binary,
            "lstart": job.lstart,
            "started_at": job.started_at,
            "log_path": str(job.log_path),
        }
        tmp = self._job_file(job.run_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._job_file(job.run_id))

    def _recover(self) -> None:
        if not self._log_dir.is_dir():
            return
        for job_file in self._log_dir.glob("*.job.json"):
            try:
                data = json.loads(job_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_id = data.get("run_id")
            pid = data.get("pid")
            binary = data.get("binary", "")
            if not isinstance(run_id, str) or not isinstance(pid, int):
                continue
            if run_id in self._jobs:
                continue
            lstart = str(data.get("lstart", ""))
            adopted = _pid_alive(pid) and _pid_matches(pid, lstart)
            job = DriverJob(
                run_id=run_id,
                repo_id=str(data.get("repo_id", "")),
                command=str(data.get("command", "")),
                prompt=str(data.get("prompt", "")),
                binary=binary,
                lstart=lstart,
                pid=pid,
                started_at=float(data.get("started_at", 0.0)),
                log_path=Path(str(data.get("log_path", ""))),
                process=None,
                adopted=True,
                exit_code=None,
                finished_at=None,
            )
            if not adopted:
                job.finished_at = None  # GUI 停机期间结束，退出码不可知
            self._jobs[run_id] = job

    # ---- 查询 ----

    def status(self, run_id: str, tail: int = 200) -> dict[str, object]:
        job = self._jobs.get(run_id)
        if job is None:
            return {
                "active": False,
                "state": "idle",
                "adopted": False,
                "command": None,
                "pid": None,
                "exit_code": None,
                "started_at": None,
                "finished_at": None,
                "tail": [],
            }
        state = job.state()
        if job.process is not None and job.exit_code is not None:
            pass
        return {
            "active": state == "running",
            "state": state,
            "adopted": job.adopted,
            "command": job.command,
            "pid": job.pid,
            "exit_code": job.exit_code,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "tail": _tail_file(job.log_path, tail),
        }

    def is_active(self, run_id: str) -> bool:
        job = self._jobs.get(run_id)
        return job is not None and job.state() == "running"

    # ---- 操作 ----

    def start(
        self,
        *,
        run_id: str,
        repo_id: str,
        repo_root: Path,
        template: str,
        prompt: str,
        model: str = "",
    ) -> dict[str, object]:
        if self.is_active(run_id):
            raise AppError("driver_busy", "该 run 的 agent 已在运行中")
        if "{prompt}" not in template:
            raise AppError(
                "invalid_arguments", "agent 命令模板必须包含 {prompt} 占位符"
            )
        argv = render_argv(template, prompt, model)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = self._log_dir / f"{run_id}-{timestamp}.log"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(repo_root),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
            raise AppError(
                "agent_spawn_failed",
                f"无法启动 agent 命令「{argv[0]}」：{error}。请在装机与诊断页检查命令模板。",
            ) from error
        finally:
            log_handle.close()
        job = DriverJob(
            run_id=run_id,
            repo_id=repo_id,
            command=template,
            prompt=prompt,
            binary=argv[0],
            pid=process.pid,
            lstart=_process_lstart(process.pid) or "",
            started_at=time.time(),
            log_path=log_path,
            process=process,
        )
        self._jobs[run_id] = job
        self._persist(job)
        threading.Thread(target=self._reap, args=(job,), daemon=True).start()
        return self.status(run_id)

    def _reap(self, job: DriverJob) -> None:
        code = job.process.wait()
        job.exit_code = code
        job.finished_at = time.time()

    def stop(self, run_id: str) -> dict[str, object]:
        job = self._jobs.get(run_id)
        if job is None or job.state() != "running":
            raise AppError("invalid_arguments", "该 run 没有正在运行的 agent")
        if job.adopted and not _pid_matches(job.pid, job.lstart):
            raise AppError("invalid_arguments", "进程身份校验失败，拒绝停止陌生 PID")
        try:
            os.killpg(job.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                if job.process is not None:
                    job.process.terminate()
                else:
                    os.kill(job.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return self.status(run_id)

    def auto_resume(
        self, *, run_id: str, repo_id: str, repo_root: Path, state, template: str, model: str = ""
    ) -> dict[str, object]:
        """gate 接受后的自动接力：可驱且空闲才启动。"""
        if state.status in ("completed", "aborted"):
            return {"resumed": False, "reason": "terminal"}
        gate = state.artifacts.get("review_gate")
        if (
            isinstance(gate, dict)
            and gate.get("decision") == "human_review"
            and not gate.get("accepted_at")
        ):
            return {"resumed": False, "reason": "gate_pending"}
        if self.is_active(run_id):
            return {"resumed": False, "reason": "already_running"}
        prompt = build_prompt(state.profile, run_id, state.requirement)
        self.start(
            run_id=run_id,
            repo_id=repo_id,
            repo_root=repo_root,
            template=template,
            prompt=prompt,
            model=model,
        )
        return {"resumed": True}

    def schedule_resume(
        self,
        *,
        run_id: str,
        repo_id: str,
        repo_root: Path,
        template: str,
        model: str = "",
        get_state,
        timeout: float = 120.0,
        interval: float = 2.0,
        on_result=None,
    ) -> None:
        """接受 gate 时 agent 尚未退出：后台等它退出后自动接力（有界）。"""

        def watch() -> None:
            import logging

            log = logging.getLogger("ai_workflow_gui")
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    state = get_state()
                except AppError as error:
                    if on_result:
                        on_result({"resumed": False, "reason": error.message})
                    return
                if state.status in ("completed", "aborted"):
                    if on_result:
                        on_result({"resumed": False, "reason": "terminal"})
                    return
                gate = state.artifacts.get("review_gate")
                if (
                    isinstance(gate, dict)
                    and gate.get("decision") == "human_review"
                    and not gate.get("accepted_at")
                ):
                    if on_result:
                        on_result({"resumed": False, "reason": "gate_pending"})
                    return
                if self.is_active(run_id):
                    time.sleep(interval)
                    continue
                try:
                    self.start(
                        run_id=run_id,
                        repo_id=repo_id,
                        repo_root=repo_root,
                        template=template,
                        prompt=build_prompt(
                            state.profile, run_id, state.requirement
                        ),
                        model=model,
                    )
                    log.info("auto-resume started agent for %s", run_id)
                except AppError as error:
                    log.warning("auto-resume failed for %s: %s", run_id, error.message)
                    if on_result:
                        on_result({"resumed": False, "reason": error.message})
                    return
                if on_result:
                    on_result({"resumed": True})
                return
            if on_result:
                on_result({"resumed": False, "reason": "timeout"})

        threading.Thread(target=watch, daemon=True).start()
