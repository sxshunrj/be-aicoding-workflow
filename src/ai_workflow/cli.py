import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from ai_workflow.config import RepositoryConfig
from ai_workflow.doctor import run_doctor
from ai_workflow.errors import AppError
from ai_workflow.install import install_skills
from ai_workflow.path_authorization import PathKind, RepositoryPathAuthorizer
from ai_workflow.wecom.notify import notify_command, reset_notify_dedup
from ai_workflow.workflow.models import Phase, RunState
from ai_workflow.workflow.review import ReviewDecision
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.wiki.repository import WikiRepository
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
    wecom_notify.add_argument("--run-id", required=True)
    wecom_notify.add_argument(
        "--gate", required=True, choices=("review", "blocked", "governance", "git_handoff", "terminal")
    )
    wecom_notify.add_argument("--action", required=True)
    wecom_notify.add_argument("--summary", default="")
    wecom_notify.add_argument("--phase")
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
        summary = "重跑：" + "；".join(
            f"{node}={reason}" for node, reason in decision.proposed_reruns
        )
    else:
        summary = "无重跑节点，请验收产物"
    try:
        return notify_command(
            repo_root,
            run_id=decision.run_id,
            gate="review",
            phase=decision.phase,
            action="等待人工 Review 决定",
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
    state even if the harness LLM skips the skill template call. Returns the
    notify outcome for the command's response."""
    try:
        return notify_command(
            repo_root,
            run_id=run_id,
            gate="terminal",
            phase=None,
            action="请验收 run 终态（completed/aborted）",
            summary="",
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
                        force=args.force,
                        dry_run=args.dry_run,
                    )
                except AppError as error:
                    if error.code not in {
                        "wecom_not_configured",
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
                    creator = os.environ.get("WECOM_CREATOR_USERID", "")
                    if creator.strip():
                        operators = (creator.strip(),)
                data = service.init(
                    args.repo,
                    args.source_revision,
                    args.requirement,
                    args.profile,
                    operators=operators,
                ).to_dict()
            elif args.workflow_command == "status":
                data = service.status(args.run_id).to_dict()
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
                data = service.submit_reflection(
                    args.run_id, args.decision, args.proposal
                )
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
