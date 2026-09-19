from __future__ import annotations

from pathlib import Path

from ai_workflow.errors import AppError

MAX_FILE_BYTES = 1_000_000
TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".yaml",
    ".yml",
    ".txt",
    ".log",
    ".py",
    ".sh",
}


def _run_dir(repo_root: Path, run_id: str) -> Path:
    from ai_workflow.workflow.service import RUN_ID_PATTERN

    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise AppError("invalid_run_id", "run ID has an invalid format")
    run_dir = (
        Path(repo_root).resolve() / ".ai-workflow" / "runs" / run_id
    )
    if not run_dir.is_dir():
        raise AppError("state_not_found", f"workflow run not found: {run_id}")
    return run_dir


def _resolve_inside(run_dir: Path, relative: str) -> Path:
    candidate = (run_dir / relative).resolve()
    if run_dir != candidate and run_dir not in candidate.parents:
        raise AppError("invalid_arguments", "path escapes the run directory")
    if candidate.is_symlink():
        raise AppError("invalid_arguments", "symlinks are not readable here")
    return candidate


def list_run_files(repo_root: Path, run_id: str) -> dict[str, object]:
    run_dir = _run_dir(repo_root, run_id)
    files: list[dict[str, object]] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_dir() or path.is_symlink():
            continue
        relative = path.relative_to(run_dir).as_posix()
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "suffix": path.suffix,
            }
        )
    return {"run_id": run_id, "files": files}


def read_run_file(repo_root: Path, run_id: str, relative: str) -> dict[str, object]:
    run_dir = _run_dir(repo_root, run_id)
    if not relative or relative.startswith("/"):
        raise AppError("invalid_arguments", "relative path is required")
    path = _resolve_inside(run_dir, relative)
    if not path.is_file():
        raise AppError("file_not_found", f"file not found in run: {relative}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        return {
            "path": relative,
            "size": size,
            "truncated": True,
            "content": f"（文件 {size} 字节超过 {MAX_FILE_BYTES} 上限，请在编辑器中打开）",
        }
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_bytes()[:200_000].decode("utf-8", errors="replace")
    return {"path": relative, "size": size, "truncated": False, "content": content}
