from __future__ import annotations

import json
from pathlib import Path

import yaml

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import RunState

RUNS_SEGMENT = (".ai-workflow", "runs")


def list_runs(repo_root: Path) -> dict[str, object]:
    runs_root = Path(repo_root).resolve().joinpath(*RUNS_SEGMENT)
    runs: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    if not runs_root.is_dir():
        return {"runs": runs, "errors": errors}
    for state_path in sorted(runs_root.glob("RUN-*/state.yaml")):
        run_id = state_path.parent.name
        try:
            raw = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("state is not a mapping")
            runs.append(RunState.from_dict(raw).to_dict())
        except Exception as error:
            errors.append({"run_id": run_id, "error": str(error)})
    runs.sort(key=lambda run: str(run.get("run_id", "")), reverse=True)
    return {"runs": runs, "errors": errors}


def read_events(repo_root: Path, run_id: str, limit: int = 50) -> list[dict[str, object]]:
    from ai_workflow.workflow.service import RUN_ID_PATTERN

    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise AppError("invalid_run_id", "run ID has an invalid format")
    events_path = (
        Path(repo_root).resolve().joinpath(*RUNS_SEGMENT, run_id, "events.jsonl")
    )
    if not events_path.is_file():
        return []
    events: list[dict[str, object]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events
