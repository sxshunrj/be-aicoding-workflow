from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Literal
from uuid import uuid4

import yaml

from ai_workflow.config import RepositoryConfig
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.dispatch import OWNER_CONTRACT, render_prompt_file
from ai_workflow.workflow.graph import NodeValidity, build_run_graph
from ai_workflow.workflow.machine import StateMachine, phase_nodes
from ai_workflow.workflow.models import NodeStatus, Phase, RunState
from ai_workflow.workflow.store import Event, StateStore
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.search import KnowledgeQuery, SearchLimits
from ai_workflow.wiki.service import WikiService


RUN_ID_PATTERN = re.compile(r"RUN-\d{8}-\d{6}-[0-9a-f]{6}")
ID_SUFFIX_PATTERN = re.compile(r"[0-9a-f]{6}")
ATTEMPT_ID_PATTERN = re.compile(
    r"(spec|plan|implement|verify)-([1-9]\d*)-[0-9a-f]{6}"
)
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
BLOCKED_STATE_KEY = "_blocked_state"
UNABLE_REASON = (
    "child unable to complete; workflow must provide an actionable reason"
)
RUN_STATUSES = {
    NodeStatus.PENDING.value,
    NodeStatus.RUNNING.value,
    NodeStatus.BLOCKED.value,
    "completed",
    "aborted",
}


class _EmptyWiki:
    def paths(self) -> list[Path]:
        return []

    def read(self, path: Path):
        raise AssertionError("empty wiki has no readable paths")


@dataclass(frozen=True, slots=True)
class DispatchItem:
    node: str
    child: str
    action: Literal["dispatch", "rerun", "already_staged"]
    prompt_file: str | None
    packet_file: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "node": self.node,
            "child": self.child,
            "action": self.action,
            "prompt_file": self.prompt_file,
            "packet_file": self.packet_file,
        }


@dataclass(frozen=True, slots=True)
class PhaseAttempt:
    run_id: str
    phase: str
    number: int
    attempt_id: str
    dispatch_plan: tuple[DispatchItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "number": self.number,
            "attempt_id": self.attempt_id,
            "dispatch_plan": [item.to_dict() for item in self.dispatch_plan],
        }


@dataclass(frozen=True, slots=True)
class StagedChild:
    run_id: str
    node: str
    child: str
    attempt_id: str
    status: Literal["completed", "unable_to_complete"]
    result_path: str
    result_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "node": self.node,
            "child": self.child,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "result_path": self.result_path,
            "result_digest": self.result_digest,
        }


@dataclass(frozen=True, slots=True)
class PhaseAggregate:
    run_id: str
    phase: str
    attempt_id: str
    status: Literal["completed", "unable_to_complete"]
    children: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "children": list(self.children),
        }

    @classmethod
    def from_bytes(cls, payload: bytes) -> PhaseAggregate:
        data = json.loads(payload.decode("utf-8"))
        expected = {"run_id", "phase", "attempt_id", "status", "children"}
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError("phase aggregate keys are invalid")
        if not all(
            isinstance(data[key], str) and data[key].strip()
            for key in ("run_id", "phase", "attempt_id")
        ):
            raise ValueError("phase aggregate identity is invalid")
        if data["status"] not in ("completed", "unable_to_complete"):
            raise ValueError("phase aggregate status is invalid")
        if not isinstance(data["children"], list) or not all(
            isinstance(child, dict) for child in data["children"]
        ):
            raise ValueError("phase aggregate children are invalid")
        return cls(
            run_id=data["run_id"],
            phase=data["phase"],
            attempt_id=data["attempt_id"],
            status=data["status"],
            children=tuple(data["children"]),
        )


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    phase_durations_ms: dict[str, int]
    attempt_count: int
    rerun_count: int
    review_gate_decisions: tuple[dict[str, object], ...]
    cited_knowledge_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "phase_durations_ms": self.phase_durations_ms,
            "attempt_count": self.attempt_count,
            "rerun_count": self.rerun_count,
            "review_gate_decisions": list(self.review_gate_decisions),
            "cited_knowledge_ids": list(self.cited_knowledge_ids),
        }


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

    def init(
        self,
        repo_root: Path,
        source_revision: str,
        requirement: str,
        profile: str = "full",
    ) -> RunState:
        config = RepositoryConfig.load(repo_root)
        if not isinstance(source_revision, str) or not source_revision.strip():
            raise AppError(
                "invalid_source_revision", "source revision must not be empty"
            )
        if not isinstance(requirement, str) or not requirement.strip():
            raise AppError("invalid_requirement", "requirement must not be empty")
        if not isinstance(profile, str) or not profile.strip():
            raise AppError("invalid_profile", "profile must not be empty")
        self.repo_root = repo_root
        suffix = self._new_id_suffix()
        run_id = f"RUN-{self.clock():%Y%m%d-%H%M%S}-{suffix}"
        state = RunState.new(
            run_id,
            source_revision,
            requirement,
            profile,
            build_run_graph(config),
        )
        self._store(run_id).create(state)
        return state

    def status(self, run_id: str) -> RunState:
        return self._load(run_id)

    def begin(self, run_id: str, phase: Phase, skill_dir: Path) -> PhaseAttempt:
        store = self._store(run_id)
        with store.event_lock():
            state = self._load_locked(store, run_id)
            self._active(state)
            if state.current_phase != phase.value:
                raise AppError("invalid_transition", "cannot skip workflow phases")
            current_attempts = self._mapping(
                state.artifacts, "current_attempts", "current attempt metadata"
            )
            current_id = current_attempts.get(phase.value)
            if isinstance(current_id, str):
                return self._current_attempt(state, current_id, store)

            effective = tuple(
                node
                for node in phase_nodes(state, phase)
                if node.validity is not NodeValidity.VALID
            )
            if not effective:
                raise AppError(
                    "invalid_transition", "phase has no dispatchable child nodes"
                )
            attempts = self._mapping(
                state.artifacts, "attempts", "attempt metadata"
            )
            number = int(attempts.get(phase.value, 0)) + 1
            config = self._config()
            if number > config.max_attempts:
                raise AppError(
                    "attempt_limit", "maximum attempts reached for phase"
                )
            attempt_id = f"{phase.value}-{number}-{self._new_id_suffix()}"
            resolved_skill = self._validate_skill_dir(skill_dir, effective)
            attempts[phase.value] = number
            current_attempts[phase.value] = attempt_id
            history = self._mapping(
                state.artifacts, "attempt_history", "attempt history"
            )
            history[attempt_id] = {
                "phase": phase.value,
                "number": number,
                "nodes": [node.key for node in effective],
                "skill_dir": str(resolved_skill),
            }
            state.status = NodeStatus.RUNNING.value
            dispatch_plan = self._create_dispatch_plan(
                state, effective, attempt_id, resolved_skill, store, config
            )
            event_data = {
                "phase": phase.value,
                "attempt": number,
                "attempt_id": attempt_id,
                "dispatch_plan": [item.to_dict() for item in dispatch_plan],
            }
            store.save_locked(
                state.version,
                state,
                Event("phase_begun", event_data, self.clock().isoformat()),
            )
            return PhaseAttempt(
                run_id, phase.value, number, attempt_id, dispatch_plan
            )

    def stage(
        self,
        run_id: str,
        attempt_id: str,
        child: str,
        result_path: Path,
    ) -> StagedChild:
        try:
            raw_result = result_path.read_bytes()
            result_digest = hashlib.sha256(raw_result).hexdigest()
            result = ChildResult.from_bytes(raw_result)
        except AppError:
            raise
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise AppError(
                "invalid_result", f"child result is invalid: {error}"
            ) from error

        store = self._store(run_id)
        with store.event_lock():
            state = self._load_locked(store, run_id)
            self._active(state)
            owner, node_key = self._attempt_child_owner(
                state, attempt_id, child, require_current=True
            )
            phase = Phase(owner["phase"])
            staged_results = self._mapping(
                state.artifacts, "staged_results", "staged result metadata"
            )
            attempt_results = staged_results.setdefault(attempt_id, {})
            if not isinstance(attempt_results, dict):
                raise AppError(
                    "invalid_state", "staged result metadata is invalid"
                )
            previous = attempt_results.get(child)
            if previous is not None:
                return self._existing_stage(
                    store,
                    state,
                    attempt_id,
                    child,
                    result_digest,
                    raw_result,
                    previous,
                )

            self._validate_result_owner(
                state, result, run_id, attempt_id, phase, child
            )
            packet = self._load_dispatch_packet(store, attempt_id, child)
            self._validate_dispatch_owner(
                packet, state, run_id, attempt_id, phase, child
            )
            if result.execution_mode != packet.execution_mode:
                raise AppError(
                    "invalid_result",
                    "child result execution mode does not match dispatch packet",
                )
            if result.artifact is not None:
                self._validate_artifact(
                    state, node_key, result.artifact, packet.allowed_output_path
                )
            self._validate_knowledge_citations(
                store, packet, result.knowledge_citations
            )
            staged_path = store.staged_path(attempt_id, child)
            try:
                store.write_immutable(staged_path, raw_result)
            except AppError as error:
                if error.code == "immutable_conflict":
                    raise AppError(
                        "result_conflict",
                        "child already has a different staged result",
                    ) from error
                raise
            staged_at = self.clock().isoformat()
            record: dict[str, object] = {
                "run_id": run_id,
                "node": node_key,
                "phase": phase.value,
                "child": child,
                "attempt_id": attempt_id,
                "status": result.status,
                "result_path": str(staged_path),
                "result_digest": result_digest,
                "staged_version": state.version + 1,
                "staged_at": staged_at,
                "artifact": (
                    None if result.artifact is None else result.artifact.to_dict()
                ),
                "knowledge_citations": list(result.knowledge_citations),
            }
            attempt_results[child] = record
            store.save_locked(
                state.version,
                state,
                Event("child_result_staged", record, staged_at),
            )
            return self._staged_child(record)

    def finalize(self, run_id: str, attempt_id: str) -> PhaseAggregate:
        store = self._store(run_id)
        with store.event_lock():
            state = self._load_locked(store, run_id)
            self._active(state)
            owner = self._attempt_owner(state, attempt_id, require_current=True)
            aggregates = self._mapping(
                state.artifacts, "phase_aggregates", "phase aggregate metadata"
            )
            previous = aggregates.get(attempt_id)
            if previous is not None:
                aggregate = self._load_existing_aggregate(
                    store, attempt_id, previous
                )
                self._ensure_event_locked(
                    store, state, "phase_finalized", previous
                )
                return aggregate

            raw_nodes = owner["nodes"]
            assert isinstance(raw_nodes, list)
            staged_results = self._mapping(
                state.artifacts, "staged_results", "staged result metadata"
            )
            attempt_results = staged_results.get(attempt_id, {})
            if not isinstance(attempt_results, dict):
                raise AppError(
                    "invalid_state", "staged result metadata is invalid"
                )
            missing = [
                state.run_graph[key].child
                for key in raw_nodes
                if state.run_graph[key].child not in attempt_results
            ]
            if missing:
                raise AppError(
                    "barrier_incomplete", f"missing child result: {missing[0]}"
                )

            results: list[ChildResult] = []
            for node_key in raw_nodes:
                node = state.run_graph[node_key]
                record = attempt_results[node.child]
                if not isinstance(record, dict):
                    raise AppError(
                        "invalid_state", "staged result metadata is invalid"
                    )
                staged_path = store.staged_path(attempt_id, node.child)
                try:
                    payload = staged_path.read_bytes()
                    if hashlib.sha256(payload).hexdigest() != record["result_digest"]:
                        raise ValueError("staged result digest does not match")
                    result = ChildResult.from_bytes(payload)
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:
                    raise AppError(
                        "invalid_state", "staged child result is malformed"
                    ) from error
                self._validate_result_owner(
                    state,
                    result,
                    run_id,
                    attempt_id,
                    node.phase,
                    node.child,
                )
                results.append(result)

            aggregate_status: Literal["completed", "unable_to_complete"] = (
                "unable_to_complete"
                if any(result.status == "unable_to_complete" for result in results)
                else "completed"
            )
            aggregate = PhaseAggregate(
                run_id=run_id,
                phase=owner["phase"],
                attempt_id=attempt_id,
                status=aggregate_status,
                children=tuple(result.to_dict() for result in results),
            )
            aggregate_payload = (
                json.dumps(aggregate.to_dict(), indent=2) + "\n"
            ).encode("utf-8")
            aggregate_path = store.aggregate_path(attempt_id)
            try:
                store.write_immutable(aggregate_path, aggregate_payload)
            except AppError as error:
                if error.code == "immutable_conflict":
                    raise AppError(
                        "invalid_state", "phase aggregate conflicts with staged results"
                    ) from error
                raise

            registered = self._list(
                state.artifacts, "registered", "artifact registry"
            )
            citation_registry = self._list(
                state.artifacts,
                "knowledge_citations",
                "knowledge citation registry",
            )
            for node_key, result in zip(raw_nodes, results, strict=True):
                node = state.run_graph[node_key]
                if result.status == "completed":
                    node.validity = NodeValidity.VALID
                    node.reason = None
                    assert result.artifact is not None
                    registered[:] = [
                        item
                        for item in registered
                        if not (
                            isinstance(item, dict)
                            and item.get("phase") == node.phase.value
                            and item.get("child") == node.child
                        )
                    ]
                    registered.append(result.artifact.to_dict())
                else:
                    node.validity = NodeValidity.RERUN
                    node.reason = UNABLE_REASON
                citation_registry.extend(
                    citation
                    for citation in result.knowledge_citations
                    if citation not in citation_registry
                )
            state.status = NodeStatus.RUNNING.value
            finalized_at = self.clock().isoformat()
            record = {
                **aggregate.to_dict(),
                "aggregate_path": str(aggregate_path),
                "aggregate_digest": hashlib.sha256(aggregate_payload).hexdigest(),
                "finalized_version": state.version + 1,
                "finalized_at": finalized_at,
            }
            aggregates[attempt_id] = record
            store.save_locked(
                state.version,
                state,
                Event("phase_finalized", record, finalized_at),
            )
            return aggregate

    def summary(self, run_id: str) -> RunSummary:
        self._load(run_id)
        events = self._read_events(run_id)
        for path in self._store(run_id).run_dir.glob("attempts/*/dispatch/*.json"):
            try:
                packet = DispatchPacket.load(path)
                if packet.run_id != run_id:
                    raise ValueError("dispatch packet run ID does not match")
            except AppError as error:
                raise AppError(
                    "invalid_state", "workflow dispatch packet is malformed"
                ) from error
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                raise AppError(
                    "invalid_state", "workflow dispatch packet is malformed"
                ) from error
        attempts = [event for event in events if event["type"] == "phase_begun"]
        finalized = [
            event for event in events if event["type"] == "phase_finalized"
        ]
        staged = [
            event for event in events if event["type"] == "child_result_staged"
        ]
        durations: dict[str, int] = {}
        for begun in attempts:
            data = begun["data"]
            finished = next(
                (
                    event
                    for event in finalized
                    if event["data"].get("attempt_id")
                    == data.get("attempt_id")
                ),
                None,
            )
            if (
                finished is not None
                and isinstance(begun.get("timestamp"), str)
                and isinstance(finished["data"].get("finalized_at"), str)
            ):
                start = datetime.fromisoformat(begun["timestamp"])
                end = datetime.fromisoformat(finished["data"]["finalized_at"])
                phase = str(data.get("phase"))
                durations[phase] = durations.get(phase, 0) + int(
                    (end - start).total_seconds() * 1000
                )
        transitions = tuple(
            event["data"]
            for event in events
            if event["type"] == "workflow_transitioned"
        )
        cited = {
            citation
            for event in staged
            for citation in event["data"].get("knowledge_citations", [])
            if isinstance(citation, str)
        }
        reruns = sum(
            1
            for event in staged
            if event["data"].get("status") == "unable_to_complete"
        ) + sum(len(item.get("reruns", {})) for item in transitions)
        return RunSummary(
            run_id,
            durations,
            len(attempts),
            reruns,
            transitions,
            tuple(sorted(cited)),
        )

    def transition(
        self, run_id: str, accepted: bool, reruns: dict[Phase, str]
    ) -> RunState:
        state = self._load(run_id)
        self._active(state)
        current_attempts = state.artifacts.get("current_attempts", {})
        aggregates = state.artifacts.get("phase_aggregates", {})
        attempt_id = (
            current_attempts.get(state.current_phase)
            if isinstance(current_attempts, dict)
            else None
        )
        if not isinstance(aggregates, dict) or attempt_id not in aggregates:
            raise AppError(
                "invalid_transition", "current phase must be finalized before transition"
            )
        if not accepted or reruns:
            raise AppError(
                "review_gate_required",
                "rerun and review-gate transitions are handled by the next workflow layer",
            )
        self.machine.advance(state)
        if isinstance(current_attempts, dict):
            current_attempts.pop(Phase(aggregates[attempt_id]["phase"]).value, None)
        self._save(
            state, "workflow_transitioned", {"accepted": True, "reruns": {}}
        )
        return state

    def block(self, run_id: str, reason: str) -> RunState:
        state = self._load(run_id)
        self._active(state)
        if not isinstance(reason, str) or not reason.strip():
            raise AppError("invalid_transition", "block reason must not be empty")
        state.artifacts[BLOCKED_STATE_KEY] = {"run": state.status}
        state.status = NodeStatus.BLOCKED.value
        self._save(state, "run_blocked", {"reason": reason})
        return state

    def resume(self, run_id: str) -> RunState:
        state = self._load(run_id)
        if state.status != NodeStatus.BLOCKED.value:
            raise AppError(
                "invalid_transition", "only a blocked run can be resumed"
            )
        prior = state.artifacts.pop(BLOCKED_STATE_KEY, None)
        if not isinstance(prior, dict) or prior.get("run") not in {
            NodeStatus.PENDING.value,
            NodeStatus.RUNNING.value,
        }:
            raise AppError(
                "invalid_state", "blocked lifecycle metadata is invalid"
            )
        state.status = prior["run"]
        self._save(state, "run_resumed", {})
        return state

    def abort(self, run_id: str) -> RunState:
        state = self._load(run_id)
        self._active(state)
        state.status = "aborted"
        self._save(state, "run_aborted", {})
        return state

    def _create_dispatch_plan(
        self,
        state: RunState,
        nodes,
        attempt_id: str,
        skill_dir: Path,
        store: StateStore,
        config: RepositoryConfig,
    ) -> tuple[DispatchItem, ...]:
        prior = self._artifact_refs(state)
        allowed_inputs = self._allowed_input_paths(config, prior)
        items: list[DispatchItem] = []
        contracts = skill_dir / "references" / "agents"
        for node in nodes:
            knowledge_path = store.knowledge_path(attempt_id, node.child)
            wiki = (
                WikiService(
                    WikiRepository(config.wiki_path),
                    today=lambda: self.clock().date(),
                )
                if config.wiki_path.is_dir()
                else WikiService(
                    _EmptyWiki(), today=lambda: self.clock().date()
                )
            )
            knowledge = wiki.create_packet(
                KnowledgeQuery(
                    repository=config.repository,
                    services=config.services,
                    phase=node.phase.value,
                ),
                knowledge_path,
                SearchLimits(
                    config.max_knowledge_entries,
                    config.max_knowledge_characters,
                ),
            )
            action: Literal["dispatch", "rerun"] = (
                "rerun"
                if node.validity is NodeValidity.RERUN
                else "dispatch"
            )
            output = (
                f"artifacts/{node.phase.value}-{node.child.replace('_', '-')}.md"
            )
            commands = {}
            command = config.command(node.child)
            if command is not None:
                commands[node.child] = command
            packet = DispatchPacket(
                run_id=state.run_id,
                phase=node.phase,
                child=node.child,
                attempt_id=attempt_id,
                source_revision=state.source_revision,
                requirement=state.requirement,
                execution_mode="rerun" if action == "rerun" else "fresh",
                rerun_reason=node.reason if action == "rerun" else None,
                owner_contract_path=str(
                    (contracts / OWNER_CONTRACT[node.key]).resolve()
                ),
                common_contract_path=str(
                    (contracts / "common-phase-contract.md").resolve()
                ),
                allowed_input_paths=allowed_inputs,
                allowed_output_path=output,
                commands=commands,
                knowledge_packet={
                    "path": str(knowledge_path),
                    "sha256": knowledge.digest,
                },
                prior_artifacts=prior,
            )
            packet_path = store.dispatch_path(attempt_id, node.child)
            packet_payload = (
                json.dumps(packet.to_dict(), indent=2) + "\n"
            ).encode("utf-8")
            try:
                store.write_immutable(packet_path, packet_payload)
            except AppError as error:
                if error.code == "immutable_conflict":
                    raise AppError(
                        "dispatch_packet_conflict",
                        f"dispatch packet already exists with different content: {packet_path}",
                    ) from error
                raise
            prompt_path = store.prompt_path(attempt_id, node.child)
            render_prompt_file(packet, prompt_path)
            items.append(
                DispatchItem(
                    node=node.key,
                    child=node.child,
                    action=action,
                    prompt_file=str(prompt_path),
                    packet_file=str(packet_path),
                )
            )
        return tuple(items)

    def _current_attempt(
        self, state: RunState, attempt_id: str, store: StateStore
    ) -> PhaseAttempt:
        owner = self._attempt_owner(state, attempt_id, require_current=True)
        raw_nodes = owner["nodes"]
        assert isinstance(raw_nodes, list)
        staged_results = state.artifacts.get("staged_results", {})
        attempt_results = (
            staged_results.get(attempt_id, {})
            if isinstance(staged_results, dict)
            else {}
        )
        if not isinstance(attempt_results, dict):
            raise AppError("invalid_state", "staged result metadata is invalid")
        plan: list[DispatchItem] = []
        for key in raw_nodes:
            node = state.run_graph[key]
            if node.child in attempt_results:
                plan.append(
                    DispatchItem(
                        node=key,
                        child=node.child,
                        action="already_staged",
                        prompt_file=None,
                        packet_file=None,
                    )
                )
                continue
            packet_path = store.dispatch_path(attempt_id, node.child)
            packet = self._load_dispatch_packet(store, attempt_id, node.child)
            self._validate_dispatch_owner(
                packet,
                state,
                state.run_id,
                attempt_id,
                node.phase,
                node.child,
            )
            prompt_path = store.prompt_path(attempt_id, node.child)
            try:
                render_prompt_file(packet, prompt_path)
            except AppError as error:
                raise AppError(
                    "invalid_state", "dispatch prompt is malformed"
                ) from error
            action: Literal["dispatch", "rerun"] = (
                "rerun" if packet.execution_mode == "rerun" else "dispatch"
            )
            plan.append(
                DispatchItem(
                    node=key,
                    child=node.child,
                    action=action,
                    prompt_file=str(prompt_path),
                    packet_file=str(packet_path),
                )
            )
        return PhaseAttempt(
            state.run_id,
            owner["phase"],
            owner["number"],
            attempt_id,
            tuple(plan),
        )

    def _existing_stage(
        self,
        store: StateStore,
        state: RunState,
        attempt_id: str,
        child: str,
        result_digest: str,
        raw_result: bytes,
        previous: object,
    ) -> StagedChild:
        if not isinstance(previous, dict):
            raise AppError("invalid_state", "staged result metadata is invalid")
        if previous.get("result_digest") != result_digest:
            raise AppError(
                "result_conflict", "child already has a different staged result"
            )
        staged_path = store.staged_path(attempt_id, child)
        try:
            if staged_path.read_bytes() != raw_result:
                raise ValueError("staged result bytes changed")
        except (OSError, ValueError) as error:
            raise AppError(
                "invalid_state", "staged result evidence is malformed"
            ) from error
        self._ensure_event_locked(
            store, state, "child_result_staged", previous
        )
        return self._staged_child(previous)

    def _load_existing_aggregate(
        self, store: StateStore, attempt_id: str, record: object
    ) -> PhaseAggregate:
        if not isinstance(record, dict):
            raise AppError("invalid_state", "phase aggregate metadata is invalid")
        path = store.aggregate_path(attempt_id)
        try:
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != record["aggregate_digest"]:
                raise ValueError("phase aggregate digest does not match")
            aggregate = PhaseAggregate.from_bytes(payload)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise AppError(
                "invalid_state", "phase aggregate evidence is malformed"
            ) from error
        if (
            aggregate.run_id != record.get("run_id")
            or aggregate.phase != record.get("phase")
            or aggregate.attempt_id != record.get("attempt_id")
            or aggregate.status != record.get("status")
            or list(aggregate.children) != record.get("children")
        ):
            raise AppError(
                "invalid_state", "phase aggregate metadata does not match evidence"
            )
        return aggregate

    def _ensure_event_locked(
        self,
        store: StateStore,
        state: RunState,
        event_type: str,
        record: dict[str, object],
    ) -> RunState:
        events = self._read_events(
            state.run_id,
            recover_incomplete_tail=True,
            store=store,
            event_lock_held=True,
        )
        if any(
            event["type"] == event_type and event["data"] == record
            for event in events
        ):
            return state
        store.save_locked(
            state.version,
            state,
            Event(event_type, record, self.clock().isoformat()),
        )
        return state

    @staticmethod
    def _staged_child(record: dict[str, object]) -> StagedChild:
        return StagedChild(
            run_id=record["run_id"],
            node=record["node"],
            child=record["child"],
            attempt_id=record["attempt_id"],
            status=record["status"],
            result_path=record["result_path"],
            result_digest=record["result_digest"],
        )

    def _load_dispatch_packet(
        self, store: StateStore, attempt_id: str, child: str
    ) -> DispatchPacket:
        try:
            packet = DispatchPacket.load(store.dispatch_path(attempt_id, child))
        except AppError:
            raise
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise AppError(
                "invalid_state", "child dispatch packet is malformed"
            ) from error
        return packet

    def _validate_result_owner(
        self,
        state: RunState,
        result: ChildResult,
        run_id: str,
        attempt_id: str,
        phase: Phase,
        child: str,
    ) -> None:
        if result.run_id != run_id:
            raise AppError("attempt_owner_mismatch", "result run does not match")
        if result.attempt_id != attempt_id:
            raise AppError(
                "attempt_owner_mismatch", "result attempt does not match"
            )
        if result.phase is not phase:
            raise AppError(
                "attempt_owner_mismatch", "result phase does not match attempt"
            )
        if result.child != child:
            raise AppError(
                "attempt_owner_mismatch", "result child does not match staged child"
            )
        if state.current_phase != phase.value:
            raise AppError(
                "attempt_owner_mismatch",
                "result does not belong to the current phase",
            )

    @staticmethod
    def _validate_dispatch_owner(
        packet: DispatchPacket,
        state: RunState,
        run_id: str,
        attempt_id: str,
        phase: Phase,
        child: str,
    ) -> None:
        if (
            packet.run_id != run_id
            or packet.attempt_id != attempt_id
            or packet.phase is not phase
            or packet.child != child
            or packet.source_revision != state.source_revision
            or packet.requirement != state.requirement
        ):
            raise AppError(
                "invalid_state", "child dispatch packet ownership is invalid"
            )

    def _validate_artifact(
        self,
        state: RunState,
        node_key: str,
        artifact: ArtifactRef,
        allowed_output: str,
    ) -> None:
        node = state.run_graph[node_key]
        if artifact.phase is not node.phase or artifact.child != node.child:
            raise AppError(
                "invalid_result", "artifact owner does not match attempt child"
            )
        if artifact.source_revision != state.source_revision:
            raise AppError(
                "invalid_result", "artifact source revision does not match run"
            )
        if artifact.path != allowed_output:
            raise AppError(
                "invalid_result", "artifact path is not the child-owned output"
            )
        pure = PurePosixPath(artifact.path)
        if (
            pure.is_absolute()
            or pure.as_posix() != artifact.path
            or ".." in pure.parts
            or "\\" in artifact.path
        ):
            raise AppError("invalid_result", "artifact path escapes repository")
        config = self._config()
        if any(fnmatchcase(artifact.path, pattern) for pattern in config.protected_paths):
            raise AppError(
                "protected_artifact_path", "artifact path is protected"
            )
        if self.repo_root is None:
            raise AppError(
                "repository_required", "repository root is required"
            )
        repository = self.repo_root.resolve()
        path = self.repo_root / artifact.path
        if path.is_symlink():
            raise AppError(
                "invalid_result", "artifact path must be a regular file"
            )
        try:
            resolved = path.resolve()
            resolved.relative_to(repository)
        except ValueError as error:
            raise AppError(
                "invalid_result", "artifact path escapes repository"
            ) from error
        digest = hashlib.sha256()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise OSError("artifact is not a regular file")
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
        except OSError as error:
            raise AppError(
                "invalid_result", "artifact path must be a regular file"
            ) from error
        if digest.hexdigest() != artifact.sha256:
            raise AppError(
                "artifact_digest_mismatch",
                "artifact digest does not match result",
            )

    def _validate_knowledge_citations(
        self,
        store: StateStore,
        dispatch: DispatchPacket,
        citations: tuple[str, ...],
    ) -> None:
        reference = dispatch.knowledge_packet
        try:
            packet_path = Path(reference["path"])
            expected_digest = reference["sha256"]
            expected_path = store.knowledge_path(
                dispatch.attempt_id, dispatch.child
            )
            if packet_path != expected_path:
                raise ValueError("knowledge packet path does not match child")
            payload = json.loads(packet_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("knowledge packet must be an object")
            unsigned = {key: value for key, value in payload.items() if key != "digest"}
            actual_digest = hashlib.sha256(
                json.dumps(
                    unsigned, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            if (
                payload.get("digest") != expected_digest
                or actual_digest != expected_digest
            ):
                raise ValueError("knowledge packet digest does not match")
            allowed = payload["selected_ids"]
            if not isinstance(allowed, list) or not all(
                isinstance(item, str) for item in allowed
            ):
                raise ValueError("selected knowledge IDs are invalid")
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise AppError(
                "invalid_state", "child knowledge packet is malformed"
            ) from error
        unknown = sorted(set(citations) - set(allowed))
        if unknown:
            raise AppError(
                "invalid_result",
                f"knowledge citation was not in phase packet: {unknown[0]}",
            )

    @staticmethod
    def _artifact_refs(state: RunState) -> tuple[ArtifactRef, ...]:
        raw = state.artifacts.get("registered", [])
        if not isinstance(raw, list):
            raise AppError("invalid_state", "artifact registry is invalid")
        try:
            if not all(isinstance(item, dict) for item in raw):
                raise ValueError("artifact registry entries must be objects")
            return tuple(ArtifactRef.from_dict(item) for item in raw)
        except (AppError, ValueError, TypeError, KeyError) as error:
            raise AppError(
                "invalid_state", "artifact registry is invalid"
            ) from error

    def _allowed_input_paths(
        self, config: RepositoryConfig, prior: tuple[ArtifactRef, ...]
    ) -> tuple[str, ...]:
        if self.repo_root is None:
            raise AppError(
                "repository_required", "repository root is required"
            )
        excluded = {".ai-workflow", "wiki", "artifacts"}
        paths = [
            entry.name
            for entry in sorted(self.repo_root.iterdir(), key=lambda item: item.name)
            if entry.name not in excluded
            and not entry.is_symlink()
            and not any(
                fnmatchcase(entry.name, pattern)
                for pattern in config.protected_paths
            )
        ]
        paths.extend(
            artifact.path for artifact in prior if artifact.path not in paths
        )
        return tuple(paths)

    @staticmethod
    def _validate_skill_dir(skill_dir: Path, nodes) -> Path:
        try:
            resolved = skill_dir.resolve(strict=True)
        except OSError as error:
            raise AppError(
                "invalid_skill_dir", "skill directory does not exist"
            ) from error
        contracts = resolved / "references" / "agents"
        required = {"common-phase-contract.md"} | {
            OWNER_CONTRACT[node.key] for node in nodes
        }
        for name in required:
            path = contracts / name
            if path.is_symlink() or not path.is_file():
                raise AppError(
                    "invalid_skill_dir", f"required child contract is missing: {name}"
                )
        return resolved

    def _attempt_owner(
        self, state: RunState, attempt_id: str, *, require_current: bool
    ) -> dict[str, object]:
        history = state.artifacts.get("attempt_history", {})
        owner = history.get(attempt_id) if isinstance(history, dict) else None
        if not isinstance(owner, dict):
            raise AppError(
                "attempt_owner_mismatch", "attempt does not belong to this run"
            )
        if require_current:
            current = state.artifacts.get("current_attempts", {})
            if (
                not isinstance(current, dict)
                or current.get(owner.get("phase")) != attempt_id
                or state.current_phase != owner.get("phase")
            ):
                raise AppError(
                    "attempt_owner_mismatch", "attempt is not current for this phase"
                )
        return owner

    def _attempt_child_owner(
        self,
        state: RunState,
        attempt_id: str,
        child: str,
        *,
        require_current: bool,
    ) -> tuple[dict[str, object], str]:
        owner = self._attempt_owner(
            state, attempt_id, require_current=require_current
        )
        nodes = owner.get("nodes")
        if not isinstance(nodes, list):
            raise AppError("invalid_state", "attempt history is invalid")
        matching = [
            key for key in nodes if state.run_graph[key].child == child
        ]
        if len(matching) != 1:
            raise AppError(
                "attempt_owner_mismatch", "child does not belong to the attempt"
            )
        return owner, matching[0]

    def _active(self, state: RunState) -> None:
        if state.status in {"completed", "aborted"}:
            raise AppError(
                "invalid_transition", "terminal run cannot be changed"
            )
        if state.status == NodeStatus.BLOCKED.value:
            raise AppError(
                "invalid_transition", "blocked run must be resumed first"
            )

    def _config(self) -> RepositoryConfig:
        if self.repo_root is None:
            raise AppError(
                "repository_required", "repository root is required"
            )
        return RepositoryConfig.load(self.repo_root)

    def _new_id_suffix(self) -> str:
        suffix = str(self.id_factory())
        if ID_SUFFIX_PATTERN.fullmatch(suffix) is None:
            raise AppError(
                "invalid_run_id",
                "generated ID suffix must be six lowercase hex characters",
            )
        return suffix

    def _store(self, run_id: str) -> StateStore:
        if self.repo_root is None:
            raise AppError(
                "repository_required", "repository root is required"
            )
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise AppError("invalid_run_id", "run ID has an invalid format")
        runs_root = (self.repo_root / ".ai-workflow" / "runs").resolve()
        run_entry = runs_root / run_id
        if run_entry.is_symlink():
            raise AppError(
                "invalid_run_id", "run directory must not be a symlink"
            )
        run_path = run_entry.resolve()
        if run_path.parent != runs_root:
            raise AppError(
                "invalid_run_id", "run path escapes workflow storage"
            )
        return StateStore(run_path)

    def _load(self, run_id: str) -> RunState:
        store = self._store(run_id)
        try:
            state = store.load()
        except FileNotFoundError as error:
            raise AppError(
                "state_not_found", f"workflow run not found: {run_id}"
            ) from error
        except AppError:
            raise
        except (
            yaml.YAMLError,
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
        ) as error:
            raise AppError(
                "invalid_state", "workflow state is malformed"
            ) from error
        self._validate_state(state, run_id)
        return state

    def _load_locked(self, store: StateStore, run_id: str) -> RunState:
        try:
            state = store.load()
        except FileNotFoundError as error:
            raise AppError(
                "state_not_found", f"workflow run not found: {run_id}"
            ) from error
        except AppError:
            raise
        except (
            yaml.YAMLError,
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
        ) as error:
            raise AppError(
                "invalid_state", "workflow state is malformed"
            ) from error
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
        if not phase_nodes(state, current_phase):
            raise AppError(
                "invalid_state", "current phase has no run graph nodes"
            )
        if state.status not in RUN_STATUSES:
            raise AppError("invalid_state", "run status is invalid")
        if "accepted_results" in state.artifacts or "rerun_reasons" in state.artifacts:
            raise AppError(
                "invalid_state", "legacy result metadata is not supported"
            )
        attempts = state.artifacts.get("attempts", {})
        if not isinstance(attempts, dict) or any(
            phase not in {item.value for item in Phase}
            or type(count) is not int
            or count < 0
            for phase, count in attempts.items()
        ):
            raise AppError("invalid_state", "attempt counter is invalid")
        history = state.artifacts.get("attempt_history", {})
        if not isinstance(history, dict):
            raise AppError("invalid_state", "attempt history is invalid")
        pairs: set[tuple[str, int]] = set()
        for attempt_id, owner in history.items():
            match = (
                ATTEMPT_ID_PATTERN.fullmatch(attempt_id)
                if isinstance(attempt_id, str)
                else None
            )
            if (
                match is None
                or not isinstance(owner, dict)
                or set(owner) != {"phase", "number", "nodes", "skill_dir"}
                or owner.get("phase") != match.group(1)
                or owner.get("number") != int(match.group(2))
                or not isinstance(owner.get("nodes"), list)
                or not owner["nodes"]
                or not all(isinstance(key, str) for key in owner["nodes"])
                or len(owner["nodes"]) != len(set(owner["nodes"]))
                or not isinstance(owner.get("skill_dir"), str)
                or not owner["skill_dir"]
            ):
                raise AppError("invalid_state", "attempt history is invalid")
            if any(
                key not in state.run_graph
                or state.run_graph[key].phase.value != owner["phase"]
                for key in owner["nodes"]
            ):
                raise AppError("invalid_state", "attempt history is invalid")
            pairs.add((owner["phase"], owner["number"]))
        expected_pairs = {
            (phase, number)
            for phase, count in attempts.items()
            for number in range(1, count + 1)
        }
        if pairs != expected_pairs or len(history) != len(expected_pairs):
            raise AppError(
                "invalid_state", "attempt history is incomplete or duplicated"
            )
        current_attempts = state.artifacts.get("current_attempts", {})
        if not isinstance(current_attempts, dict) or any(
            phase not in {item.value for item in Phase}
            or attempt_id not in history
            or history[attempt_id]["phase"] != phase
            or history[attempt_id]["number"] != attempts.get(phase)
            for phase, attempt_id in current_attempts.items()
        ):
            raise AppError(
                "invalid_state", "current attempt metadata is invalid"
            )
        staged = state.artifacts.get("staged_results", {})
        if not isinstance(staged, dict) or any(
            attempt_id not in history or not isinstance(results, dict)
            for attempt_id, results in staged.items()
        ):
            raise AppError(
                "invalid_state", "staged result metadata is invalid"
            )
        for attempt_id, results in staged.items():
            owner = history[attempt_id]
            owned_children = {
                state.run_graph[key].child for key in owner["nodes"]
            }
            for child, record in results.items():
                if (
                    child not in owned_children
                    or not WorkflowService._valid_staged_record(
                        record, state, attempt_id, child
                    )
                ):
                    raise AppError(
                        "invalid_state", "staged result metadata is invalid"
                    )
        aggregates = state.artifacts.get("phase_aggregates", {})
        if not isinstance(aggregates, dict) or any(
            attempt_id not in history
            or not WorkflowService._valid_aggregate_record(
                record, state, attempt_id
            )
            for attempt_id, record in aggregates.items()
        ):
            raise AppError(
                "invalid_state", "phase aggregate metadata is invalid"
            )
        registered = state.artifacts.get("registered", [])
        if not isinstance(registered, list) or not all(
            isinstance(item, dict) for item in registered
        ):
            raise AppError("invalid_state", "artifact registry is invalid")
        try:
            refs = tuple(ArtifactRef.from_dict(item) for item in registered)
        except (AppError, KeyError, TypeError, ValueError) as error:
            raise AppError(
                "invalid_state", "artifact registry is invalid"
            ) from error
        if any(ref.source_revision != state.source_revision for ref in refs):
            raise AppError(
                "invalid_state", "artifact registry source revision is invalid"
            )
        citations = state.artifacts.get("knowledge_citations", [])
        if (
            not isinstance(citations, list)
            or not all(isinstance(item, str) and item for item in citations)
            or len(citations) != len(set(citations))
        ):
            raise AppError(
                "invalid_state", "knowledge citation registry is invalid"
            )
        blocked = state.artifacts.get(BLOCKED_STATE_KEY)
        if state.status == NodeStatus.BLOCKED.value:
            if (
                not isinstance(blocked, dict)
                or set(blocked) != {"run"}
                or blocked["run"]
                not in {NodeStatus.PENDING.value, NodeStatus.RUNNING.value}
            ):
                raise AppError(
                    "invalid_state", "blocked lifecycle metadata is invalid"
                )
        elif blocked is not None:
            raise AppError(
                "invalid_state", "unexpected blocked lifecycle metadata"
            )

    @staticmethod
    def _valid_staged_record(
        record: object, state: RunState, attempt_id: str, child: str
    ) -> bool:
        expected = {
            "run_id",
            "node",
            "phase",
            "child",
            "attempt_id",
            "status",
            "result_path",
            "result_digest",
            "staged_version",
            "staged_at",
            "artifact",
            "knowledge_citations",
        }
        if not isinstance(record, dict) or set(record) != expected:
            return False
        node = state.run_graph.get(record.get("node"))
        if (
            record.get("run_id") != state.run_id
            or record.get("attempt_id") != attempt_id
            or record.get("child") != child
            or node is None
            or node.child != child
            or record.get("phase") != node.phase.value
            or record.get("status")
            not in {"completed", "unable_to_complete"}
            or not isinstance(record.get("result_path"), str)
            or not isinstance(record.get("result_digest"), str)
            or DIGEST_PATTERN.fullmatch(record["result_digest"]) is None
            or type(record.get("staged_version")) is not int
            or not 1 <= record["staged_version"] <= state.version
            or not isinstance(record.get("staged_at"), str)
            or not isinstance(record.get("knowledge_citations"), list)
            or not all(
                isinstance(item, str) for item in record["knowledge_citations"]
            )
        ):
            return False
        try:
            datetime.fromisoformat(record["staged_at"])
        except ValueError:
            return False
        artifact = record.get("artifact")
        if artifact is None:
            return record["status"] == "unable_to_complete"
        if not isinstance(artifact, dict):
            return False
        try:
            ref = ArtifactRef.from_dict(artifact)
        except (AppError, KeyError, TypeError, ValueError):
            return False
        return (
            ref.phase is node.phase
            and ref.child == child
            and ref.source_revision == state.source_revision
        )

    @staticmethod
    def _valid_aggregate_record(
        record: object, state: RunState, attempt_id: str
    ) -> bool:
        expected = {
            "run_id",
            "phase",
            "attempt_id",
            "status",
            "children",
            "aggregate_path",
            "aggregate_digest",
            "finalized_version",
            "finalized_at",
        }
        if not isinstance(record, dict) or set(record) != expected:
            return False
        if (
            record.get("run_id") != state.run_id
            or record.get("attempt_id") != attempt_id
            or record.get("status")
            not in {"completed", "unable_to_complete"}
            or not isinstance(record.get("children"), list)
            or not all(isinstance(item, dict) for item in record["children"])
            or not isinstance(record.get("aggregate_path"), str)
            or not isinstance(record.get("aggregate_digest"), str)
            or DIGEST_PATTERN.fullmatch(record["aggregate_digest"]) is None
            or type(record.get("finalized_version")) is not int
            or not 1 <= record["finalized_version"] <= state.version
            or not isinstance(record.get("finalized_at"), str)
        ):
            return False
        try:
            Phase(record["phase"])
            datetime.fromisoformat(record["finalized_at"])
        except (ValueError, TypeError):
            return False
        history = state.artifacts.get("attempt_history", {})
        owner = history.get(attempt_id) if isinstance(history, dict) else None
        return isinstance(owner, dict) and owner.get("phase") == record["phase"]

    def _read_events(
        self,
        run_id: str,
        *,
        recover_incomplete_tail: bool = False,
        store: StateStore | None = None,
        event_lock_held: bool = False,
    ) -> list[dict[str, object]]:
        try:
            event_store = self._store(run_id) if store is None else store
            if recover_incomplete_tail:
                if not event_lock_held:
                    raise RuntimeError("event lock is required for tail recovery")
                payload = event_store.normalize_event_tail_locked(
                    recover_malformed=True
                )
            else:
                payload = event_store.events_path.read_bytes()
            events: list[dict[str, object]] = []
            for line in payload.decode("utf-8").splitlines():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("event must be an object")
                if not isinstance(event.get("type"), str) or not event["type"]:
                    raise ValueError("event type is invalid")
                if (
                    type(event.get("version")) is not int
                    or event["version"] < 1
                ):
                    raise ValueError("event version is invalid")
                if not isinstance(event.get("data"), dict):
                    raise ValueError("event data is invalid")
                timestamp = event.get("timestamp")
                if timestamp is not None:
                    if not isinstance(timestamp, str):
                        raise ValueError("event timestamp is invalid")
                    datetime.fromisoformat(timestamp)
                for key in ("staged_at", "finalized_at"):
                    value = event["data"].get(key)
                    if value is not None:
                        if not isinstance(value, str):
                            raise ValueError(f"{key} is invalid")
                        datetime.fromisoformat(value)
                events.append(event)
            return events
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:
            raise AppError(
                "invalid_state", "workflow events are malformed"
            ) from error

    @staticmethod
    def _mapping(
        artifacts: dict[str, object], key: str, name: str
    ) -> dict[str, object]:
        value = artifacts.setdefault(key, {})
        if not isinstance(value, dict):
            raise AppError("invalid_state", f"{name} is invalid")
        return value

    @staticmethod
    def _list(
        artifacts: dict[str, object], key: str, name: str
    ) -> list[object]:
        value = artifacts.setdefault(key, [])
        if not isinstance(value, list):
            raise AppError("invalid_state", f"{name} is invalid")
        return value

    def _save(
        self, state: RunState, event_type: str, data: dict[str, object]
    ) -> None:
        self._store(state.run_id).save(
            state.version,
            state,
            Event(event_type, data, self.clock().isoformat()),
        )
