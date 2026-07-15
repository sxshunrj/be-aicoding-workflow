import json

import pytest

from ai_workflow.contracts.artifacts import ChildResult
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase


def _payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "run_id": "RUN-20260715-120000-abcdef",
        "phase": "spec",
        "child": "spec",
        "attempt_id": "spec-1-abcdef",
        "execution_mode": "fresh",
        "status": "completed",
        "summary": "Specification completed.",
        "artifact": {
            "path": "technical-spec.md",
            "sha256": "a" * 64,
            "schema_version": 2,
            "phase": "spec",
            "child": "spec",
            "source_revision": "abc123",
        },
        "findings": [],
        "knowledge_citations": [],
    }


def _parse(payload: dict[str, object]) -> ChildResult:
    return ChildResult.from_bytes(json.dumps(payload).encode())


def test_completed_result_parses_and_round_trips_exact_schema_v2_keys() -> None:
    payload = _payload()

    result = _parse(payload)

    assert result.run_id == "RUN-20260715-120000-abcdef"
    assert result.phase is Phase.SPEC
    assert result.child == "spec"
    assert result.attempt_id == "spec-1-abcdef"
    assert result.execution_mode == "fresh"
    assert result.artifact is not None
    assert result.artifact.child == "spec"
    assert result.to_dict() == payload


def test_legacy_result_rejects_schema_before_legacy_shape() -> None:
    payload = {
        "schema_version": 1,
        "status": "completed",
        "summary": "Legacy specification completed.",
        "artifact": {
            "path": "technical-spec.md",
            "sha256": "a" * 64,
            "schema_version": 1,
            "phase": "spec",
            "source_revision": "abc123",
        },
        "findings": [],
        "knowledge_citations": [],
    }

    with pytest.raises(AppError) as error:
        _parse(payload)
    assert error.value.code == "unsupported_schema_version"
    assert str(error.value) == "unsupported schema_version: 1"


def test_nested_legacy_artifact_rejects_schema_before_legacy_shape() -> None:
    payload = _payload()
    artifact = payload["artifact"]
    assert isinstance(artifact, dict)
    artifact["schema_version"] = 1
    del artifact["child"]

    with pytest.raises(AppError) as error:
        _parse(payload)
    assert error.value.code == "unsupported_schema_version"
    assert str(error.value) == "unsupported schema_version: 1"


@pytest.mark.parametrize("version", [None, "2", 2.0, True])
def test_result_requires_integer_schema_version(version: object) -> None:
    payload = _payload()
    payload["schema_version"] = version

    with pytest.raises(AppError) as error:
        _parse(payload)
    assert error.value.code == "unsupported_schema_version"
    assert str(error.value) == f"unsupported schema_version: {version!r}"


def test_result_requires_schema_version_before_exact_keys() -> None:
    payload = _payload()
    del payload["schema_version"]
    del payload["child"]

    with pytest.raises(AppError) as error:
        _parse(payload)
    assert error.value.code == "unsupported_schema_version"
    assert str(error.value) == "unsupported schema_version: None"


@pytest.mark.parametrize("key", ["run_id", "attempt_id", "execution_mode"])
def test_result_rejects_missing_keys(key: str) -> None:
    payload = _payload()
    del payload[key]

    with pytest.raises(ValueError, match="invalid child result keys"):
        _parse(payload)


def test_result_rejects_unknown_keys() -> None:
    payload = _payload()
    payload["unexpected"] = True

    with pytest.raises(ValueError, match="invalid child result keys"):
        _parse(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("phase", "plan"), ("child", "solution")],
)
def test_result_rejects_artifact_owner_mismatch(field: str, value: str) -> None:
    payload = _payload()
    artifact = payload["artifact"]
    assert isinstance(artifact, dict)
    artifact[field] = value

    with pytest.raises(ValueError, match="artifact owner does not match child result"):
        _parse(payload)


@pytest.mark.parametrize("mode", ["", "retry", "Fresh", None, 1])
def test_result_rejects_invalid_execution_mode(mode: object) -> None:
    payload = _payload()
    payload["execution_mode"] = mode

    with pytest.raises(ValueError, match="execution mode is invalid"):
        _parse(payload)


def test_completed_result_requires_artifact() -> None:
    payload = _payload()
    payload["artifact"] = None

    with pytest.raises(ValueError, match="completed child result requires an artifact"):
        _parse(payload)


def test_unable_to_complete_allows_nullable_artifact() -> None:
    payload = _payload()
    payload["status"] = "unable_to_complete"
    payload["artifact"] = None

    result = _parse(payload)

    assert result.status == "unable_to_complete"
    assert result.artifact is None


@pytest.mark.parametrize("citations", [[""], ["   "], ["wiki-1", "wiki-1"]])
def test_result_requires_non_blank_unique_citations(citations: list[str]) -> None:
    payload = _payload()
    payload["knowledge_citations"] = citations

    with pytest.raises(ValueError, match="unique non-empty string list"):
        _parse(payload)


def test_artifact_rejects_unknown_keys() -> None:
    payload = _payload()
    artifact = payload["artifact"]
    assert isinstance(artifact, dict)
    artifact["unexpected"] = True

    with pytest.raises(ValueError, match="invalid artifact keys"):
        _parse(payload)
