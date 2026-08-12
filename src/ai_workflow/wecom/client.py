from __future__ import annotations

import json
import time
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ai_workflow.errors import AppError

BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"


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
        self,
        corpid: str,
        corpsecret: str,
        agentid: int,
        *,
        transport: WeComTransport | None = None,
        clock=None,
    ) -> None:
        self.corpid = corpid
        self.corpsecret = corpsecret
        self.agentid = agentid
        self._transport = transport if transport is not None else UrllibTransport()
        self._clock = clock or time.time
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._tag_cache: dict[str, int] = {}

    def access_token(self) -> str:
        now = self._clock()
        if self._token is not None and now < self._token_expires_at:
            return self._token
        data = self._transport.request_json(
            "GET",
            f"{BASE_URL}/gettoken",
            params={"corpid": self.corpid, "corpsecret": self.corpsecret},
        )
        if data.get("errcode", 0) != 0:
            raise AppError(
                "wecom_api_error",
                f"gettoken failed: {data.get('errmsg')}",
            )
        self._token = str(data["access_token"])
        self._token_expires_at = now + int(data.get("expires_in", 7200)) - 60
        return self._token

    def resolve_tag(self, tag_name: str) -> int:
        cached = self._tag_cache.get(tag_name)
        if cached is not None:
            return cached
        data = self._transport.request_json(
            "GET",
            f"{BASE_URL}/tag/list",
            params={"access_token": self.access_token()},
        )
        if data.get("errcode", 0) != 0:
            raise AppError(
                "wecom_api_error", f"tag/list failed: {data.get('errmsg')}"
            )
        for item in data.get("taglist", []):
            if item.get("tagname") == tag_name:
                tag_id = int(item["tagid"])
                self._tag_cache[tag_name] = tag_id
                return tag_id
        raise AppError("wecom_tag_not_found", f"tag not found: {tag_name}")

    def send_message(
        self,
        *,
        content: str,
        msgtype: str = "markdown",
        tag_id: int | None = None,
        to_user: str | None = None,
    ) -> dict[str, object]:
        if tag_id is None and to_user is None:
            raise AppError("wecom_invalid_target", "either tag_id or to_user is required")
        payload: dict[str, object] = {
            "agentid": self.agentid,
            "msgtype": msgtype,
            msgtype: {"content": content},
            "safe": 0,
        }
        if tag_id is not None:
            payload["totag"] = tag_id
        if to_user is not None:
            payload["touser"] = to_user
        data = self._transport.request_json(
            "POST",
            f"{BASE_URL}/message/send",
            params={"access_token": self.access_token()},
            payload=payload,
        )
        if data.get("errcode", 0) != 0:
            raise AppError(
                "wecom_api_error",
                f"message/send failed: {data.get('errmsg')}",
            )
        return data
