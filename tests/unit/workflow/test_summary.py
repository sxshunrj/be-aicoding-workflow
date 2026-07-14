import json

import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def _run(tmp_path):
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123")
    service.begin(run.run_id, Phase.SPEC)
    return service, run.run_id


@pytest.mark.parametrize(
    "event",
    [
        [],
        {"type": 1, "version": 1, "data": {}},
        {"type": "phase_begun", "version": 1, "data": []},
        {"type": "phase_begun", "version": 1, "data": {}, "timestamp": "not-a-date"},
    ],
    ids=["non-object", "invalid-type", "invalid-data", "invalid-timestamp"],
)
def test_summary_translates_valid_json_event_corruption(tmp_path, event) -> None:
    service, run_id = _run(tmp_path)
    events = tmp_path / ".ai-workflow" / "runs" / run_id / "events.jsonl"
    events.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(AppError) as error:
        service.summary(run_id)

    assert error.value.code == "invalid_state"


@pytest.mark.parametrize("payload", [
    "[]",
    '{"schema_version":2}',
    ('{"schema_version":1,"run_id":1,"phase":"spec","attempt_id":"spec-1-abcdef",'
     '"source_revision":"abc123","knowledge_packet":{},"prior_artifacts":[],"rerun_reason":null}'),
])
def test_summary_rejects_malformed_phase_packet(tmp_path, payload) -> None:
    service, run_id = _run(tmp_path)
    packet = next((tmp_path / ".ai-workflow" / "runs" / run_id / "attempts").glob("*/phase-packet.json"))
    packet.write_text(payload, encoding="utf-8")

    with pytest.raises(AppError) as error:
        service.summary(run_id)

    assert error.value.code == "invalid_state"
