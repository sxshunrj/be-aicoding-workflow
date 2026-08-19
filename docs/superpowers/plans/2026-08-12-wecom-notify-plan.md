# WeCom Notify at Human Gates — Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At human-gate nodes (review / blocked / governance / git_handoff), push an idempotent WeCom notification to a **group-robot webhook**, annotated with `👤 开启者` and `🔑 授权操作者`.

**Architecture:** The Python Helper Core gains a new `wecom` domain module (`src/ai_workflow/wecom/`). `workflow init --operators` records the run's operators into `state.artifacts["operators"]` (creator default). A new `ai-workflow wecom notify` command reads `.ai-workflow.yaml`'s `wecom:` block + run state, reads the group-robot webhook URL from an env var, renders a Markdown message, and sends it via `webhook/send` through a transport-injected client. Sending is idempotent (dedup by content digest), soft-failing (never affects the workflow), and supports `--dry-run`. Three skills (`ai-workflow-harness`, `ai-git-handoff`, `ai-knowledge-governance`) call this command at their human gates.

**Tech Stack:** Python 3.11+, stdlib `urllib.request`, PyYAML. **No new dependencies in Plan 1.** (Plan 2 — the callback service — adds `cryptography` for WeCom AES.)

## Global Constraints

- Repository runs offline tests: `python -m pytest -q` (currently 487 passing). Every task keeps the suite green.
- Secret material (the webhook URL, etc.) comes **only from environment variables**, never from `.ai-workflow.yaml` values. Config stores **env-var names**, not values.
- Notifications never block the workflow: network/API/config failures return `{"sent": false, "error": ...}` and write a warning to stderr — they never raise into the workflow path.
- Idempotency key: `(run_id, gate, phase, content_digest)`. Same content → `dedup="repeat"`, no resend. Changed content → `dedup="content_changed"`, resend. `--force` skips dedup.
- Notification records live in `.ai-workflow/notifications/<run_id>.json` (sibling of `.ai-workflow/runs/`, both Helper-owned, both gitignored). Never written into `state.yaml`.
- Operators are WeCom `userid` strings. Display uses `@<userid>`. Creator is the first operator by convention (inserted first when resolved).
- New domain module follows repo layout: `src/ai_workflow/wecom/` with focused files, mirroring `src/ai_workflow/wiki/` structure.
- All new tests must run with the fake transport — never call the real WeCom API in tests.
- Copy style: type hints everywhere, `from __future__ import annotations` where forward refs occur, docstrings on public functions, plain-English comments matching repo density.

---

### Task 1: Parse the `wecom:` config block

**Files:**
- Modify: `src/ai_workflow/config.py` (dataclass fields ~line 32-47; `load()` ~line 76-125)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `RepositoryConfig` gains these attributes (all defaults shown):
  - `wecom_enabled: bool = False`
  - `wecom_webhook_url_env: str | None = None`
  - `wecom_creator_userid_env: str | None = None`
  - `wecom_gates: tuple[str, ...] = ("review", "blocked", "governance", "git_handoff")`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_config.py`:

```python
def test_load_wecom_block_and_defaults(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n"
        "  creator_userid_env: WECOM_CREATOR_USERID\n",
        encoding="utf-8",
    )
    config = RepositoryConfig.load(tmp_path)
    assert config.wecom_enabled is True
    assert config.wecom_webhook_url_env == "WECOM_WEBHOOK_URL"
    assert config.wecom_creator_userid_env == "WECOM_CREATOR_USERID"
    assert config.wecom_gates == ("review", "blocked", "governance", "git_handoff")


def test_load_wecom_disabled_by_default(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n", encoding="utf-8"
    )
    config = RepositoryConfig.load(tmp_path)
    assert config.wecom_enabled is False
    assert config.wecom_webhook_url_env is None
    assert config.wecom_gates == ("review", "blocked", "governance", "git_handoff")


def test_load_wecom_gates_restricts_choices(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  gates: [review, blocked]\n",
        encoding="utf-8",
    )
    config = RepositoryConfig.load(tmp_path)
    assert config.wecom_gates == ("review", "blocked")


def test_load_wecom_rejects_unknown_gate(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  gates: [review, nonsense]\n",
        encoding="utf-8",
    )
    with pytest.raises(AppError) as exc:
        RepositoryConfig.load(tmp_path)
    assert exc.value.code == "config_invalid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: FAIL with `AttributeError: 'RepositoryConfig' object has no attribute 'wecom_enabled'`

- [ ] **Step 3: Add dataclass fields and parsing**

In `src/ai_workflow/config.py`, add to the `RepositoryConfig` dataclass (after `adapter_report_paths`):

```python
    wecom_enabled: bool = False
    wecom_webhook_url_env: str | None = None
    wecom_creator_userid_env: str | None = None
    wecom_gates: tuple[str, ...] = ("review", "blocked", "governance", "git_handoff")
```

Add a module-level helper near `_strings`:

```python
_WECOM_GATES = ("review", "blocked", "governance", "git_handoff")


def _optional_env_name(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AppError("config_invalid", f"{name} must be a non-empty string")
    return value.strip()
```

Inside `load()`, after the `adapter` mapping is resolved, add parsing:

```python
        wecom = raw.get("wecom", {})
        if "wecom" in raw:
            wecom = _mapping(wecom, "wecom")
        wecom_gates = _strings(wecom.get("gates"), "wecom.gates") or _WECOM_GATES
        for gate in wecom_gates:
            if gate not in _WECOM_GATES:
                raise AppError(
                    "config_invalid",
                    f"wecom.gates contains an unknown gate: {gate}",
                )
```

And pass to the `cls(...)` constructor call:

```python
            wecom_enabled=bool(wecom.get("enabled", False)),
            wecom_webhook_url_env=_optional_env_name(
                wecom.get("webhook_url_env"), "wecom.webhook_url_env"
            ),
            wecom_creator_userid_env=_optional_env_name(
                wecom.get("creator_userid_env"), "wecom.creator_userid_env"
            ),
            wecom_gates=wecom_gates,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: PASS (new + existing config tests)

- [ ] **Step 5: Commit**

```bash
git add src/ai_workflow/config.py tests/unit/test_config.py
git commit -m "feat: parse wecom notify config block"
```

---

### Task 2: `workflow init --operators` records operators in run state

**Files:**
- Modify: `src/ai_workflow/workflow/service.py` (`init` at ~line 215)
- Modify: `src/ai_workflow/cli.py` (init parser ~line 52-56; dispatch ~line 267)
- Test: `tests/unit/workflow/test_service.py`
- Test: `tests/contract/test_workflow_cli.py`

**Interfaces:**
- Consumes: `WorkflowService.init` existing signature.
- Produces: `WorkflowService.init(repo_root, source_revision, requirement, profile="full", operators=())` — stores `state.artifacts["operators"] = list(operators)` (validated). CLI `workflow init --operators a,b` splits on comma; when omitted, defaults to `os.environ.get("WECOM_CREATOR_USERID", "")` (non-empty), inserted first.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/workflow/test_service.py`:

```python
def test_init_records_operators_in_artifacts(tmp_path: Path) -> None:
    service = WorkflowService()
    state = service.init(
        tmp_path,
        source_revision="abc123",
        requirement="Specify the change",
        operators=("sunxianshun", "wangxiaofei"),
    )
    assert state.artifacts["operators"] == ["sunxianshun", "wangxiaofei"]


def test_init_operators_default_empty(tmp_path: Path) -> None:
    service = WorkflowService()
    state = service.init(
        tmp_path,
        source_revision="abc123",
        requirement="Specify the change",
    )
    assert state.artifacts.get("operators", []) == []


def test_init_rejects_blank_operator(tmp_path: Path) -> None:
    service = WorkflowService()
    with pytest.raises(AppError) as exc:
        service.init(
            tmp_path,
            source_revision="abc123",
            requirement="Specify the change",
            operators=("",),
        )
    assert exc.value.code == "invalid_operators"
```

Note: `WorkflowService()` uses `repo_root=None`; `init()` sets `self.repo_root = repo_root` before building state, so the constructor arg is optional here (matches existing tests). If the existing `test_service.py` init tests construct differently, mirror their pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/workflow/test_service.py -k operators -v`
Expected: FAIL with `TypeError: init() got an unexpected keyword argument 'operators'`

- [ ] **Step 3: Implement operators in `init`**

In `src/ai_workflow/workflow/service.py`, change the `init` signature:

```python
    def init(
        self,
        repo_root: Path,
        source_revision: str,
        requirement: str,
        profile: str = "full",
        operators: tuple[str, ...] = (),
    ) -> RunState:
```

After the `profile` validation block and before `self.repo_root = repo_root`, add validation:

```python
        if not isinstance(operators, (list, tuple)):
            raise AppError(
                "invalid_operators", "operators must be a sequence of strings"
            )
        for operator in operators:
            if not isinstance(operator, str) or not operator.strip():
                raise AppError(
                    "invalid_operators", "operators must be non-empty strings"
                )
        resolved_operators = tuple(operators)
```

After `state = RunState.new(...)`, before the `RUN_POLICY_KEY` assignment, store operators:

```python
        state.artifacts["operators"] = list(resolved_operators)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/workflow/test_service.py -k operators -v`
Expected: PASS

- [ ] **Step 5: Wire the CLI `--operators` flag**

In `src/ai_workflow/cli.py`, add to the init parser (after `init.add_argument("--profile", default="full")`):

```python
    init.add_argument("--operators", default="")
```

In the dispatch block, replace the `workflow_command == "init"` branch:

```python
            elif args.workflow_command == "init":
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
```

Add `import os` at the top of `cli.py` if not already present.

- [ ] **Step 6: Add the contract test for the CLI flag**

Append to `tests/contract/test_workflow_cli.py`:

```python
def test_cli_init_records_operators(tmp_path: Path, capsys) -> None:
    _config(tmp_path)
    status, init = _call(
        capsys,
        [
            "workflow",
            "init",
            "--repo",
            str(tmp_path),
            "--source-revision",
            "abc123",
            "--requirement",
            "Specify the change",
            "--operators",
            "sunxianshun,wangxiaofei",
        ],
    )
    assert status == 0
    assert init["data"]["artifacts"]["operators"] == ["sunxianshun", "wangxiaofei"]
```

Note: `init["data"]` is the `RunState.to_dict()` output, so `artifacts` is present. Verify the envelope shape from the existing `test_cli_init_begin_stage_finalize_lifecycle` test (it asserts `init["data"]["profile"]`, so `data` is the state dict — confirm `data["artifacts"]` exists; if the envelope omits artifacts, assert on `init["data"]["artifacts"]["operators"]` accordingly).

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/ai_workflow/workflow/service.py src/ai_workflow/cli.py \
        tests/unit/workflow/test_service.py tests/contract/test_workflow_cli.py
git commit -m "feat: record operators at workflow init"
```

---

### Task 3: WeCom API client with injected transport (webhook-only)

**Files:**
- Create: `src/ai_workflow/wecom/__init__.py`
- Create: `src/ai_workflow/wecom/client.py`
- Test: `tests/unit/wecom/test_client.py`

**Interfaces:**
- Produces:
  - `WeComTransport` (Protocol): `def request_json(self, method: str, url: str, *, params: dict[str, object] | None = None, payload: dict[str, object] | None = None) -> dict[str, object]`
  - `UrllibTransport(WeComTransport)`: real implementation via `urllib.request`.
  - `WeComApiClient(*, transport: WeComTransport | None = None)`:
    - `webhook_send(*, content: str, webhook_url: str) -> dict[str, object]` — `POST` to the webhook URL (key embedded in the URL); raises `AppError("wecom_api_error", ...)` on `errcode != 0`.
  - `FakeWeComTransport` lives in tests (not production).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/wecom/test_client.py`:

```python
from __future__ import annotations

import urllib.error

import pytest

from ai_workflow.errors import AppError
from ai_workflow.wecom.client import UrllibTransport, WeComApiClient


class FakeWeComTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.send_result: dict[str, object] = {"errcode": 0, "errmsg": "ok"}

    def request_json(self, method: str, url: str, *, params=None, payload=None) -> dict[str, object]:
        self.calls.append((method, url, payload))
        if "/webhook/send" in url:
            return self.send_result
        raise AssertionError(f"unexpected url: {url}")


def test_urllib_transport_converts_urlerror_to_apperror(monkeypatch) -> None:
    def _offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("ai_workflow.wecom.client.urlopen", _offline)
    transport = UrllibTransport()
    with pytest.raises(AppError) as exc:
        transport.request_json("GET", "https://example.com/webhook/send")
    assert exc.value.code == "wecom_http_error"
    assert "offline" in exc.value.message


def test_urllib_transport_converts_timeout_to_apperror(monkeypatch) -> None:
    import socket

    def _timeout(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr("ai_workflow.wecom.client.urlopen", _timeout)
    transport = UrllibTransport()
    with pytest.raises(AppError) as exc:
        transport.request_json("GET", "https://example.com/webhook/send")
    assert exc.value.code == "wecom_http_error"


def test_webhook_send_posts_with_embedded_key() -> None:
    transport = FakeWeComTransport()
    client = WeComApiClient(transport=transport)
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123"
    result = client.webhook_send(content="**hi**", webhook_url=webhook)
    assert result == {"errcode": 0, "errmsg": "ok"}
    method, url, payload = transport.calls[-1]
    assert method == "POST"
    assert url == webhook  # exact webhook URL, key included
    assert payload["msgtype"] == "markdown"
    assert payload["markdown"]["content"] == "**hi**"


def test_webhook_send_raises_on_errcode() -> None:
    transport = FakeWeComTransport()
    transport.send_result = {"errcode": 93000, "errmsg": "invalid webhook key"}
    client = WeComApiClient(transport=transport)
    with pytest.raises(AppError) as exc:
        client.webhook_send(
            content="x",
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bad",
        )
    assert exc.value.code == "wecom_api_error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/wecom/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ai_workflow.wecom'`

- [ ] **Step 3: Create the module and client**

Create `src/ai_workflow/wecom/__init__.py` (empty docstring module):

```python
"""WeCom (enterprise WeChat) integration helpers."""
```

Create `src/ai_workflow/wecom/client.py`:

```python
from __future__ import annotations

import json
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ai_workflow.errors import AppError


class WeComTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]: ...


class UrllibTransport:
    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        target = url
        if params:
            target = f"{url}?{urlencode({k: str(v) for k, v in params.items()})}"
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(target, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=10) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            raise AppError(
                "wecom_http_error",
                f"WeCom HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:200]}",
            ) from error
        except OSError as error:
            # URLError (DNS failure, connection refused) and the OSError
            # subclasses raised by socket timeouts all land here. These are
            # environmental failures that must soft-fail the notify step, never
            # escape as an uncaught traceback.
            raise AppError(
                "wecom_http_error", f"WeCom request failed: {error}"
            ) from error
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AppError(
                "wecom_http_error", "WeCom returned non-JSON response"
            ) from error
        if not isinstance(data, dict):
            raise AppError("wecom_http_error", "WeCom returned an unexpected shape")
        return data


class WeComApiClient:
    def __init__(
        self, *, transport: WeComTransport | None = None
    ) -> None:
        self._transport = transport if transport is not None else UrllibTransport()

    def webhook_send(self, *, content: str, webhook_url: str) -> dict[str, object]:
        """Send a group-robot webhook message.

        The webhook URL itself carries the key (``.../webhook/send?key=...``),
        so the message is sent directly. Markdown supports
        ``<@userid>`` in ``content`` to force-notify members.
        """
        payload: dict[str, object] = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        data = self._transport.request_json("POST", webhook_url, payload=payload)
        if data.get("errcode", 0) != 0:
            raise AppError(
                "wecom_api_error",
                f"webhook/send failed: {data.get('errmsg')}",
            )
        return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/wecom/test_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_workflow/wecom/__init__.py src/ai_workflow/wecom/client.py tests/unit/wecom/test_client.py
git commit -m "feat: add WeCom webhook client with injected transport"
```

---

### Task 4: Message rendering + idempotent notify command (webhook-only)

**Files:**
- Create: `src/ai_workflow/wecom/notify.py`
- Test: `tests/unit/wecom/test_notify.py`

**Interfaces:**
- Consumes: `RepositoryConfig` (wecom fields), `WorkflowService.status(run_id) -> RunState`, `WeComApiClient`.
- Produces:
  - `render_message(*, gate, phase, run_id, requirement, repo, operators, action, summary) -> str`
  - `notify_command(repo_root: Path, *, run_id, gate, action, summary="", phase=None, force=False, dry_run=False, client=None) -> dict[str, object]`
  - Notification log path helper: `notification_log_path(repo_root, run_id) -> Path` → `<repo>/.ai-workflow/notifications/<run_id>.json`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/wecom/test_notify.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.wecom.notify import notify_command, render_message


class FakeWeComTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request_json(self, method: str, url: str, *, params=None, payload=None) -> dict[str, object]:
        self.calls.append((method, url, payload))
        if "/webhook/send" in url:
            self.sent.append(payload or {})
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123"


def _config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )


def _set_webhook_env(monkeypatch) -> None:
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)


def _client() -> tuple[WeComApiClient, FakeWeComTransport]:
    transport = FakeWeComTransport()
    return WeComApiClient(transport=transport), transport


def test_render_message_includes_owner_and_operators() -> None:
    content = render_message(
        gate="review",
        phase="plan",
        run_id="RUN-1",
        requirement="实现订单导出",
        repo="demo",
        operators=["sunxianshun", "wangxiaofei"],
        action="接受或修改 rerun",
        summary="plan.solution 已完成",
    )
    assert "🔔 工作流需要人工处理" in content
    assert "👤 开启者：@sunxianshun" in content
    assert "🔑 授权操作者：@sunxianshun @wangxiaofei" in content
    assert "Review Gate（plan 阶段）" in content
    assert "RUN-1" in content
    assert "接受或修改 rerun" in content
    assert "请勿直接操作本工作流" in content


def test_notify_sends_once_then_dedups(tmp_path: Path, monkeypatch) -> None:
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo,
        source_revision="abc123",
        requirement="实现订单导出",
        operators=("sunxianshun", "wangxiaofei"),
    )
    run_id = state.run_id
    client, transport = _client()

    first = notify_command(
        repo, run_id=run_id, gate="review", phase="plan",
        action="接受或修改 rerun", summary="plan.solution 已完成", client=client,
    )
    assert first["sent"] is True
    assert first["dedup"] == "new"

    second = notify_command(
        repo, run_id=run_id, gate="review", phase="plan",
        action="接受或修改 rerun", summary="plan.solution 已完成", client=client,
    )
    assert second["sent"] is False
    assert second["dedup"] == "repeat"

    third = notify_command(
        repo, run_id=run_id, gate="review", phase="plan",
        action="修改了 rerun 内容", summary="plan.solution 已更新", client=client,
    )
    assert third["sent"] is True
    assert third["dedup"] == "content_changed"

    assert len(transport.sent) == 2


def test_notify_dry_run_does_not_send(tmp_path: Path, monkeypatch) -> None:
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(repo, source_revision="abc123", requirement="x")
    run_id = state.run_id
    client, transport = _client()

    result = notify_command(
        repo, run_id=run_id, gate="blocked", phase="implement",
        action="resume 或 abort", summary="环境失败", client=client, dry_run=True,
    )
    assert result["sent"] is False
    assert result["dry_run"] is True
    assert transport.sent == []


def test_notify_noop_when_disabled(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
    repo = tmp_path
    client, _ = _client()
    result = notify_command(
        repo, run_id="RUN-1", gate="review", action="x", client=client,
    )
    assert result["sent"] is False
    assert result["reason"] == "not_enabled"


def test_notify_gate_not_configured_is_noop(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  gates: [review]\n",
        encoding="utf-8",
    )
    repo = tmp_path
    client, _ = _client()
    result = notify_command(
        repo, run_id="RUN-1", gate="blocked", action="x", client=client,
    )
    assert result["sent"] is False
    assert result["reason"] == "gate_not_configured"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/wecom/test_notify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ai_workflow.wecom.notify'`

- [ ] **Step 3: Implement `notify.py`**

Create `src/ai_workflow/wecom/notify.py`:

```python
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.workflow.service import WorkflowService

_GATE_LABELS = {
    "review": "Review Gate",
    "blocked": "Blocked",
    "governance": "Knowledge Governance",
    "git_handoff": "Git Handoff",
}

_NOTIFY_DIRNAME = "notifications"


def notification_log_path(repo_root: Path, run_id: str) -> Path:
    return (repo_root / ".ai-workflow" / _NOTIFY_DIRNAME / f"{run_id}.json").resolve()


def render_message(
    *,
    gate: str,
    phase: str | None,
    run_id: str,
    requirement: str,
    repo: str,
    operators: list[str],
    action: str,
    summary: str,
) -> str:
    label = _GATE_LABELS.get(gate, gate)
    type_line = f"{label}（{phase} 阶段）" if phase else label
    creator = operators[0] if operators else "未知"
    operator_line = " ".join(f"@{op}" for op in operators) or "@无"
    summary_block = f"\n{summary}" if summary else ""
    return (
        "**🔔 工作流需要人工处理**\n\n"
        f"👤 开启者：@{creator}\n"
        f"🔑 授权操作者：{operator_line}\n"
        f"📌 类型：{type_line}\n"
        f"🆔 Run ID：`{run_id}`\n"
        f"🏷 摘要：{requirement}\n"
        f"📁 仓库：{repo}\n"
        f"{summary_block}\n\n"
        f"请授权操作者处理：{action}\n"
        "其他成员仅收到通知，请勿直接操作本工作流。"
    )


def _content_digest(*, gate: str, phase: str | None, content: str) -> str:
    payload = json.dumps(
        {"gate": gate, "phase": phase, "content": content},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_log(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A truncated/corrupt log means "no prior notifications": never let a
        # broken dedup log block or crash the notify step.
        return {}
    return data if isinstance(data, dict) else {}


def _client_for_webhook() -> WeComApiClient:
    # Webhook messages carry their key in the URL: the client is only a thin
    # holder for the transport.
    return WeComApiClient()


def _webhook_url(config: RepositoryConfig) -> str | None:
    if config.wecom_webhook_url_env is None:
        return None
    url = os.environ.get(config.wecom_webhook_url_env, "").strip()
    if not url:
        raise AppError(
            "wecom_not_configured",
            "WeCom webhook URL is not configured in the environment",
        )
    return url


def notify_command(
    repo_root: Path,
    *,
    run_id: str,
    gate: str,
    action: str,
    summary: str = "",
    phase: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    client: WeComApiClient | None = None,
) -> dict[str, object]:
    if gate not in _GATE_LABELS:
        raise AppError("wecom_invalid_gate", f"unknown gate: {gate}")
    config = RepositoryConfig.load(repo_root)
    if not config.wecom_enabled:
        return {"sent": False, "reason": "not_enabled"}
    if gate not in config.wecom_gates:
        return {"sent": False, "reason": "gate_not_configured"}
    webhook_url = _webhook_url(config)
    if webhook_url is None:
        return {"sent": False, "reason": "notify_target_not_configured"}

    service = WorkflowService(repo_root)
    state = service.status(run_id)
    operators = state.artifacts.get("operators", [])
    if not isinstance(operators, list) or not all(
        isinstance(item, str) for item in operators
    ):
        raise AppError("invalid_state", "operators artifact is invalid")

    content = render_message(
        gate=gate,
        phase=phase,
        run_id=run_id,
        requirement=state.requirement,
        repo=config.repository,
        operators=operators,
        action=action,
        summary=summary,
    )
    log_path = notification_log_path(repo_root, run_id)
    log = _load_log(log_path)
    # Key the dedup log by gate plus phase so the same gate at different
    # phases (review at plan vs review at verify) never collides.
    log_key = f"{gate}:{phase or ''}"
    existing = log.get(log_key)
    digest = _content_digest(gate=gate, phase=phase, content=content)
    if not force and existing == digest:
        return {"sent": False, "dedup": "repeat", "targets": []}

    if dry_run:
        return {"sent": False, "dry_run": True, "dedup": "new", "payload": content}

    send_client = client if client is not None else _client_for_webhook()
    result = send_client.webhook_send(content=content, webhook_url=webhook_url)

    log[log_key] = digest
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: crash mid-write must not corrupt the dedup log.
    temporary = log_path.with_name(f".{log_path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(log_path)
    # A first send is "new"; a resend after content changed is "content_changed";
    # a forced resend of identical content counts as a fresh "new" send.
    dedup = "new" if force or existing is None else "content_changed"
    return {
        "sent": True,
        "dedup": dedup,
        "result": result,
        "webhook": webhook_url,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/wecom/test_notify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_workflow/wecom/notify.py tests/unit/wecom/test_notify.py
git commit -m "feat: add idempotent WeCom webhook notify command"
```

---

### Task 5: `ai-workflow wecom notify` CLI command

**Files:**
- Modify: `src/ai_workflow/cli.py` (parser ~line 108 region; dispatch after `config` branch ~line 204)
- Test: `tests/contract/test_wecom_notify_cli.py`

**Interfaces:**
- Consumes: `notify_command(repo_root, *, run_id, gate, action, summary, phase, force, dry_run, client=None)`.
- Produces: top-level `ai-workflow wecom notify --repo --run-id --gate --action [--summary] [--phase] [--force] [--dry-run]` printing a JSON envelope `{"ok": true, "data": {...}}`.

- [ ] **Step 1: Write the failing test**

Create `tests/contract/test_wecom_notify_cli.py`:

```python
import json
import urllib.error
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.workflow.service import WorkflowService


_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123"


def _write_config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )


def test_cli_wecom_notify_dry_run(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    _write_config(tmp_path)
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x", operators=("sunxianshun",)
    )
    status, out = main(
        [
            "wecom", "notify",
            "--repo", str(tmp_path),
            "--run-id", state.run_id,
            "--gate", "review",
            "--phase", "plan",
            "--action", "接受或修改 rerun",
            "--dry-run",
        ]
    ), capsys.readouterr().out
    assert status == 0
    data = json.loads(out)["data"]
    assert data["sent"] is False
    assert data["dry_run"] is True
    assert "🔔 工作流需要人工处理" in data["payload"]


def test_cli_wecom_notify_not_enabled(tmp_path: Path, capsys) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
    state = WorkflowService().init(tmp_path, source_revision="abc123", requirement="x")
    status, out = main(
        [
            "wecom", "notify",
            "--repo", str(tmp_path),
            "--run-id", state.run_id,
            "--gate", "review",
            "--action", "x",
        ]
    ), capsys.readouterr().out
    assert status == 0
    assert json.loads(out)["data"]["reason"] == "not_enabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_wecom_notify_cli.py -v`
Expected: FAIL with a parser/usage error for the unknown `wecom` command.

- [ ] **Step 3: Add the CLI parser and dispatch**

In `src/ai_workflow/cli.py` `_parser()`, after the `wiki` parser block (find `wiki_commands = ...` and its subparsers) add:

```python
    wecom = commands.add_parser("wecom")
    wecom_commands = wecom.add_subparsers(dest="wecom_command", required=True)
    wecom_notify = wecom_commands.add_parser("notify")
    wecom_notify.add_argument("--repo", type=Path, required=True)
    wecom_notify.add_argument("--run-id", required=True)
    wecom_notify.add_argument(
        "--gate", required=True, choices=("review", "blocked", "governance", "git_handoff")
    )
    wecom_notify.add_argument("--action", required=True)
    wecom_notify.add_argument("--summary", default="")
    wecom_notify.add_argument("--phase")
    wecom_notify.add_argument("--force", action="store_true")
    wecom_notify.add_argument("--dry-run", action="store_true")
```

In `main()`, add a dispatch branch. The current structure is `if args.command == "install": ... elif args.command == "doctor": ... elif args.command == "config": ... elif args.command == "wiki": ... else: (workflow)`. Add `elif args.command == "wecom":` before the final `else`. Import `notify_command` at the top:

```python
from ai_workflow.wecom.notify import notify_command
```

Branch body:

```python
        elif args.command == "wecom":
            if args.wecom_command == "notify":
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/contract/test_wecom_notify_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_workflow/cli.py tests/contract/test_wecom_notify_cli.py
git commit -m "feat: add ai-workflow wecom notify CLI"
```

---

### Task 6: Wire the three skills to call `wecom notify` at their human gates

**Files:**
- Modify: `skills/ai-workflow-harness/SKILL.md`
- Modify: `skills/ai-git-handoff/SKILL.md`
- Modify: `skills/ai-knowledge-governance/SKILL.md`
- Create: `skills/ai-workflow-harness/references/wecom-notify.md`
- Test: `tests/contract/test_wecom_notify_skill.py`

**Interfaces:**
- Consumes: the `ai-workflow wecom notify` CLI contract from Task 5.
- Produces: three skills document that they call `ai-workflow wecom notify` at their human-gate steps; a reference doc `references/wecom-notify.md` documents the command and when to call it.

- [ ] **Step 1: Write the failing contract test**

Create `tests/contract/test_wecom_notify_skill.py`:

```python
from pathlib import Path


SKILL_DIRS = {
    "harness": Path("skills/ai-workflow-harness"),
    "git_handoff": Path("skills/ai-git-handoff"),
    "governance": Path("skills/ai-knowledge-governance"),
}


def _read(skill_key: str, relative: str = "SKILL.md") -> str:
    return (SKILL_DIRS[skill_key] / relative).read_text(encoding="utf-8")


def test_harness_skill_references_wecom_notify() -> None:
    skill = _read("harness")
    assert "ai-workflow wecom notify" in skill
    assert "Review Gate" in skill and "wecom notify" in skill


def test_git_handoff_skill_references_wecom_notify() -> None:
    skill = _read("git_handoff")
    assert "ai-workflow wecom notify" in skill


def test_governance_skill_references_wecom_notify() -> None:
    skill = _read("governance")
    assert "ai-workflow wecom notify" in skill


def test_harness_wecom_notify_reference_exists() -> None:
    ref = _read("harness", "references/wecom-notify.md")
    for phrase in (
        "ai-workflow wecom notify",
        "--gate",
        "--run-id",
        "dry-run",
        "dedup",
        "不影响主流程",
    ):
        assert phrase in ref
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_wecom_notify_skill.py -v`
Expected: FAIL (phrases missing from skills / reference missing)

- [ ] **Step 3: Add the reference doc**

Create `skills/ai-workflow-harness/references/wecom-notify.md`:

```markdown
# WeCom 人工干预通知

到达需要人工干预的节点时，调用 Helper 通知团队。通知是增强，不是依赖：失败不影响主流程。

## 命令

```bash
ai-workflow wecom notify \
  --repo <repo> \
  --run-id <run-id> \
  --gate <review|blocked|governance|git_handoff> \
  --action "<人类需要做什么>" \
  [--phase <phase>] \
  [--summary "<摘要>"] \
  [--dry-run]
```

- `--dry-run`：只打印 payload，不真发。
- 幂等：同一 gate 同一内容不重复推送；`--force` 强制重发。
- 失败只写 warning，不中断 workflow。

## 何时调用

- Review Gate：`workflow review` 返回 `human_review` 后。
- Blocked：进入 `run_blocked` 后。
- Knowledge Governance：需要人工 promote/reject/保持时。
- Git Handoff：需要人工 skip/commit/MR 时。

## 输出

`{"ok": true, "data": {"sent": bool, "dedup": "...", ...}}`。`sent=false` + `reason` 时按 no-op 处理。
```

- [ ] **Step 4: Add one-liners to the three skills**

In `skills/ai-workflow-harness/SKILL.md`, in the Review Gate and blocked sections (find the `human_review` bullet and the blocked bullet), add a line calling the command, e.g.:

```markdown
到达 `human_review` / blocked / terminal governance / git handoff 节点时，调用 `ai-workflow wecom notify --repo <repo> --run-id <run-id> --gate <gate> --action "<action>"` 通知团队；失败仅写 warning，不影响主流程。
```

Adjust the exact wording to fit each section's surrounding text. Ensure the literal string `ai-workflow wecom notify` appears.

In `skills/ai-git-handoff/SKILL.md`, add under the "Choices" or flow section a line that before presenting choices the agent calls `ai-workflow wecom notify --gate git_handoff --action "请选择 skip / commit / MR"` when a notification channel is configured.

In `skills/ai-knowledge-governance/SKILL.md`, add a line that before awaiting the human promote/reject choice the agent calls `ai-workflow wecom notify --gate governance --action "请选择 promote / reject / 保持"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/contract/test_wecom_notify_skill.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add skills/ai-workflow-harness/SKILL.md skills/ai-workflow-harness/references/wecom-notify.md \
        skills/ai-git-handoff/SKILL.md skills/ai-knowledge-governance/SKILL.md \
        tests/contract/test_wecom_notify_skill.py
git commit -m "feat: wire skills to notify WeCom at human gates"
```

---

### Task 7: End-to-end notify flow with fake transport

**Files:**
- Create: `tests/e2e/test_wecom_notify.py`

**Interfaces:**
- Consumes: Task 2 (init --operators), Task 5 (wecom notify CLI).
- Produces: e2e proof that init → (simulated gate) → wecom notify → second call dedups, all through the real CLI with a fake transport.

- [ ] **Step 1: Write the e2e test**

The CLI builds the real `WeComApiClient` via `_client_for_webhook` (env var). To inject a fake transport end-to-end, set the webhook URL env var AND monkeypatch `ai_workflow.wecom.notify._client_for_webhook` to return a client backed by `FakeWeComTransport`:

```python
import json
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.workflow.service import WorkflowService


class FakeWeComTransport:
    def __init__(self) -> None:
        self.sent = 0

    def request_json(self, method, url, *, params=None, payload=None):
        if "/webhook/send" in url:
            self.sent += 1
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


def test_wecom_notify_e2e_dedup(monkeypatch, tmp_path: Path, capsys) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "WECOM_WEBHOOK_URL",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123",
    )
    transport = FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )

    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="实现订单导出",
        operators=("sunxianshun", "wangxiaofei"),
    )
    run_id = state.run_id
    base = [
        "wecom", "notify",
        "--repo", str(tmp_path),
        "--run-id", run_id,
        "--gate", "review",
        "--phase", "plan",
        "--action", "接受或修改 rerun",
    ]

    status1, out1 = main([*base]), capsys.readouterr().out
    assert status1 == 0
    assert json.loads(out1)["data"]["sent"] is True

    status2, out2 = main([*base]), capsys.readouterr().out
    assert status2 == 0
    assert json.loads(out2)["data"]["sent"] is False
    assert json.loads(out2)["data"]["dedup"] == "repeat"

    assert transport.sent == 1
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/e2e/test_wecom_notify.py -v`
Expected: PASS

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (487 existing + new tests)

- [ ] **Step 4: Add gitignore entries and commit**

In `.gitignore`, append:

```
.ai-workflow/notifications/
.ai-workflow/runs/
```

Note: verify these paths aren't already tracked (`git ls-files .ai-workflow` should be empty). If `examples/language-neutral` tracks a `.ai-workflow` dir, keep team.yaml shared and ignore only the runtime subdirs.

```bash
git add .gitignore tests/e2e/test_wecom_notify.py
git commit -m "test: e2e WeCom notify dedup with fake transport"
```

---

## Self-Review

**Spec coverage (Plan 1 scope):** `wecom:` config block with `webhook_url_env` ✓ (Task 1); operators recorded at init with creator default ✓ (Task 2); webhook-only client (`WeComApiClient` + `webhook_send`) ✓ (Task 3); Markdown message with `👤 开启者` / `🔑 授权操作者` ✓ (Task 4); idempotent dedup `(run_id, gate, phase, content_digest)` ✓ (Task 4); soft-fail / dry-run / no-op-when-disabled / unset-webhook surfaces stderr ✓ (Task 4/5); `ai-workflow wecom notify` CLI ✓ (Task 5); three skills call the command + reference doc ✓ (Task 6); `.ai-workflow/notifications/` gitignored, run state untouched ✓ (Task 7).

**Placeholder scan:** Every step contains real code or explicit copy text. No "TBD"/"TODO".

**Type consistency:** `notify_command(repo_root, *, run_id, gate, action, summary, phase, force, dry_run, client)` is defined in Task 4 and consumed identically in Task 5. `render_message` kwargs match Task 4's test. `init(..., operators=())` matches Task 2. `WeComApiClient(*, transport)` matches Task 3.

**Deferred to Plan 2 (separate plan, not this one):** the local callback service `ai-workflow wecom serve` (crypto/signature verification, command parsing, authorization, execution of review/blocked/governance/git actions, second-confirmation for git commit/MR), which adds the `cryptography` dependency and the callback config fields (`callback_token_env`, `callback_aeskey_env`).
