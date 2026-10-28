# -*- coding: utf-8 -*-
"""Normalize official QQ Bot events into one stable local shape.

The raw event is untrusted data. This module only extracts identifiers and text;
it never interprets instructions, downloads attachments, or follows links.
Raw openids stay in the local event record; the agent-facing view (public_view)
carries an alias or a salted short hash instead.
"""
import datetime as _dt
import hashlib
import json
import secrets
from pathlib import Path

from . import config

C2C_EVENT = "C2C_MESSAGE_CREATE"
GROUP_AT_EVENT = "GROUP_AT_MESSAGE_CREATE"


def _parse_ts(value):
    if not value:
        return None
    s = str(value).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return _dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _iso(epoch):
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _msg_idx(d: dict) -> str:
    scene = d.get("message_scene") or {}
    ext = scene.get("ext") if isinstance(scene, dict) else None
    if isinstance(ext, list):
        for item in ext:
            text = str(item)
            if text.startswith("msg_idx="):
                return text.split("=", 1)[1]
    if isinstance(ext, dict):
        return str(ext.get("msg_idx") or "")
    return str(d.get("msg_idx") or "")


def _salt() -> str:
    path = config.home() / "salt"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    value = secrets.token_hex(16)
    try:
        config.ensure_home()
        path.write_text(value + "\n", encoding="utf-8")
        config.chmod_600(path)
    except OSError:
        pass
    return value


def _ref(kind: str, chat_id: str) -> str:
    digest = hashlib.sha256((_salt() + "|" + chat_id).encode("utf-8")).hexdigest()[:10]
    return f"{kind}-{digest}"


def event_type(payload: dict) -> str:
    t = payload.get("t") or payload.get("type")
    if t:
        return str(t)
    d = payload.get("d") if isinstance(payload.get("d"), dict) else payload
    if not isinstance(d, dict):
        return ""
    if d.get("group_openid"):
        return GROUP_AT_EVENT
    author = d.get("author") if isinstance(d.get("author"), dict) else {}
    if author.get("user_openid"):
        return C2C_EVENT
    return ""


def normalize(payload: dict, cfg: dict) -> dict:
    """Return a normalized event, or raise ValueError for unsupported/empty input."""
    t = event_type(payload)
    d = payload.get("d") if isinstance(payload.get("d"), dict) else payload
    if not isinstance(d, dict):
        raise ValueError("event payload is not an object")
    author = d.get("author") if isinstance(d.get("author"), dict) else {}

    kind = ""
    chat_id = ""
    sender_id = ""
    if t == C2C_EVENT or (not t and author.get("user_openid")):
        kind = "c2c"
        chat_id = str(author.get("user_openid") or "")
        sender_id = chat_id
    elif t == GROUP_AT_EVENT or (not t and d.get("group_openid")):
        kind = "group"
        chat_id = str(d.get("group_openid") or "")
        sender_id = str(author.get("member_openid") or "")
    else:
        raise ValueError(f"unsupported event type: {t or 'unknown'}")

    if not chat_id:
        raise ValueError("event has no chat identifier")
    if author.get("bot"):
        raise ValueError("ignoring bot-authored event")

    content = str(d.get("content") or "").strip()
    if not content:
        raise ValueError("empty message content")

    msg_id = str(d.get("id") or payload.get("id") or "")
    event_id = str(payload.get("id") or msg_id)
    if not event_id:
        raise ValueError("event has no id")

    ts_epoch = _parse_ts(d.get("timestamp"))
    received = _dt.datetime.now(_dt.timezone.utc).timestamp()
    window = cfg.get("group_passive_seconds" if kind == "group" else "c2c_passive_seconds", 300)
    base = ts_epoch if ts_epoch is not None else received
    deadline = base + int(window)

    try:
        message_type = int(d.get("message_type") or 0)
    except (TypeError, ValueError):
        message_type = 0

    label = config.entry_label("user" if kind == "c2c" else "group", chat_id)
    ref = label or _ref(kind, chat_id)
    return {
        "event_id": event_id,
        "kind": kind,
        "chat_id": chat_id,
        "chat_ref": ref,
        "chat_label": label,
        "sender_id": sender_id,
        "sender_ref": config.entry_label("user", sender_id) or _ref("user", sender_id),
        "content": content,
        "timestamp": str(d.get("timestamp") or ""),
        "received_at": _iso(received),
        "msg_id": msg_id,
        "msg_idx": _msg_idx(d),
        "message_type": message_type,
        "allowed": config.is_allowed("user" if kind == "c2c" else "group", chat_id),
        "deadline": _iso(deadline),
        "deadline_epoch": int(deadline),
        "event_type": t,
        "attachments": [
            {
                "filename": str(a.get("filename") or ""),
                "content_type": str(a.get("content_type") or ""),
                "size": a.get("size"),
            }
            for a in (d.get("attachments") or [])
            if isinstance(a, dict)
        ],
    }


def public_view(ev: dict, now=None) -> dict:
    """Agent-facing view: no raw openids, no passive-reply internals."""
    now = now or _dt.datetime.now(_dt.timezone.utc).timestamp()
    deadline = int(ev.get("deadline_epoch") or 0)
    return {
        "event_id": ev.get("event_id", ""),
        "kind": ev.get("kind", ""),
        "chat": ev.get("chat_ref") or ev.get("chat_label") or "",
        "sender": ev.get("sender_ref") or "",
        "content": ev.get("content", ""),
        "timestamp": ev.get("timestamp", ""),
        "received_at": ev.get("received_at", ""),
        "message_type": ev.get("message_type", 0),
        "allowed": bool(ev.get("allowed")),
        "deadline": ev.get("deadline", ""),
        "deadline_in": int(deadline - now),
        "expired": deadline <= now,
        "acked": bool(ev.get("acked")),
        "claimed": bool(ev.get("claimed")),
    }


def load_event_file(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
