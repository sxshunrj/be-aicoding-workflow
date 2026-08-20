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
    # business rejection is deterministic — never retried
    assert len(transport.calls) == 1


def test_webhook_send_retries_transient_http_errors(monkeypatch) -> None:
    """Network-level failures (connection refused, timeout, DNS) are transient:
    the client retries with backoff instead of dropping the notification — a
    human gate that went unnoticed is worse than a late ping."""
    from ai_workflow.errors import AppError as _AppError

    failures = {"failures": 2}

    def _flaky(*args, **kwargs):
        if failures["failures"] > 0:
            failures["failures"] -= 1
            raise _AppError("wecom_http_error", "connection refused")
        return {"errcode": 0, "errmsg": "ok"}

    transport = FakeWeComTransport()
    monkeypatch.setattr(transport, "request_json", _flaky)
    client = WeComApiClient(transport=transport, backoff_seconds=0)
    result = client.webhook_send(
        content="x",
        webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
    )
    assert result == {"errcode": 0, "errmsg": "ok"}


def test_webhook_send_gives_up_after_retries(monkeypatch) -> None:
    from ai_workflow.errors import AppError as _AppError

    calls = {"n": 0}

    def _always_fail(*args, **kwargs):
        calls["n"] += 1
        raise _AppError("wecom_http_error", "timeout")

    transport = FakeWeComTransport()
    monkeypatch.setattr(transport, "request_json", _always_fail)
    client = WeComApiClient(
        transport=transport, retries=2, backoff_seconds=0
    )
    with pytest.raises(AppError) as exc:
        client.webhook_send(
            content="x",
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        )
    assert exc.value.code == "wecom_http_error"
    # 1 initial attempt + 2 retries = 3 calls, then give up
    assert calls["n"] == 3

