# -*- coding: utf-8 -*-
"""Official QQ Bot HTTP surface: gateway discovery and passive replies.

Only the two message sends are implemented; there is no proactive/active send,
no recall, and no attachment download. The connector's write surface is exactly
"reply to a stored event".
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

INTENT_GROUP_AND_C2C = 1 << 25

KNOWN_ERRORS = {
    "40034005": "passive reply msg_id expired",
    "40034024": "invalid msg_id or event_id",
    "40034028": "passive reply window expired",
    "40034029": "keyboard rows/columns over limit",
    "40034100": "active message frequency limit",
    "40034101": "bot is not a member of the group",
    "40034128": "passive reply time or count exceeded",
    "40054005": "duplicate msg_id + msg_seq",
    "40054007": "message length over limit",
    "40054010": "URL not allowed (register it in the bot console)",
    "40054016": "bot offline",
}


class ApiError(RuntimeError):
    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.code = str(code) if code is not None else ""
        self.status = status


class TokenExpired(ApiError):
    pass


class RateLimited(ApiError):
    def __init__(self, message, retry_after=1.0):
        super().__init__(message, status=429)
        self.retry_after = retry_after


def _request(method: str, url: str, token: str, body=None, timeout: int = 20):
    data = None
    headers = {"Authorization": f"QQBot {token}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if status == 401:
            raise TokenExpired("access token rejected", status=401)
        if status == 429:
            try:
                delay = float(retry_after) if retry_after else 1.0
            except ValueError:
                delay = 1.0
            raise RateLimited("rate limited", retry_after=min(10.0, delay))
        raise ApiError(f"HTTP {status}: {raw[:300]}", status=status)
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        raise ApiError(f"non-JSON response: {raw[:300]}", status=status)
    code = payload.get("err_code", payload.get("code", 0))
    if code not in (0, "0", None):
        hint = KNOWN_ERRORS.get(str(code), "")
        msg = payload.get("message") or payload.get("msg") or "api error"
        raise ApiError(f"{code}: {msg}{(' — ' + hint) if hint else ''}", code=code, status=status)
    return payload


def get_gateway(token: str, cfg: dict) -> str:
    base = config.api_base(cfg)
    last = None
    for path in ("/gateway", "/gateway/bot"):
        try:
            data = _request("GET", base + path, token)
            url = data.get("url")
            if url:
                return str(url)
        except ApiError as exc:
            last = exc
            continue
    raise ApiError(f"gateway discovery failed: {last}")


def _send_url(cfg: dict, kind: str, chat_id: str) -> str:
    base = config.api_base(cfg)
    quoted = urllib.parse.quote(chat_id, safe="")
    if kind == "group":
        return f"{base}/v2/groups/{quoted}/messages"
    return f"{base}/v2/users/{quoted}/messages"


def send_passive(token: str, cfg: dict, kind: str, chat_id: str, content: str, msg_id: str, msg_seq: int):
    body = {
        "content": content,
        "msg_type": 0,
        "msg_id": msg_id,
        "msg_seq": int(msg_seq),
    }
    last = None
    for attempt in range(3):
        try:
            return _request("POST", _send_url(cfg, kind, chat_id), token, body)
        except RateLimited as exc:
            last = exc
            time.sleep(exc.retry_after)
        except ApiError:
            raise
    raise last or ApiError("send failed")


def _guard_wikilinks(text: str, start: int, end: int) -> int:
    """Move a hard split point out of an unterminated [[...]] span."""
    open_idx = text.rfind("[[", start, end)
    close_idx = text.rfind("]]", start, end)
    if open_idx > close_idx and open_idx > start:
        return open_idx
    return end


def _hard_split(text: str, limit: int):
    out = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            end = _guard_wikilinks(text, start, end)
            if end <= start:  # pathological: a wikilink longer than the limit
                end = min(start + limit, len(text))
        out.append(text[start:end])
        start = end
    return out


def split_text(text: str, max_chars: int = 1800, max_parts: int = 5):
    text = (text or "").strip()
    if not text:
        return []
    max_chars = max(200, int(max_chars))
    max_parts = max(1, int(max_parts))

    blocks = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            blocks.append(para)
        else:
            for line in para.splitlines():
                line = line.strip()
                if not line:
                    continue
                if len(line) <= max_chars:
                    blocks.append(line)
                else:
                    blocks.extend(_hard_split(line, max_chars))

    parts, current = [], ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = block
    if current:
        parts.append(current)

    if len(parts) > max_parts:
        parts = parts[:max_parts]
        suffix = "\n……（内容较长，已截断）"
        room = max(1, max_chars - len(suffix))
        parts[-1] = parts[-1][:room].rstrip() + suffix
    if len(parts) > 1:
        n = len(parts)
        parts = [f"({i}/{n}) {p}" for i, p in enumerate(parts, 1)]
    return parts
