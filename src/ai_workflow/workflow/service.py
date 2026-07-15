from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4
import hashlib
import json
import os

import yaml

from ai_workflow.config import RepositoryConfig
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.contracts.packets import PhasePacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.machine import StateMachine
from ai_workflow.workflow.models import NodeStatus, Phase, RunState
from ai_workflow.workflow.store import Event, StateStore
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.search import KnowledgeQuery, SearchLimits
from ai_workflow.wiki.service import WikiService


RUN_ID_PATTERN = re.compile(r"RUN-\d{8}-\d{6}-[0-9a-f]{6}")
ID_SUFFIX_PATTERN = re.compile(r"[0-9a-f]{6}")
ATTEMPT_ID_PATTERN = re.compile(r"(spec|plan|implement|verify)-([1-9]\d*)-[0-9a-f]{6}")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class _EmptyWiki:
    def paths(self) -> list[Path]:
        return []

    def read(self, path: Path):
        raise AssertionError("empty wiki has no readable paths")
BLOCKED_STATE_KEY = "_blocked_state"
RUN_STATUSES = {
    NodeStatus.PENDING.value,
    NodeStatus.RUNNING.value,
    NodeStatus.BLOCKED.value,
    "completed",
    "aborted",
}
NODE_STATUSES = {status.value for status in NodeStatus}
RESTORABLE_RUN_STATUSES = {NodeStatus.PENDING.value, NodeStatus.RUNNING.value}
RESTORABLE_NODE_STATUSES = {
    NodeStatus.PENDING.value,
    NodeStatus.RUNNING.value,
    NodeStatus.RERUN.value,
}
ACCEPTANCE_KEYS = {"run_id", "node", "phase", "attempt_id", "result_digest",
                   "artifact_digest", "accepted_version", "accepted_at", "status",
                   "summary", "artifact", "knowledge_citations"}


def _valid_acceptance_record(record: object, run_id: str, attempt_id: str,
                             source_revision: str) -> bool:
    if not isinstance(record, dict) or set(record) != ACCEPTANCE_KEYS:
        return False
    if (record.get("run_id") != run_id or record.get("attempt_id") != attempt_id
            or record.get("node") not in {phase.value for phase in Phase}
            or record.get("phase") != record.get("node")
            or not isinstance(record.get("result_digest"), str)
            or DIGEST_PATTERN.fullmatch(record["result_digest"]) is None
            or type(record.get("accepted_version")) is not int
            or record["accepted_version"] < 1
            or not isinstance(record.get("accepted_at"), str)
            or record.get("status") not in {"completed", "unable_to_complete"}
            or not isinstance(record.get("knowledge_citations"), list)
            or not all(isinstance(item, str) for item in record["knowledge_citations"])
            or not isinstance(record.get("summary"), str) or not record["summary"].strip()):
        return False
    try:
        datetime.fromisoformat(record["accepted_at"])
    except ValueError:
        return False
    artifact, artifact_digest = record.get("artifact"), record.get("artifact_digest")
    if artifact is None:
        return artifact_digest is None and record["status"] == "unable_to_complete"
    if not isinstance(artifact, dict):
        return False
    try:
        ref = ArtifactRef.from_dict(artifact)
    except (KeyError, TypeError, ValueError):
        return False
    return (artifact_digest == ref.sha256 and ref.phase.value == record["node"]
            and ref.source_revision == source_revision)


@dataclass(frozen=True, slots=True)
class Attempt:
    run_id: str
    phase: str
    number: int
    attempt_id: str
    packet_path: str

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id, "phase": self.phase, "number": self.number,
                "attempt_id": self.attempt_id, "packet_path": self.packet_path}


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    phase_durations_ms: dict[str, int]
    attempt_count: int
    rerun_count: int
    review_gate_decisions: tuple[dict[str, object], ...]
    cited_knowledge_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id, "phase_durations_ms": self.phase_durations_ms,
                "attempt_count": self.attempt_count, "rerun_count": self.rerun_count,
                "review_gate_decisions": list(self.review_gate_decisions),
                "cited_knowledge_ids": list(self.cited_knowledge_ids)}


class WorkflowService:
    def __init__(
        self,
        repo_root: Path | None = None,
        *,
        clock: Callable[[], datetime] = datetime.now,
        id_factory: Callable[[], str] = lambda: uuid4().hex[:6],
    ) -> None:
        self.repo_root = repo_root
        self.clock = clock
        self.id_factory = id_factory
        self.machine = StateMachine()

    def init(self, repo_root: Path, source_revision: str) -> RunState:
        RepositoryConfig.load(repo_root)
        if not source_revision.strip():
            raise AppError("invalid_source_revision", "source revision must not be empty")
        self.repo_root = repo_root
        suffix = str(self.id_factory())
        if ID_SUFFIX_PATTERN.fullmatch(suffix) is None:
            raise AppError(
                "invalid_run_id",
                "generated run ID suffix must be six lowercase hex characters",
            )
        run_id = f"RUN-{self.clock():%Y%m%d-%H%M%S}-{suffix}"
        state = RunState.new(run_id, source_revision)
        self._store(run_id).create(state)
        return state

    def status(self, run_id: str) -> RunState:
        return self._load(run_id)

    def begin(self, run_id: str, phase: Phase) -> Attempt:
        state = self._load(run_id)
        self._active(state)
        if state.current_phase != phase.value:
            raise AppError("invalid_transition", "cannot skip workflow phases")
        node = state.nodes[phase.value]
        if node.status not in {NodeStatus.PENDING.value, NodeStatus.RERUN.value}:
            raise AppError("invalid_transition", "phase cannot be begun in its current state")
        attempts = state.artifacts.setdefault("attempts", {})
        if not isinstance(attempts, dict):
            raise AppError("invalid_state", "attempt metadata is invalid")
        number = int(attempts.get(phase.value, 0)) + 1
        if self.repo_root is None:
            raise AppError("repository_required", "repository root is required")
        config = RepositoryConfig.load(self.repo_root)
        if number > config.max_attempts:
            raise AppError("attempt_limit", "maximum attempts reached for phase")
        attempts[phase.value] = number
        attempt_id = f"{phase.value}-{number}-{self.id_factory()}"
        current_attempts = state.artifacts.setdefault("current_attempts", {})
        if not isinstance(current_attempts, dict):
            raise AppError("invalid_state", "current attempt metadata is invalid")
        current_attempts[phase.value] = attempt_id
        history = state.artifacts.setdefault("attempt_history", {})
        if not isinstance(history, dict):
            raise AppError("invalid_state", "attempt history is invalid")
        history[attempt_id] = {"phase": phase.value, "number": number}
        node.status = NodeStatus.RUNNING.value
        state.status = NodeStatus.RUNNING.value
        packet_path = self._store(run_id).run_dir / "attempts" / attempt_id / "phase-packet.json"
        prior = self._artifact_refs(state)
        rerun_reasons = state.artifacts.get("rerun_reasons", {})
        rerun_reason = rerun_reasons.get(phase.value) if isinstance(rerun_reasons, dict) else None
        knowledge_path = self._store(run_id).run_dir / "knowledge-packets" / f"{attempt_id}.json"
        if config.wiki_path.is_dir():
            packet = WikiService(WikiRepository(config.wiki_path), today=lambda: self.clock().date()).create_packet(
                KnowledgeQuery(repository=config.repository, services=config.services,
                               phase=phase.value), knowledge_path,
                SearchLimits(config.max_knowledge_entries, config.max_knowledge_characters))
        else:
            packet = WikiService(_EmptyWiki(), today=lambda: self.clock().date()).create_packet(
                KnowledgeQuery(repository=config.repository, services=config.services,
                               phase=phase.value), knowledge_path,
                SearchLimits(config.max_knowledge_entries, config.max_knowledge_characters))
        knowledge_ref = {"path": str(knowledge_path), "sha256": packet.digest}
        PhasePacket(run_id, phase, attempt_id, state.source_revision, knowledge_ref, prior,
                    rerun_reason if isinstance(rerun_reason, str) else None).write(packet_path)
        self._save(state, "phase_begun", {"phase": phase.value, "attempt": number,
                                          "attempt_id": attempt_id, "packet_path": str(packet_path)})
        return Attempt(run_id, phase.value, number, attempt_id, str(packet_path))

    def submit(self, run_id: str, attempt_id: str, result_path: Path) -> RunState:
        state = self._load(run_id)
        current = state.artifacts.get("current_attempts", {})
        accepted = state.artifacts.get("accepted_results", {})
        if not isinstance(current, dict) or not isinstance(accepted, dict):
            raise AppError("invalid_state", "attempt result metadata is invalid")
        previous = accepted.get(attempt_id)
        try:
            raw_result = result_path.read_bytes()
            result_digest = hashlib.sha256(raw_result).hexdigest()
            result = ChildResult.from_bytes(raw_result)
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise AppError("invalid_result", f"child result is invalid: {error}") from error
        if previous is not None:
            if isinstance(previous, dict) and previous.get("result_digest") == result_digest:
                return self._reconcile_submission_evidence(run_id, attempt_id, result_digest)
            raise AppError("result_conflict", "attempt already has a different accepted result")
        matching = [name for name, owner in current.items() if owner == attempt_id]
        if len(matching) != 1:
            raise AppError("attempt_owner_mismatch", "result does not belong to the current attempt")
        phase = Phase(matching[0])
        if state.current_phase != phase.value or state.nodes[phase.value].status != NodeStatus.RUNNING.value:
            raise AppError("attempt_owner_mismatch", "result does not belong to the running phase")
        artifact = result.artifact
        if result.status == "completed" and artifact is None:
            raise AppError("invalid_result", "completed result requires an artifact")
        if artifact is not None:
            self._validate_artifact(state, phase, artifact, result_path)
            artifacts = state.artifacts.setdefault("registered", [])
            if not isinstance(artifacts, list):
                raise AppError("invalid_state", "artifact registry is invalid")
            artifacts.append(artifact.to_dict())
        self._validate_knowledge_citations(run_id, attempt_id, result.knowledge_citations)
        citation_registry = state.artifacts.setdefault("knowledge_citations", [])
        if not isinstance(citation_registry, list):
            raise AppError("invalid_state", "knowledge citation registry is invalid")
        citation_registry.extend(item for item in result.knowledge_citations
                                 if item not in citation_registry)
        accepted_at = self.clock().isoformat()
        accepted_version = state.version + 1
        record = self._acceptance_record(state, phase, attempt_id, result_digest, result,
                                         accepted_version, accepted_at)
        accepted[attempt_id] = record
        state.artifacts["accepted_results"] = accepted
        if result.status == "completed":
            state.nodes[phase.value].status = NodeStatus.VALID.value
            self.machine.advance(state)
        else:
            state.nodes[phase.value].status = NodeStatus.RUNNING.value
            state.status = NodeStatus.RUNNING.value
        self._store(state.run_id).save(
            state.version, state, Event("result_submitted", record, accepted_at))
        return state

    @staticmethod
    def _acceptance_record(state: RunState, phase: Phase, attempt_id: str,
                           result_digest: str, result: ChildResult,
                           accepted_version: int, accepted_at: str) -> dict[str, object]:
        artifact = result.artifact
        return {"run_id": state.run_id, "node": phase.value, "phase": phase.value,
                "attempt_id": attempt_id, "result_digest": result_digest,
                "artifact_digest": None if artifact is None else artifact.sha256,
                "accepted_version": accepted_version, "accepted_at": accepted_at,
                "status": result.status, "summary": result.summary,
                "artifact": None if artifact is None else artifact.to_dict(),
                "knowledge_citations": list(result.knowledge_citations)}

    def _validate_knowledge_citations(self, run_id: str, attempt_id: str,
                                      citations: tuple[str, ...]) -> None:
        path = self._store(run_id).run_dir / "attempts" / attempt_id / "phase-packet.json"
        try:
            reference = PhasePacket.load(path).knowledge_packet
            packet_path = reference["path"]
            expected_digest = reference["sha256"]
            if not isinstance(packet_path, str) or not isinstance(expected_digest, str):
                raise ValueError("knowledge packet path is invalid")
            resolved = Path(packet_path).resolve()
            resolved.relative_to(self._store(run_id).run_dir.resolve())
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            unsigned = {key: value for key, value in payload.items() if key != "digest"}
            actual_digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
                                                       separators=(",", ":")).encode()).hexdigest()
            if payload.get("digest") != expected_digest or actual_digest != expected_digest:
                raise ValueError("knowledge packet digest does not match")
            allowed = payload["selected_ids"]
            if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
                raise ValueError("selected knowledge IDs are invalid")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AppError("invalid_state", "phase knowledge packet is malformed") from error
        unknown = sorted(set(citations) - set(allowed))
        if unknown:
            raise AppError("invalid_result", f"knowledge citation was not in phase packet: {unknown[0]}")

    def _reconcile_submission_evidence(self, run_id: str, attempt_id: str,
                                       result_digest: str) -> RunState:
        store = self._store(run_id)
        with store.event_lock():
            try:
                state = store.load()
                self._validate_state(state, run_id)
            except (yaml.YAMLError, KeyError, TypeError, ValueError, UnicodeError) as error:
                raise AppError("invalid_state", "workflow state is malformed") from error
            accepted = state.artifacts["accepted_results"]
            assert isinstance(accepted, dict)
            record = accepted.get(attempt_id)
            if not isinstance(record, dict) or record.get("result_digest") != result_digest:
                raise AppError("result_conflict", "accepted result changed during reconciliation")
            events = self._read_events(run_id, recover_incomplete_tail=True,
                                       store=store, event_lock_held=True)
            found = any(event["type"] == "result_submitted"
                        and all(event["data"].get(key) == record[key]
                                for key in ("run_id", "node", "attempt_id", "result_digest",
                                            "artifact_digest", "accepted_version", "accepted_at"))
                        for event in events)
            if not found:
                store.save_locked(
                    state.version, state,
                    Event("result_submitted", record, self.clock().isoformat()))
            return state

    def _validate_artifact(self, state: RunState, phase: Phase, artifact: ArtifactRef,
                           result_path: Path) -> None:
        if artifact.phase != phase:
            raise AppError("invalid_result", "artifact phase does not match attempt")
        if artifact.source_revision != state.source_revision:
            raise AppError("invalid_result", "artifact source revision does not match run")
        path = Path(artifact.path)
        if not path.is_absolute():
            path = result_path.parent / path
        if self.repo_root is None:
            raise AppError("repository_required", "repository root is required")
        try:
            path.resolve().relative_to(self.repo_root.resolve())
        except ValueError as error:
            raise AppError("invalid_result", "artifact path escapes repository") from error
        digest = hashlib.sha256()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
        except OSError as error:
            raise AppError("invalid_result", "artifact path must be a regular file") from error
        if digest.hexdigest() != artifact.sha256:
            raise AppError("artifact_digest_mismatch", "artifact digest does not match result")

    @staticmethod
    def _artifact_refs(state: RunState) -> tuple[ArtifactRef, ...]:
        raw = state.artifacts.get("registered", [])
        if not isinstance(raw, list):
            raise AppError("invalid_state", "artifact registry is invalid")
        try:
            if not all(isinstance(item, dict) for item in raw):
                raise ValueError("artifact registry entries must be objects")
            return tuple(ArtifactRef.from_dict(item) for item in raw)
        except (ValueError, TypeError, KeyError) as error:
            raise AppError("invalid_state", "artifact registry is invalid") from error

    def summary(self, run_id: str) -> RunSummary:
        self._load(run_id)
        events = self._read_events(run_id)
        attempts = [event for event in events if event["type"] == "phase_begun"]
        submissions = [event for event in events if event["type"] == "result_submitted"]
        durations: dict[str, int] = {}
        for begun in attempts:
            data = begun["data"]
            finished = next((event for event in submissions
                             if event["data"].get("attempt_id") == data.get("attempt_id")), None)
            finished_time = None if finished is None else finished["data"].get("accepted_at")
            if finished is not None and finished_time is None:
                finished_time = finished.get("timestamp")
            if finished and "timestamp" in begun and isinstance(finished_time, str):
                start = datetime.fromisoformat(begun["timestamp"])
                end = datetime.fromisoformat(finished_time)
                phase = str(data.get("phase"))
                durations[phase] = durations.get(phase, 0) + int((end - start).total_seconds() * 1000)
        transitions = [event["data"] for event in events if event["type"] == "workflow_transitioned"]
        for packet in self._store(run_id).run_dir.glob("attempts/*/phase-packet.json"):
            try:
                phase_packet = PhasePacket.load(packet)
                if phase_packet.run_id != run_id:
                    raise ValueError("phase packet run ID does not match")
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise AppError("invalid_state", "workflow phase packet is malformed") from error
        cited = {item for event in submissions
                 for item in event["data"].get("knowledge_citations", [])
                 if isinstance(item, str)}
        return RunSummary(run_id, durations, len(attempts),
                          sum(1 for item in submissions if item["data"].get("status") == "unable_to_complete")
                          + sum(len(item.get("reruns", {})) for item in transitions),
                          tuple(transitions), tuple(sorted(cited)))

    def _read_events(self, run_id: str, *, recover_incomplete_tail: bool = False,
                     store: StateStore | None = None,
                     event_lock_held: bool = False) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        try:
            event_store = self._store(run_id) if store is None else store
            if recover_incomplete_tail:
                if not event_lock_held:
                    raise RuntimeError("event lock is required for tail recovery")
                payload = event_store.normalize_event_tail_locked(recover_malformed=True)
            else:
                payload = event_store.events_path.read_bytes()
            for line in payload.decode("utf-8").splitlines():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("event must be an object")
                if not isinstance(event.get("type"), str) or not event["type"]:
                    raise ValueError("event type is invalid")
                if type(event.get("version")) is not int or event["version"] < 1:
                    raise ValueError("event version is invalid")
                if not isinstance(event.get("data"), dict):
                    raise ValueError("event data is invalid")
                accepted_at = event["data"].get("accepted_at")
                if event["type"] == "result_submitted" and accepted_at is not None:
                    if not isinstance(accepted_at, str):
                        raise ValueError("accepted_at is invalid")
                    datetime.fromisoformat(accepted_at)
                timestamp = event.get("timestamp")
                if timestamp is not None:
                    if not isinstance(timestamp, str):
                        raise ValueError("event timestamp is invalid")
                    datetime.fromisoformat(timestamp)
                events.append(event)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise AppError("invalid_state", "workflow events are malformed") from error
        return events

    def transition(
        self, run_id: str, accepted: bool, reruns: dict[Phase, str]
    ) -> RunState:
        state = self._load(run_id)
        self._active(state)
        phase = Phase(state.current_phase)
        if state.nodes[phase.value].status != NodeStatus.RUNNING.value:
            raise AppError("invalid_transition", "current node is not running")
        if accepted:
            if reruns:
                raise AppError("invalid_transition", "accepted transition cannot include reruns")
            state.nodes[phase.value].status = NodeStatus.VALID.value
            self.machine.advance(state)
        else:
            self.machine.apply_reruns(state, reruns)
            state.artifacts["rerun_reasons"] = {key.value: value for key, value in reruns.items()}
        self._save(
            state,
            "workflow_transitioned",
            {"accepted": accepted, "reruns": {key.value: value for key, value in reruns.items()}},
        )
        return state

    def block(self, run_id: str, reason: str) -> RunState:
        state = self._load(run_id)
        self._active(state)
        if not reason.strip():
            raise AppError("invalid_transition", "block reason must not be empty")
        state.artifacts[BLOCKED_STATE_KEY] = {
            "run": state.status,
            "node": state.nodes[state.current_phase].status,
        }
        state.status = NodeStatus.BLOCKED.value
        state.nodes[state.current_phase].status = NodeStatus.BLOCKED.value
        self._save(state, "run_blocked", {"reason": reason})
        return state

    def resume(self, run_id: str) -> RunState:
        state = self._load(run_id)
        if state.status != NodeStatus.BLOCKED.value:
            raise AppError("invalid_transition", "only a blocked run can be resumed")
        prior = state.artifacts.pop(BLOCKED_STATE_KEY, None)
        if (
            not isinstance(prior, dict)
            or not isinstance(prior.get("run"), str)
            or not isinstance(prior.get("node"), str)
        ):
            raise AppError("invalid_state", "blocked lifecycle metadata is invalid")
        state.status = prior["run"]
        state.nodes[state.current_phase].status = prior["node"]
        self._save(state, "run_resumed", {})
        return state

    def abort(self, run_id: str) -> RunState:
        state = self._load(run_id)
        self._active(state)
        state.status = "aborted"
        self._save(state, "run_aborted", {})
        return state

    def _active(self, state: RunState) -> None:
        if state.status in {"completed", "aborted"}:
            raise AppError("invalid_transition", "terminal run cannot be changed")
        if state.status == NodeStatus.BLOCKED.value:
            raise AppError("invalid_transition", "blocked run must be resumed first")

    def _store(self, run_id: str) -> StateStore:
        if self.repo_root is None:
            raise AppError("repository_required", "repository root is required")
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise AppError("invalid_run_id", "run ID has an invalid format")
        runs_root = (self.repo_root / ".ai-workflow" / "runs").resolve()
        run_entry = runs_root / run_id
        if run_entry.is_symlink():
            raise AppError("invalid_run_id", "run directory must not be a symlink")
        run_path = run_entry.resolve()
        if run_path.parent != runs_root:
            raise AppError("invalid_run_id", "run path escapes workflow storage")
        return StateStore(run_path)

    def _load(self, run_id: str) -> RunState:
        try:
            state = self._store(run_id).load()
        except FileNotFoundError as error:
            raise AppError("state_not_found", f"workflow run not found: {run_id}") from error
        except (yaml.YAMLError, KeyError, TypeError, ValueError, UnicodeError) as error:
            raise AppError("invalid_state", "workflow state is malformed") from error
        self._validate_state(state, run_id)
        return state

    @staticmethod
    def _validate_state(state: RunState, requested_run_id: str) -> None:
        if state.run_id != requested_run_id:
            raise AppError(
                "invalid_state",
                "persisted run ID does not match requested run ID",
            )
        try:
            current_phase = Phase(state.current_phase)
        except ValueError as error:
            raise AppError("invalid_state", "current phase is invalid") from error
        formal_phases = {phase.value for phase in Phase}
        if set(state.nodes) != formal_phases:
            raise AppError("invalid_state", "workflow nodes are incomplete or unknown")
        for phase in Phase:
            node = state.nodes[phase.value]
            if node.phase != phase.value or node.status not in NODE_STATUSES:
                raise AppError("invalid_state", f"node {phase.value} is invalid")
        if state.status not in RUN_STATUSES:
            raise AppError("invalid_state", "run status is invalid")
        attempts = state.artifacts.get("attempts", {})
        if not isinstance(attempts, dict):
            raise AppError("invalid_state", "attempt metadata is invalid")
        for phase, count in attempts.items():
            if phase not in formal_phases or type(count) is not int or count < 0:
                raise AppError("invalid_state", "attempt counter is invalid")
        current_attempts = state.artifacts.get("current_attempts", {})
        attempt_history = state.artifacts.get("attempt_history", {})
        accepted_results = state.artifacts.get("accepted_results", {})
        registered = state.artifacts.get("registered", [])
        knowledge_citations = state.artifacts.get("knowledge_citations", [])
        rerun_reasons = state.artifacts.get("rerun_reasons", {})
        def attempt_parts(attempt_id: object) -> tuple[str, int] | None:
            if not isinstance(attempt_id, str):
                return None
            match = ATTEMPT_ID_PATTERN.fullmatch(attempt_id)
            if match is None:
                return None
            return match.group(1), int(match.group(2))

        if not isinstance(attempt_history, dict):
            raise AppError("invalid_state", "attempt history is invalid")
        for attempt_id, owner in attempt_history.items():
            parts = attempt_parts(attempt_id)
            if (parts is None or not isinstance(owner, dict)
                    or set(owner) != {"phase", "number"}
                    or owner.get("phase") != parts[0] or owner.get("number") != parts[1]
                    or parts[1] > attempts.get(parts[0], 0)):
                raise AppError("invalid_state", "attempt history is invalid")
        expected_history = {(phase, number) for phase, count in attempts.items()
                            for number in range(1, count + 1)}
        actual_history = {attempt_parts(attempt_id) for attempt_id in attempt_history}
        if len(attempt_history) != len(expected_history) or actual_history != expected_history:
            raise AppError("invalid_state", "attempt history is incomplete or duplicated")

        if not isinstance(current_attempts, dict) or any(
            phase not in formal_phases or attempt_parts(attempt_id) != (phase, attempts.get(phase))
            or attempt_id not in attempt_history
            for phase, attempt_id in current_attempts.items()
        ):
            raise AppError("invalid_state", "current attempt metadata is invalid")
        if not isinstance(accepted_results, dict):
            raise AppError("invalid_state", "accepted result metadata is invalid")
        for attempt_id, record in accepted_results.items():
            if attempt_id not in attempt_history or not _valid_acceptance_record(
                record, state.run_id, attempt_id, state.source_revision
            ):
                raise AppError("invalid_state", "accepted result metadata is invalid")
            owner = attempt_history[attempt_id]
            assert isinstance(owner, dict) and isinstance(record, dict)
            if record["node"] != owner["phase"] or record["accepted_version"] > state.version:
                raise AppError("invalid_state", "accepted result ownership is invalid")
        if not isinstance(registered, list) or not all(isinstance(item, dict) for item in registered):
            raise AppError("invalid_state", "artifact registry is invalid")
        try:
            refs = tuple(ArtifactRef.from_dict(item) for item in registered)
        except (KeyError, TypeError, ValueError) as error:
            raise AppError("invalid_state", "artifact registry is invalid") from error
        if (not isinstance(knowledge_citations, list)
                or not all(isinstance(item, str) and item for item in knowledge_citations)
                or len(knowledge_citations) != len(set(knowledge_citations))):
            raise AppError("invalid_state", "knowledge citation registry is invalid")
        if any(ref.source_revision != state.source_revision for ref in refs):
            raise AppError("invalid_state", "artifact registry source revision is invalid")
        if not isinstance(rerun_reasons, dict) or any(
            phase not in formal_phases or not isinstance(reason, str) or not reason.strip()
            for phase, reason in rerun_reasons.items()
        ):
            raise AppError("invalid_state", "rerun reason metadata is invalid")
        blocked_state = state.artifacts.get(BLOCKED_STATE_KEY)
        if state.status == NodeStatus.BLOCKED.value:
            if state.nodes[current_phase.value].status != NodeStatus.BLOCKED.value:
                raise AppError("invalid_state", "blocked current node is invalid")
            if not isinstance(blocked_state, dict):
                raise AppError("invalid_state", "blocked lifecycle metadata is invalid")
            if (
                blocked_state.get("run") not in RESTORABLE_RUN_STATUSES
                or blocked_state.get("node") not in RESTORABLE_NODE_STATUSES
            ):
                raise AppError("invalid_state", "blocked lifecycle metadata is invalid")
        elif blocked_state is not None:
            raise AppError("invalid_state", "unexpected blocked lifecycle metadata")

    def _save(self, state: RunState, event_type: str, data: dict[str, object]) -> None:
        self._store(state.run_id).save(state.version, state, Event(event_type, data,
                                                                   self.clock().isoformat()))
