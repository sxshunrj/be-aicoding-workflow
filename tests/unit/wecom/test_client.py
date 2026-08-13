from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta

import pytest

from ai_workflow.errors import AppError
from ai_workflow.wecom.client import UrllibTransport, WeComApiClient, WeComTransport


class FakeWeComTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.tokens: list[dict[str, object]] = [{"errcode": 0, "access_token": "TOK-1", "expires_in": 7200}]
        self.taglist: list[dict[str, object]] = [
            {"tagid": 7, "tagname": "工作流通知组"},
            {"tagid": 9, "tagname": "other"},
        ]
        self.send_result: dict[str, object] = {"errcode": 0, "errmsg": "ok"}

    def request_json(self, method: str, url: str, *, params=None, payload=None) -> dict[str, object]:
        self.calls.append((method, url, payload))
        if url.endswith("/gettoken"):
            return self.tokens.pop(0)
        if url.endswith("/tag/list"):
            return {"errcode": 0, "taglist": self.taglist}
        if url.endswith("/message/send"):
            if params and params.get("debug") == "1":
                raise AppError("wecom_api_error", "debug failure")
            return self.send_result
        if "/webhook/send" in url:
            if params and params.get("debug") == "1":
                raise AppError("wecom_api_error", "debug failure")
            return self.send_result
        raise AssertionError(f"unexpected url: {url}")


def test_access_token_cached_then_refreshed() -> None:
    transport = FakeWeComTransport()
    client = WeComApiClient("corp", "secret", 1000002, transport=transport)
    first = client.access_token()
    second = client.access_token()
    assert first == "TOK-1"
    assert second == "TOK-1"
    # only one gettoken call for the cached token
    assert sum(1 for c in transport.calls if c[0] == "GET" and c[1].endswith("/gettoken")) == 1


def test_resolve_tag_finds_tagname() -> None:
    transport = FakeWeComTransport()
    client = WeComApiClient("corp", "secret", 1000002, transport=transport)
    assert client.resolve_tag("工作流通知组") == 7


def test_resolve_tag_missing_raises() -> None:
    transport = FakeWeComTransport()
    client = WeComApiClient("corp", "secret", 1000002, transport=transport)
    with pytest.raises(AppError) as exc:
        client.resolve_tag("不存在")
    assert exc.value.code == "wecom_tag_not_found"


def test_send_message_posts_to_tag() -> None:
    transport = FakeWeComTransport()
    client = WeComApiClient("corp", "secret", 1000002, transport=transport)
    result = client.send_message(content="**hi**", msgtype="markdown", tag_id=7)
    assert result == {"errcode": 0, "errmsg": "ok"}
    _, url, payload = transport.calls[-1]
    assert url.endswith("/message/send")
    assert payload["totag"] == 7
    assert payload["agentid"] == 1000002
    assert payload["msgtype"] == "markdown"
    assert payload["markdown"]["content"] == "**hi**"


def test_send_message_raises_on_errcode() -> None:
    transport = FakeWeComTransport()
    transport.send_result = {"errcode": 81013, "errmsg": "user & party & tag all invalid"}
    client = WeComApiClient("corp", "secret", 1000002, transport=transport)
    with pytest.raises(AppError) as exc:
        client.send_message(content="x", tag_id=7)
    assert exc.value.code == "wecom_api_error"


def test_urllib_transport_converts_urlerror_to_apperror(monkeypatch) -> None:
    def _offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("ai_workflow.wecom.client.urlopen", _offline)
    transport = UrllibTransport()
    with pytest.raises(AppError) as exc:
        transport.request_json("GET", "https://example.com/gettoken")
    assert exc.value.code == "wecom_http_error"
    assert "offline" in exc.value.message


def test_urllib_transport_converts_timeout_to_apperror(monkeypatch) -> None:
    import socket

    def _timeout(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr("ai_workflow.wecom.client.urlopen", _timeout)
    transport = UrllibTransport()
    with pytest.raises(AppError) as exc:
        transport.request_json("GET", "https://example.com/gettoken")
    assert exc.value.code == "wecom_http_error"


def test_access_token_missing_token_raises() -> None:
    class MissingTokenTransport:
        def request_json(self, method: str, url: str, *, params=None, payload=None):
            return {"errcode": 0}

    client = WeComApiClient("corp", "secret", 1000002, transport=MissingTokenTransport())
    with pytest.raises(AppError) as exc:
        client.access_token()
    assert exc.value.code == "wecom_api_error"


def test_webhook_send_posts_without_access_token() -> None:
    transport = FakeWeComTransport()
    client = WeComApiClient("corp", "secret", 1000002, transport=transport)
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123"
    result = client.webhook_send(content="**hi**", webhook_url=webhook)
    assert result == {"errcode": 0, "errmsg": "ok"}
    method, url, payload = transport.calls[-1]
    assert method == "POST"
    assert url == webhook  # exact webhook URL, key included, no access_token
    assert payload["msgtype"] == "markdown"
    assert payload["markdown"]["content"] == "**hi**"
    # webhook send must not hit gettoken (no access_token involved)
    assert not any(c[0] == "GET" and c[1].endswith("/gettoken") for c in transport.calls)
