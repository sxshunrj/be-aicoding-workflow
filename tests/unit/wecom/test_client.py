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


def test_webhook_send_posts_without_access_token() -> None:
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
