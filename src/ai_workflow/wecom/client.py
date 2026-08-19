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
