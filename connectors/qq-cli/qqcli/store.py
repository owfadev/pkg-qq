# -*- coding: utf-8 -*-
"""Local spool, dedupe, leases, acknowledgements and sent-reply idempotency.

All state is local (~/.qq-cli); POSIX files are 0600, while Windows relies on
the user-profile ACL (see platforms/windows.py). The inbox is append-only NDJSON;
the JSON state holds dedupe keys, acknowledgements and leases. Writes are guarded
by a cross-platform file lock so a detached listener and an agent session can
share the spool safely.
"""
import contextlib
import datetime as _dt
import json
import os
import time

from . import config
from .locks import FileLock


def _now():
    return int(time.time())


def _iso(epoch=None):
    return _dt.datetime.fromtimestamp(epoch or _now(), _dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _today():
    return _dt.date.today().isoformat()


@contextlib.contextmanager
def _lock(name="state"):
    """Cross-process lock on a dedicated lock file (POSIX flock / Windows msvcrt).

    The lock file is deliberately separate from state.json / inbox/*.jsonl: the
    Windows implementation locks a byte range, so it cannot share a file that is
    opened for append and read as NDJSON.
    """
    config.ensure_home()
    path = config.home() / f".{name}.lock"
    with FileLock(path, timeout=60.0):
        yield


def load_state() -> dict:
    try:
        with open(config.state_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("seen", {})
    data.setdefault("acked", {})
    data.setdefault("leases", {})
    data.setdefault("cursor", {})
    return data


def save_state(state: dict) -> None:
    tmp = str(config.state_path()) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    config.chmod_600(tmp)
    os.replace(tmp, config.state_path())


def _prune(state: dict, retention_days: int) -> None:
    cutoff = _now() - retention_days * 86400
    for key in ("seen", "acked"):
        state[key] = {
            k: v for k, v in state.get(key, {}).items()
            if _epoch(v) is None or _epoch(v) >= cutoff
        }
    state["leases"] = {
        k: v for k, v in state.get("leases", {}).items() if int(v) > _now()
    }


def _epoch(value):
    if isinstance(value, (int, float)):
        return int(value)
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(_dt.datetime.fromisoformat(s).timestamp())
    except (TypeError, ValueError):
        return None


def _inbox_path(day: str):
    return config.home() / "inbox" / f"{day}.jsonl"


def dedupe_key(ev: dict) -> str:
    return f"{ev.get('event_id', '')}|{ev.get('msg_idx', '')}"


def append_event(ev: dict, cfg: dict) -> bool:
    """Append an event unless its dedupe key was already seen. Returns True when appended."""
    with _lock("state"):
        state = load_state()
        key = dedupe_key(ev)
        if key in state["seen"]:
            return False
        state["seen"][key] = _iso()
        _prune(state, int(cfg.get("retention_days", 7)))
        save_state(state)
        path = _inbox_path(_today())
        # The enclosing _lock("state") already serializes every spool writer
        # (listener and agent alike); no second lock on the data file is needed.
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        config.chmod_600(path)
        return True


def _read_events() -> dict:
    inbox = config.home() / "inbox"
    events = {}
    if not inbox.is_dir():
        return events
    for path in sorted(inbox.glob("*.jsonl")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    events[dedupe_key(ev)] = ev
        except OSError:
            continue
    return events


def _allowed_now(ev: dict) -> bool:
    """Re-evaluate the allowlist on read.

    Messages can arrive before the operator approves the chat. The stored flag is a
    receipt-time snapshot; approval must take effect without restarting the listener
    or rewriting the append-only spool.
    """
    kind = "user" if ev.get("kind") == "c2c" else "group"
    return config.is_allowed(kind, str(ev.get("chat_id") or ""))


def _materialize(state: dict, ev: dict) -> dict:
    key = dedupe_key(ev)
    out = dict(ev)
    out["allowed"] = _allowed_now(ev)
    out["acked"] = key in state["acked"] or ev.get("event_id") in state["acked"]
    lease = int(state["leases"].get(key, 0))
    out["claimed"] = lease > _now()
    out["claimed_until"] = _iso(lease) if lease else ""
    return out


def all_events() -> list:
    state = load_state()
    return [_materialize(state, ev) for ev in _read_events().values()]


def inbox(
    cfg: dict,
    *,
    include_blocked: bool = False,
    unread_only: bool = True,
    claim: bool = False,
    lease: int = 120,
    kind: str = "",
    limit: int = 0,
) -> list:
    now = _now()
    picked = []
    with _lock("state"):
        state = load_state()
        for ev in _read_events().values():
            if unread_only and (dedupe_key(ev) in state["acked"] or ev.get("event_id") in state["acked"]):
                continue
            if not include_blocked and not _allowed_now(ev):
                continue
            if kind and ev.get("kind") != kind:
                continue
            if int(state["leases"].get(dedupe_key(ev), 0)) > now:
                continue
            picked.append(_materialize(state, ev))

        def sort_key(ev):
            expired = int(ev.get("deadline_epoch") or 0) <= now
            return (1 if expired else 0, int(ev.get("deadline_epoch") or 0), ev.get("received_at", ""))

        picked.sort(key=sort_key)
        if limit and limit > 0:
            picked = picked[:limit]
        if claim and picked:
            until = now + max(30, int(lease))
            for ev in picked:
                state["leases"][dedupe_key(ev)] = until
                ev["claimed"] = True
                ev["claimed_until"] = _iso(until)
            save_state(state)
    return picked


def ack(event_ids) -> int:
    ids = [str(x) for x in event_ids if str(x)]
    if not ids:
        return 0
    with _lock("state"):
        state = load_state()
        now_iso = _iso()
        count = 0
        for ev in _read_events().values():
            if ev.get("event_id") in ids or dedupe_key(ev) in ids:
                state["acked"][dedupe_key(ev)] = now_iso
                state["leases"].pop(dedupe_key(ev), None)
                count += 1
        save_state(state)
        return count


def ack_all() -> int:
    with _lock("state"):
        state = load_state()
        now_iso = _iso()
        count = 0
        for ev in _read_events().values():
            if _allowed_now(ev) and dedupe_key(ev) not in state["acked"]:
                state["acked"][dedupe_key(ev)] = now_iso
                state["leases"].pop(dedupe_key(ev), None)
                count += 1
        save_state(state)
        return count


def release(event_ids) -> int:
    ids = [str(x) for x in event_ids if str(x)]
    with _lock("state"):
        state = load_state()
        count = 0
        for ev in _read_events().values():
            if ev.get("event_id") in ids or dedupe_key(ev) in ids:
                state["leases"].pop(dedupe_key(ev), None)
                count += 1
        save_state(state)
        return count


def find_event(event_id: str):
    for ev in _read_events().values():
        if ev.get("event_id") == event_id:
            return _materialize(load_state(), ev)
    return None


def requests() -> list:
    grouped = {}
    for ev in _read_events().values():
        if _allowed_now(ev):
            continue
        key = (ev.get("kind"), ev.get("chat_id"))
        g = grouped.setdefault(
            key,
            {
                "kind": ev.get("kind"),
                "chat_id": ev.get("chat_id"),
                "label": ev.get("chat_label", ""),
                "count": 0,
                "first_seen": ev.get("received_at", ""),
                "last_seen": ev.get("received_at", ""),
                "last_content": "",
            },
        )
        g["count"] += 1
        if ev.get("received_at", "") >= g["last_seen"]:
            g["last_seen"] = ev.get("received_at", "")
            g["last_content"] = str(ev.get("content", ""))[:80]
    return sorted(grouped.values(), key=lambda x: x["last_seen"], reverse=True)


def sent_for(event_id: str) -> list:
    out = []
    try:
        with open(config.sent_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event_id") == event_id:
                    out.append(rec)
    except OSError:
        pass
    return out


def record_sent(event_id: str, kind: str, seq: int, message_id: str, text_chars: int) -> None:
    with _lock("sent"):
        rec = {
            "event_id": event_id,
            "kind": kind,
            "seq": int(seq),
            "message_id": message_id,
            "at": _iso(),
            "chars": int(text_chars),
        }
        # As in append_event: _lock("sent") already serializes this writer.
        with open(config.sent_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        config.chmod_600(config.sent_path())


def next_seq(event_id: str) -> int:
    seqs = [int(r.get("seq") or 0) for r in sent_for(event_id)]
    return (max(seqs) if seqs else 0) + 1


def counts() -> dict:
    state = load_state()
    now = _now()
    total = unread = expired = blocked = 0
    for ev in _read_events().values():
        total += 1
        key = dedupe_key(ev)
        if key in state["acked"] or ev.get("event_id") in state["acked"]:
            continue
        unread += 1
        if not _allowed_now(ev):
            blocked += 1
        if int(ev.get("deadline_epoch") or 0) <= now:
            expired += 1
    return {"total": total, "unread": unread, "expired": expired, "blocked": blocked}


def purge(days: int) -> dict:
    cutoff = _dt.date.today() - _dt.timedelta(days=max(0, int(days)))
    removed = 0
    inbox = config.home() / "inbox"
    if inbox.is_dir():
        for path in inbox.glob("*.jsonl"):
            try:
                day = _dt.date.fromisoformat(path.stem)
            except ValueError:
                continue
            if day < cutoff:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
    with _lock("state"):
        state = load_state()
        _prune(state, max(0, int(days)))
        save_state(state)
    return {"removed_files": removed, "kept_days": max(0, int(days))}


def load_cursor() -> dict:
    return dict(load_state().get("cursor") or {})


def update_cursor(*, session_id=None, seq=None) -> dict:
    with _lock("state"):
        state = load_state()
        cur = state.setdefault("cursor", {})
        if session_id is not None:
            cur["session_id"] = str(session_id)
        if seq is not None:
            cur["seq"] = int(seq)
        cur["updated_at"] = _iso()
        save_state(state)
        return dict(cur)


def clear_cursor() -> None:
    with _lock("state"):
        state = load_state()
        state["cursor"] = {}
        save_state(state)

