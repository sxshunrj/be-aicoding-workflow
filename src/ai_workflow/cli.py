import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.config import RepositoryConfig
from ai_workflow.doctor import run_doctor
from ai_workflow.errors import AppError
from ai_workflow.install import install_skills
from ai_workflow.path_authorization import PathKind, RepositoryPathAuthorizer
from ai_workflow.wecom.notify import (
    _env_from_shell_files,
    _fit_bytes,
    _hostname_operator,
    _shell_env_files,
    notify_command,
    reset_notify_dedup,
)
from ai_workflow.workflow.models import Phase, RunState
from ai_workflow.workflow.review import ReviewDecision
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.models import CandidateProposal
from ai_workflow.wiki.service import WikiService
from ai_workflow.wiki.search import KnowledgeQuery, SearchLimits


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AppError("invalid_arguments", message)


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="ai-workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install")
    install.add_argument("--source-root", type=Path, required=True)
    install.add_argument("--client", choices=("codex", "claude", "all"), default="all")
    install.add_argument("--scope", choices=("user", "repo"), default="user")
    install.add_argument("--repo", type=Path)
    install_mode = install.add_mutually_exclusive_group()
    install_mode.add_argument("--copy", action="store_true")
    install_mode.add_argument("--link", action="store_true")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--source-root", type=Path, required=True)
    doctor.add_argument("--repo", type=Path)
    doctor.add_argument("--client", choices=("codex", "claude", "all"), default="all")
    config = commands.add_parser("config")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    show = config_commands.add_parser("show")
    show.add_argument("--repo", type=Path, required=True)
    authorize_path = config_commands.add_parser("authorize-path")
    authorize_path.add_argument("--repo", type=Path, required=True)
    authorize_path.add_argument(
        "--kind", choices=("input", "generated-test", "report"), required=True
    )
    authorize_path.add_argument("--path", required=True)
    workflow = commands.add_parser("workflow")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    init = workflow_commands.add_parser("init")
    init.add_argument("--repo", type=Path, required=True)
    init.add_argument("--source-revision", required=True)
    init.add_argument("--requirement", required=True)
    init.add_argument("--profile", default="full")
    init.add_argument("--operators", default="")
    for name in ("status", "abort", "summary", "reflect"):
        command = workflow_commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--run-id", required=True)
    resume = workflow_commands.add_parser("resume")
    resume.add_argument("--repo", type=Path, required=True)
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--rerun", action="append", default=[])
    begin = workflow_commands.add_parser("begin")
    begin.add_argument("--repo", type=Path, required=True)
    begin.add_argument("--run-id", required=True)
    begin.add_argument("--phase", type=Phase, choices=list(Phase), required=True)
    begin.add_argument("--skill-dir", type=Path)
    stage = workflow_commands.add_parser("stage")
    stage.add_argument("--repo", type=Path, required=True)
    stage.add_argument("--run-id", required=True)
    stage.add_argument("--attempt-id", required=True)
    stage.add_argument("--child", required=True)
    stage.add_argument("--result", type=Path, required=True)
    stage_owned = workflow_commands.add_parser("stage-owned")
    stage_owned.add_argument("--repo", type=Path, required=True)
    stage_owned.add_argument("--run-id", required=True)
    stage_owned.add_argument("--attempt-id", required=True)
    stage_owned.add_argument("--phase", type=Phase, choices=list(Phase), required=True)
    stage_owned.add_argument("--child", required=True)
    stage_owned.add_argument("--artifact", type=Path, required=True)
    stage_owned.add_argument("--summary", required=True)
    finalize = workflow_commands.add_parser("finalize")
    finalize.add_argument("--repo", type=Path, required=True)
    finalize.add_argument("--run-id", required=True)
    finalize.add_argument("--attempt-id", required=True)
    transition = workflow_commands.add_parser("transition")
    transition.add_argument("--repo", type=Path, required=True)
    transition.add_argument("--run-id", required=True)
    review = workflow_commands.add_parser("review")
    review.add_argument("--repo", type=Path, required=True)
    review.add_argument("--run-id", required=True)
    review.add_argument("--rerun", action="append", default=[])
    review_accept = workflow_commands.add_parser("review-accept")
    review_accept.add_argument("--repo", type=Path, required=True)
    review_accept.add_argument("--run-id", required=True)
    review_accept.add_argument("--expected-digest", required=True)
    block = workflow_commands.add_parser("block")
    block.add_argument("--repo", type=Path, required=True)
    block.add_argument("--run-id", required=True)
    block.add_argument("--reason", required=True)
    reflect_submit = workflow_commands.add_parser("reflect-submit")
    reflect_submit.add_argument("--repo", type=Path, required=True)
    reflect_submit.add_argument("--run-id", required=True)
    reflect_submit.add_argument("--decision", type=Path, required=True)
    reflect_submit.add_argument("--proposal", type=Path)
    wiki = commands.add_parser("wiki")
    wiki_commands = wiki.add_subparsers(dest="wiki_command", required=True)
    lint = wiki_commands.add_parser("lint")
    lint.add_argument("--wiki", type=Path, required=True)
    for name in ("search", "packet"):
        command = wiki_commands.add_parser(name)
        command.add_argument("--wiki", type=Path, required=True)
        command.add_argument("--repository")
        command.add_argument("--service", action="append", default=[])
        command.add_argument("--path", action="append", default=[])
        command.add_argument("--language", action="append", default=[])
        command.add_argument("--phase")
        command.add_argument("--type", action="append", default=[])
        command.add_argument("--tag", action="append", default=[])
        command.add_argument("--text", default="")
        command.add_argument("--max-entries", type=int, default=8)
        command.add_argument("--max-characters", type=int, default=12000)
        if name == "packet":
            command.add_argument("--output", type=Path, required=True)
    propose = wiki_commands.add_parser("propose")
    propose.add_argument("--wiki", type=Path, required=True)
    propose.add_argument("--proposal", type=Path, required=True)
    propose.add_argument("--repo", type=Path, default=None)
    wiki_review = wiki_commands.add_parser("review")
    wiki_review.add_argument("--wiki", type=Path, required=True)
    wiki_review.add_argument("--id", required=True)
    wiki_review.add_argument("--max-related", type=int, default=8)
    for name in ("promote", "reject", "archive"):
        command = wiki_commands.add_parser(name)
        command.add_argument("--wiki", type=Path, required=True)
        command.add_argument("--id", required=True)
        command.add_argument("--reviewer", required=True)
        command.add_argument("--reason")
        command.add_argument("--expected-digest", required=True)
    wecom = commands.add_parser("wecom")
    wecom_commands = wecom.add_subparsers(dest="wecom_command", required=True)
    wecom_notify = wecom_commands.add_parser("notify")
    wecom_notify.add_argument("--repo", type=Path, required=True)
    wecom_notify.add_argument("--run-id", default=None)
    wecom_notify.add_argument(
        "--gate", required=True, choices=("review", "blocked", "governance", "git_handoff", "terminal")
    )
    wecom_notify.add_argument("--action", required=True)
    wecom_notify.add_argument("--summary", default="")
    wecom_notify.add_argument("--phase")
    wecom_notify.add_argument(
        "--subject",
        default=None,
        help="去重主体：同一 subject 只要成功推送过一次（任意发送方），"
        "后续通知自动去重；--force 可强制重发",
    )
    wecom_notify.add_argument("--force", action="store_true")
    wecom_notify.add_argument("--dry-run", action="store_true")
    return parser


def _config_data(config: RepositoryConfig) -> dict[str, object]:
    data = asdict(config)
    data["wiki_path"] = str(config.wiki_path)
    return data


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reruns(values: list[str]) -> dict[str, str]:
    reruns: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise AppError("invalid_arguments", "--rerun must use NODE=REASON")
        name, reason = value.split("=", 1)
        if not name.strip():
            raise AppError("invalid_arguments", "rerun node must not be empty")
        if not reason.strip():
            raise AppError("invalid_arguments", "rerun reason must not be empty")
        if name in reruns:
            raise AppError("invalid_arguments", f"duplicate rerun node: {name}")
        reruns[name] = reason
    return reruns


def _auto_notify_blocked(
    repo_root: Path, state: RunState, reason: str
) -> dict[str, object]:
    """Mechanically push the blocked-gate notification.

    A blocked run needs a human resume/abort decision, so ``workflow block``
    always notifies the team regardless of whether the harness LLM follows the
    skill template. Notification is enhancement-only: any failure writes a
    warning and never breaks the block. Phase comes from the run's current
    phase so the per-phase dedup key stays distinct.

    Returns the notify outcome so the command's response exposes whether the
    message was actually sent — a soft-failed notify is never silent.
    """
    try:
        return notify_command(
            repo_root,
            run_id=state.run_id,
            gate="blocked",
            phase=state.current_phase,
            action="请选择 resume / abort",
            summary=reason,
        )
    except AppError as error:
        print(
            f"wecom notify soft-failed ({error.code}): {error.message}",
            file=sys.stderr,
        )
        return {
            "sent": False,
            "error": error.code,
            "message": error.message,
        }


def _review_phase_facts(repo_root: Path, run_id: str, phase: str) -> list[str]:
    """One scannable line per staged child of the phase under review:
    what ran, whether it completed, its one-line summary, its artifact path,
    and open findings — the facts a human needs to accept or rerun without
    opening the session. Best-effort: any state/evidence problem degrades to
    an empty list and never breaks the notify."""
    try:
        state = WorkflowService(repo_root).status(run_id)
        current = state.artifacts.get("current_attempts", {})
        staged = state.artifacts.get("staged_results", {})
        attempt_id = current.get(phase) if isinstance(current, dict) else None
        attempt_results = (
            staged.get(attempt_id, {}) if isinstance(staged, dict) else {}
        )
        if not isinstance(attempt_id, str) or not isinstance(attempt_results, dict):
            return []
        lines: list[str] = []
        for child, record in attempt_results.items():
            if not isinstance(record, dict) or not isinstance(child, str):
                continue
            summary = ""
            findings_count = 0
            result_path = record.get("result_path")
            if isinstance(result_path, str):
                try:
                    result = ChildResult.from_bytes(Path(result_path).read_bytes())
                    summary = result.summary
                    findings_count = len(result.findings)
                except (AppError, OSError, ValueError):
                    summary = str(record.get("status", ""))
            else:
                summary = str(record.get("status", ""))
            mark = "✅" if record.get("status") == "completed" else "⚠️"
            summary_line = _fit_bytes(
                summary.splitlines()[0].strip() if summary.strip() else "（无摘要）",
                90,
            )
            line = f"・{child} {mark} {summary_line}"
            artifact = record.get("artifact")
            artifact_path = (
                artifact.get("path") if isinstance(artifact, dict) else None
            )
            if isinstance(artifact_path, str) and artifact_path:
                line += f"（{artifact_path}）"
            if findings_count:
                line += f"｜findings×{findings_count}"
            lines.append(line)
        return lines
    except (AppError, OSError):
        return []


def _auto_notify_review(
    repo_root: Path, decision: ReviewDecision
) -> dict[str, object]:
    """Mechanically push the review-gate notification when the Helper returns
    ``human_review``, so a review the team must act on is always announced even
    if the harness LLM skips the skill template call. Returns the notify
    outcome for the command's response."""
    if decision.decision != "human_review":
        return {"sent": False, "reason": "auto_accepted"}
    if decision.proposed_reruns:
        # Front-load WHAT is being rerun, then the per-node reasons — the
        # rerun reasons are full work orders written for the agent; the group
        # message only needs the scannable head (render caps the display).
        nodes = "、".join(node for node, _ in decision.proposed_reruns)
        reasons = "\n".join(
            f"・{node}：{reason}" for node, reason in decision.proposed_reruns
        )
        summary = f"重跑节点 {nodes}\n{reasons}"
        action = "接受或修改重跑方案"
    else:
        # Acceptance needs substance: list what the phase produced (children,
        # status, one-line summaries, artifacts, findings) so the human can
        # judge from the ping itself instead of digging through the session.
        facts = _review_phase_facts(repo_root, decision.run_id, decision.phase)
        summary = (
            "本阶段产物：\n" + "\n".join(facts)
            if facts
            else "review 未提出重跑建议"
        )
        action = "请验收产物或提出重跑"
    try:
        return notify_command(
            repo_root,
            run_id=decision.run_id,
            gate="review",
            phase=decision.phase,
            action=action,
            summary=summary,
        )
    except AppError as error:
        print(
            f"wecom notify soft-failed ({error.code}): {error.message}",
            file=sys.stderr,
        )
        return {
            "sent": False,
            "error": error.code,
            "message": error.message,
        }


def _auto_notify_stale_review(repo_root: Path, run_id: str) -> dict[str, object]:
    """Push a review-gate notification when the review command hits a stale gate.

    A blocked run that is resumed keeps its state version advanced, so the old
    review gate is stale and ``workflow review`` must create a new decision. The
    team is already waiting on this run though — the pending human review must
    not be silent while the harness re-generates the gate. Enhancement-only: a
    failure writes a warning and never breaks the review error path."""
    try:
        return notify_command(
            repo_root,
            run_id=run_id,
            gate="review",
            phase=None,
            action="run 已 resume，需重新生成 Review 决策",
            summary="旧 Review Gate 已失效（stale），harness 将创建新的 workflow decision",
        )
    except AppError as error:
        print(
            f"wecom notify soft-failed ({error.code}): {error.message}",
            file=sys.stderr,
        )
        return {
            "sent": False,
            "error": error.code,
            "message": error.message,
        }


def _auto_notify_terminal(repo_root: Path, run_id: str) -> dict[str, object]:
    """Mechanically push the terminal-completion notification when a run
    becomes completed/aborted, so the team is asked to accept the terminal
    state AND decide the git handoff in one message. Merging both decision
    points into a single webhook send avoids the WeCom group-robot rate limit
    (~1 msg / 20s) that would silently drop a second immediate message.
    Enhancement-only: a failure writes a warning and never breaks the
    transition."""
    try:
        return notify_command(
            repo_root,
            run_id=run_id,
            gate="terminal",
            phase=None,
            action="请验收 run 终态（completed/aborted），并决定 Git 收尾方式（skip / commit / MR）",
            summary="run 已到终态，请验收并选择 Git 收尾方式",
        )
    except AppError as error:
        print(
            f"wecom notify soft-failed ({error.code}): {error.message}",
            file=sys.stderr,
        )
        return {
            "sent": False,
            "error": error.code,
            "message": error.message,
        }


def _governance_run_proposal_subject(run_id: str) -> str:
    """Subject key under which reflect-submit announces a run's candidate.

    A run persists at most one immutable reflection proposal, so the run id
    identifies the candidate at submit time — the wiki entry id is only minted
    later by ``wiki propose``, which joins this key as an alias subject and
    re-keys the announcement under the real entry id.
    """
    return f"run-proposal:{run_id}"


def _auto_notify_governance(
    repo_root: Path,
    run_id: str | None,
    reason: str,
    *,
    subject: str | None = None,
    alias_subjects: tuple[str, ...] = (),
) -> dict[str, object]:
    """Mechanically push the knowledge-governance notification when a run's
    reflection produces a candidate that needs human promote/reject/keep, so the
    team is asked to govern the knowledge even if the harness LLM never invokes
    the ``$ai-knowledge-governance`` skill template (or invokes it without a
    run-id). Also fires for candidates created via direct ``wiki propose``
    (run-less, repo-level). ``subject``/``alias_subjects`` key the announcement
    to the candidate so the three senders (reflect-submit, wiki propose, the
    governance skill) collapse into one group ping. Enhancement-only: a failure
    writes a warning and never breaks the reflection submit / wiki propose."""
    try:
        return notify_command(
            repo_root,
            run_id=run_id,
            gate="governance",
            phase=None,
            action="请选择 promote / reject / 保持",
            summary=reason,
            subject=subject,
            alias_subjects=alias_subjects,
        )
    except AppError as error:
        print(
            f"wecom notify soft-failed ({error.code}): {error.message}",
            file=sys.stderr,
        )
        return {
            "sent": False,
            "error": error.code,
            "message": error.message,
        }


def _default_operator(repo_root: Path) -> str:
    """Resolve the default WeCom operator for ``workflow init`` when
    ``--operators`` is omitted. Mirrors the notify side: the env variable name
    comes from ``wecom.creator_userid_env`` (falling back to
    ``WECOM_CREATOR_USERID``), GUI-launched agents that miss the shell's
    exports still resolve the value from the user's shell config files, and a
    machine with neither configured falls back to its host name before the
    notify-side ``@all``."""
    try:
        creator_env = (
            RepositoryConfig.load(repo_root).wecom_creator_userid_env
            or "WECOM_CREATOR_USERID"
        )
    except AppError:
        creator_env = "WECOM_CREATOR_USERID"
    creator = os.environ.get(creator_env, "").strip()
    if not creator:
        creator = (_env_from_shell_files(creator_env, _shell_env_files()) or "").strip()
    if not creator:
        creator = _hostname_operator() or ""
    return creator


def _notify_pending_review(
    repo_root: Path, state: RunState
) -> dict[str, object] | None:
    """Re-announce a pending human review when recovering an existing run.

    The recovery flow (recovery.md) re-displays a persisted human_review gate
    without re-running ``workflow review``, so the mechanical notify would never
    fire again on a resumed/short-lived session. Calling this from ``status``
    re-pushes the review notification for a gate still waiting on a human. It is
    idempotent: the dedup log suppresses a repeat of the same gate digest, so
    already-notified gates stay quiet and only genuinely-unannounced ones ping.
    Returns None when there is no pending human review to announce."""
    gate = state.artifacts.get("review_gate")
    if not isinstance(gate, dict):
        return None
    accepted_version = gate.get("accepted_version")
    if gate.get("decision") != "human_review" or accepted_version is not None:
        return None
    try:
        decision = ReviewDecision.from_dict(
            {key: gate[key] for key in (
                "decision", "run_id", "phase", "state_version",
                "proposed_reruns", "effective_reruns", "digest",
            )}
        )
    except (KeyError, TypeError, ValueError):
        return None
    return _auto_notify_review(repo_root, decision)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "install":
            clients = ("codex", "claude") if args.client == "all" else (args.client,)
            mode = "copy" if args.copy else "link" if args.link else "auto"
            report = install_skills(
                source_root=args.source_root,
                home=Path.home(),
                clients=clients,
                mode=mode,
                scope=args.scope,
                repo=args.repo,
            )
            data = report.to_dict()
            status = 1 if report.failed else 0
            print(json.dumps({"ok": not report.failed, "data": data}))
            return status
        elif args.command == "doctor":
            clients = ("codex", "claude") if args.client == "all" else (args.client,)
            report = run_doctor(
                source_root=args.source_root,
                home=Path.home(),
                repo=args.repo,
                clients=clients,
            )
            data = report.to_dict()
            status = 1 if report.failed else 0
            print(json.dumps({"ok": not report.failed, "data": data}))
            return status
        elif args.command == "config":
            config = RepositoryConfig.load(args.repo)
            if args.config_command == "show":
                data: object = _config_data(config)
            else:
                kind: PathKind = args.kind
                authorized = RepositoryPathAuthorizer(
                    args.repo, config
                ).authorize(kind, args.path)
                data = {
                    "authorized": True,
                    "kind": kind,
                    "path": authorized,
                }
        elif args.command == "wiki":
            service = WikiService(WikiRepository(args.wiki, validate_layout=False))
            if args.wiki_command == "lint":
                report = service.lint()
                print(json.dumps({"ok": True, "data": report.to_dict()}))
                return 0 if report.valid else 1
            elif args.wiki_command == "search":
                query = KnowledgeQuery(args.repository, tuple(args.service), tuple(args.path),
                                       tuple(args.language), args.phase, tuple(args.type),
                                       tuple(args.tag), args.text)
                limits = SearchLimits(args.max_entries, args.max_characters)
                data = [{"id": item.entry.id, "title": item.entry.title,
                         "score": item.score, "match_reasons": list(item.match_reasons),
                         "warnings": list(item.warnings)}
                        for item in service.search(query, limits)]
            elif args.wiki_command == "packet":
                query = KnowledgeQuery(args.repository, tuple(args.service), tuple(args.path),
                                       tuple(args.language), args.phase, tuple(args.type),
                                       tuple(args.tag), args.text)
                limits = SearchLimits(args.max_entries, args.max_characters)
                packet = service.create_packet(query, args.output, limits)
                data = {"path": str(args.output), "sha256": packet.digest,
                        "selected_ids": list(packet.selected_ids)}
            elif args.wiki_command == "propose":
                entry = service.propose(args.proposal)
                path = service.repository.root / "candidates" / f"{entry.id}.md"
                data = {"id": entry.id, "status": entry.status.value, "path": str(path),
                        "digest": _file_digest(path)}
                # A candidate still needs a human governance decision — push
                # mechanically so a direct `wiki propose` never silently waits
                # for a human who was never told. Keyed by the entry id: when
                # the proposal came from a run's reflect-submit (its sources
                # carry the run ref), that submit already announced under
                # run-proposal:<run>, so this collapses into the same single
                # ping instead of a second one and records the entry id for
                # the governance skill's --subject lookup. Requires --repo
                # for the wecom config.
                if args.repo is not None:
                    run_ref = next(
                        (
                            source["ref"]
                            for source in entry.sources
                            if source.get("kind") == "run" and source.get("ref")
                        ),
                        None,
                    )
                    data = {**data, "notify": _auto_notify_governance(
                        args.repo,
                        run_id=run_ref,
                        reason=f"知识候选 {entry.id} 已产生，需人工选择 promote / reject / 保持",
                        subject=entry.id,
                        alias_subjects=(
                            (_governance_run_proposal_subject(run_ref),)
                            if run_ref
                            else ()
                        ),
                    )}
            elif args.wiki_command == "review":
                data = service.review_candidate(args.id, args.max_related)
            elif args.wiki_command == "promote":
                entry = service.promote(args.id, args.reviewer, args.expected_digest)
                path = service.repository.root / "approved" / f"{entry.id}.md"
                data = {"id": entry.id, "status": entry.status.value, "path": str(path),
                        "digest": _file_digest(path)}
            elif args.wiki_command == "reject":
                if args.reason is None:
                    raise AppError("invalid_arguments", "--reason is required for reject")
                path = service.reject(args.id, args.reviewer, args.reason, args.expected_digest)
                data = {"id": args.id, "status": "archived", "path": str(path),
                        "digest": _file_digest(path)}
            else:
                if args.reason is None:
                    raise AppError("invalid_arguments", "--reason is required for archive")
                path = service.archive(args.id, args.reviewer, args.reason, args.expected_digest)
                data = {"id": args.id, "status": "archived", "path": str(path),
                        "digest": _file_digest(path)}
        elif args.command == "wecom":
            if args.wecom_command == "notify":
                try:
                    data = notify_command(
                        args.repo,
                        run_id=args.run_id,
                        gate=args.gate,
                        action=args.action,
                        summary=args.summary,
                        phase=args.phase,
                        subject=args.subject,
                        force=args.force,
                        dry_run=args.dry_run,
                    )
                except AppError as error:
                    if error.code not in {
                        "wecom_not_configured",
                        "wecom_invalid_webhook",
                        "wecom_api_error",
                        "wecom_http_error",
                        "wecom_tag_not_found",
                    }:
                        raise
                    # Notifications never block the workflow: soft-fail
                    # environmental errors into a success envelope so the
                    # enclosing shell step is never failed by a notification.
                    # The failure is still surfaced on stderr so run logs stay
                    # observable instead of silently swallowing the reason.
                    print(
                        f"wecom notify soft-failed ({error.code}): {error.message}",
                        file=sys.stderr,
                    )
                    data = {"sent": False, "error": error.message}
        else:
            service = WorkflowService(args.repo)
            if args.workflow_command == "init":
                operators = tuple(
                    item.strip()
                    for item in args.operators.split(",")
                    if item.strip()
                )
                if not operators:
                    creator = _default_operator(args.repo)
                    if creator:
                        operators = (creator,)
                data = service.init(
                    args.repo,
                    args.source_revision,
                    args.requirement,
                    args.profile,
                    operators=operators,
                ).to_dict()
            elif args.workflow_command == "status":
                state = service.status(args.run_id)
                data = state.to_dict()
                # A pending human_review gate that was never announced must be
                # announced on recovery — status is the recovery entry point.
                pending = _notify_pending_review(args.repo, state)
                if pending is not None:
                    data["notify_pending_review"] = pending
            elif args.workflow_command == "begin":
                data = service.begin(
                    args.run_id, args.phase, args.skill_dir
                ).to_dict()
            elif args.workflow_command == "stage":
                data = service.stage(
                    args.run_id, args.attempt_id, args.child, args.result
                ).to_dict()
            elif args.workflow_command == "stage-owned":
                data = service.stage_owned(
                    args.run_id,
                    args.attempt_id,
                    args.phase,
                    args.child,
                    args.artifact,
                    args.summary,
                ).to_dict()
            elif args.workflow_command == "finalize":
                data = service.finalize(args.run_id, args.attempt_id).to_dict()
            elif args.workflow_command == "summary":
                data = service.summary(args.run_id).to_dict()
            elif args.workflow_command == "reflect":
                packet = service.reflection_packet(args.run_id)
                data = {
                    "path": str(
                        service._store(args.run_id).reflection_packet_path()
                    ),
                    "evidence_digest": packet.evidence_digest,
                }
            elif args.workflow_command == "reflect-submit":
                record = service.submit_reflection(
                    args.run_id, args.decision, args.proposal
                )
                data = record
                # A candidate reflection needs a human governance decision
                # (promote/reject/keep). Push it mechanically — the team must
                # learn about the candidate even if the LLM skips the
                # $ai-knowledge-governance skill's notify call. The wiki entry
                # id does not exist yet (wiki propose mints it later), so the
                # announcement is keyed by the run's proposal; wiki propose
                # joins that key and re-keys under the entry id.
                if record.get("outcome") == "candidate":
                    try:
                        proposal_title = CandidateProposal.from_json(
                            args.proposal
                        ).title
                        reason = (
                            f"知识候选「{proposal_title}」已产生，"
                            "需人工选择 promote / reject / 保持"
                        )
                    except AppError:
                        reason = "知识候选已产生，需人工选择 promote / reject / 保持"
                    data = {**record, "notify": _auto_notify_governance(
                        args.repo,
                        args.run_id,
                        reason,
                        subject=_governance_run_proposal_subject(args.run_id),
                    )}
            elif args.workflow_command == "review":
                try:
                    decision = service.review(args.run_id, _reruns(args.rerun))
                except AppError as error:
                    if error.code == "stale_review_gate":
                        # A resumed run's old gate is stale: the review command
                        # must create a new decision, but the team is already
                        # waiting on this run — notify them so the pending human
                        # decision is never silent.
                        _auto_notify_stale_review(args.repo, args.run_id)
                    raise
                data = decision.to_dict()
                data["notify"] = _auto_notify_review(args.repo, decision)
            elif args.workflow_command == "review-accept":
                try:
                    data = service.record_review_acceptance(
                        args.run_id, args.expected_digest
                    ).to_dict()
                except AppError as error:
                    if error.code in {
                        "checkpoint_scope_ambiguous",
                        "checkpoint_creation_failed",
                        "checkpoint_unavailable",
                        "path_not_authorized",
                    }:
                        # The Helper auto-blocks the run inside
                        # record_review_acceptance when checkpoint creation
                        # fails, bypassing `workflow block`; push the blocked
                        # notification here so a checkpoint-driven block is
                        # never silent. The command still re-raises so the
                        # checkpoint failure stays the reported outcome.
                        _auto_notify_blocked(
                            args.repo, service.status(args.run_id), error.message
                        )
                    raise
            elif args.workflow_command == "transition":
                state = service.transition(args.run_id)
                data = state.to_dict()
                data["notify"] = (
                    _auto_notify_terminal(args.repo, args.run_id)
                    if state.status == "completed"
                    else {"sent": False, "reason": "not_terminal"}
                )
            elif args.workflow_command == "block":
                state = service.block(args.run_id, args.reason)
                data = state.to_dict()
                data["notify"] = _auto_notify_blocked(args.repo, state, args.reason)
            elif args.workflow_command == "resume":
                state = service.resume(
                    args.run_id, _reruns(args.rerun)
                ).to_dict()
                # A resumed run starts a NEW human decision cycle. Forget the
                # old dedup digests so the fresh review/blocked/terminal gates
                # always re-notify the team instead of being swallowed as
                # "already notified".
                reset_notify_dedup(args.repo, args.run_id)
                data = state
            else:
                state = service.abort(args.run_id)
                data = state.to_dict()
                data["notify"] = _auto_notify_terminal(args.repo, args.run_id)
        envelope: dict[str, object] = {"ok": True, "data": data}
        status = 0
    except AppError as error:
        envelope = {
            "ok": False,
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        }
        status = error.exit_status
    print(json.dumps(envelope))
    return status


def entrypoint() -> None:
    raise SystemExit(main())
