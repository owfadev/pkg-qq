# -*- coding: utf-8 -*-
"""qq-cli command surface.

Read: the official QQ event stream (C2C private, group @) and local spool state.
Write: passive replies to QQ, the local spool/config, and nothing else.
Never: wiki content, .meta/, .agents/, vault/, or any agent/LLM call.
"""
import argparse
import getpass
import json
import os
import sys
import time

from . import __version__, api, auth, config, gateway, normalize, store
from .platforms import current as current_platform


# --------------------------------------------------------------------------- helpers

def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _pid_alive(pid: int) -> bool:
    return current_platform().pid_alive(pid)


def _read_pid() -> int:
    try:
        return int(config.pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _listener_state() -> dict:
    pid = _read_pid()
    return {"pid": pid, "alive": _pid_alive(pid), "log": str(config.log_path())}


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not os.isatty(0):
        print("[error] confirmation required: re-run with --yes", file=sys.stderr)
        return False
    return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")


def _read_text_file(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- commands

def cmd_version(args, cfg):
    print(f"qq-cli {__version__}")
    return 0


def cmd_login(args, cfg):
    app_id = config.resolve_app_id(cfg, args.app_id)
    if not app_id:
        print("[error] app id unavailable: pass --app-id or set QQ_CLI_APP_ID", file=sys.stderr)
        return 1
    try:
        secret = config.resolve_client_secret(cfg)
        token, expires = auth.fetch_app_token(cfg, app_id, secret)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    now = int(time.time())
    config.update_config(app_id=app_id)
    current = config.load_config()
    if current.pop("client_secret", None) is not None:
        config.save_config(current)  # migrate a legacy secret out of config.json
    if not args.no_store:
        config.save_credentials(app_id, secret)
    config.save_token(
        {"app_id": app_id, "access_token": token, "expires_at": now + expires, "obtained_at": now}
    )
    gateway_url = ""
    try:
        gateway_url = api.get_gateway(token, cfg)
    except Exception as exc:
        print(f"[warning] token ok but gateway discovery failed: {exc}", file=sys.stderr)
    print(f"[login] app_id={app_id} token_expires_in={expires}s secret_stored={not args.no_store}")
    if gateway_url:
        print(f"[login] gateway={gateway_url}")
    return 0


def cmd_logout(args, cfg):
    config.clear_token()
    if args.forget_secret:
        config.clear_credentials()
        cfg.pop("client_secret", None)
        config.save_config(cfg)
    print("[logout] token cleared" + ("; stored client secret forgotten" if args.forget_secret else ""))
    return 0


def cmd_secret(args, cfg):
    """Store/clear the AppID + ClientSecret locally (0600), like bb-cli's stored login.

    The secret is never printed and never accepted from the chat; `set` reads a file,
    stdin, or an interactive prompt in the operator's own terminal.
    """
    action = args.action
    if action == "status":
        cred = config.load_credentials()
        data = {
            "stored": config.credentials_stored(),
            "app_id": cred.get("app_id", ""),
            "path": str(config.credentials_path()),
        }
        if args.format == "json":
            _print_json(data)
        else:
            print(f"stored : {data['stored']}")
            print(f"app_id : {data['app_id'] or '(unset)'}")
            print(f"path   : {data['path']}")
        return 0
    if action == "clear":
        config.clear_credentials()
        print("[secret] cleared")
        return 0

    app_id = config.resolve_app_id(cfg, args.app_id)
    if not app_id:
        print("[error] app id unavailable: pass --app-id or set QQ_CLI_APP_ID", file=sys.stderr)
        return 1
    try:
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                secret = f.read().strip()
        elif args.stdin:
            secret = sys.stdin.read().strip()
        elif os.isatty(0):
            secret = getpass.getpass("QQ Bot ClientSecret: ").strip()
        else:
            print(
                "[error] no TTY and no --file/--stdin: run this command in a terminal once",
                file=sys.stderr,
            )
            return 1
    except OSError as exc:
        print(f"[error] cannot read secret: {exc}", file=sys.stderr)
        return 1
    if not secret:
        print("[error] empty secret", file=sys.stderr)
        return 1
    try:
        token, expires = auth.fetch_app_token(cfg, app_id, secret)
    except Exception as exc:
        print(f"[error] credential check failed: {exc}", file=sys.stderr)
        return 1
    config.save_credentials(app_id, secret)
    config.update_config(app_id=app_id)
    now = int(time.time())
    config.save_token(
        {"app_id": app_id, "access_token": token, "expires_at": now + expires, "obtained_at": now}
    )
    print(f"[secret] stored 0600 at {config.credentials_path()} (app_id={app_id}, token_expires_in={expires}s)")
    return 0


def cmd_ensure(args, cfg):
    """Idempotent auth check used by the agent when the user says “登录qq”.

    With stored credentials this needs no TTY: it refreshes the token and checks the
    gateway. Without credentials it fails with a one-line instruction.
    """
    app_id = config.resolve_app_id(cfg)
    if not app_id:
        print(
            "[error] app id unavailable: run `qq-cli secret set --app-id <AppID>` once in a terminal",
            file=sys.stderr,
        )
        return 1
    try:
        token = auth.get_token(cfg)
        gateway_url = api.get_gateway(token, cfg)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    status = auth.token_status()
    data = {
        "authenticated": True,
        "app_id": app_id,
        "token_remaining": status.get("remaining", 0),
        "gateway": gateway_url,
        "credentials_stored": config.credentials_stored(),
    }
    if args.format == "json":
        _print_json(data)
    else:
        print(f"authenticated : yes")
        print(f"app_id        : {app_id}")
        print(f"token         : {data['token_remaining']}s left")
        print(f"gateway       : {gateway_url}")
        print(f"credentials   : {'stored' if data['credentials_stored'] else 'env/one-shot only'}")
    return 0


def cmd_status(args, cfg):
    tok = auth.token_status()
    counts = store.counts()
    allow = config.load_allowlist()
    data = {
        "app_id": config.resolve_app_id(cfg),
        "api_base": config.api_base(cfg),
        "token": tok,
        "credentials_stored": config.credentials_stored(),
        "listener": _listener_state(),
        "inbox": counts,
        "allowlist": {
            "users": len(allow.get("users", {})),
            "groups": len(allow.get("groups", {})),
        },
        "home": str(config.home()),
    }
    if args.format == "json":
        _print_json(data)
    else:
        print(f"app_id     : {data['app_id'] or '(unset)'}")
        print(f"api_base   : {data['api_base']}")
        print(f"token      : {'ok, %ss left' % tok['remaining'] if tok['present'] and not tok.get('expired') else 'missing/expired'}")
        print(f"credentials: {'stored (0600)' if data['credentials_stored'] else 'not stored (env/one-shot only)'}")
        print(f"listener   : {'running pid %s' % data['listener']['pid'] if data['listener']['alive'] else 'stopped'}")
        print(f"inbox      : total {counts['total']}, unread {counts['unread']}, expired {counts['expired']}, blocked {counts['blocked']}")
        print(f"allowlist  : users {data['allowlist']['users']}, groups {data['allowlist']['groups']}")
        print(f"home       : {data['home']}")
    return 0


def cmd_whoami(args, cfg):
    allow = config.load_allowlist()
    data = {
        "app_id": config.resolve_app_id(cfg),
        "api_base": config.api_base(cfg),
        "allowlist": {"users": len(allow.get("users", {})), "groups": len(allow.get("groups", {}))},
        "note": "bot display name is shown in the QQ open-platform console; qq-cli does not call a profile endpoint",
    }
    if args.format == "json":
        _print_json(data)
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
    return 0


def cmd_inbox(args, cfg):
    include_blocked = args.include_blocked or args.all
    unread_only = not args.all
    events = store.inbox(
        cfg,
        include_blocked=include_blocked,
        unread_only=unread_only,
        claim=args.claim,
        lease=args.lease,
        kind=args.kind,
        limit=args.limit,
    )
    views = [normalize.public_view(ev) for ev in events]
    if args.count:
        # Only processable events: expired or actively leased events must not keep
        # waking the unattended agent every minute.
        print(sum(1 for v in views if not v.get("expired") and not v.get("claimed")))
        return 0
    if args.format == "json":
        _print_json(views)
    else:
        if not views:
            print("[inbox] empty")
        for v in views:
            state = "expired" if v["expired"] else f"{v['deadline_in']}s"
            flag = "BLOCKED " if not v["allowed"] else ""
            text = v["content"].replace("\n", " ")[:100]
            print(f"{flag}[{state}] {v['kind']} {v['chat']}: {text}")
    return 0


def cmd_release(args, cfg):
    n = store.release(args.event_ids)
    print(f"[release] {n} event(s)")
    return 0


def cmd_ack(args, cfg):
    if args.all:
        n = store.ack_all()
    else:
        if not args.event_ids:
            print("[error] pass event ids or --all", file=sys.stderr)
            return 1
        n = store.ack(args.event_ids)
    print(f"[ack] {n} event(s)")
    return 0


def cmd_requests(args, cfg):
    rows = store.requests()
    if not args.no_snippet:
        pass
    else:
        for r in rows:
            r["last_content"] = ""
    if args.format == "json":
        _print_json(rows)
    else:
        if not rows:
            print("[requests] none")
        for r in rows:
            print(f"{r['kind']} {r['chat_id']} label={r['label'] or '-'} count={r['count']} last={r['last_seen']}")
            if not args.no_snippet and r.get("last_content"):
                print(f"  last: {r['last_content']}")
        if rows:
            print("[requests] human-only: approve with `qq-cli allow user|group <openid>`; never paste these ids into wiki")
    return 0


def cmd_allow(args, cfg):
    kind = "user" if args.kind == "user" else "group"
    if not _confirm(f"allow {kind} {args.openid}?", args.yes):
        return 1
    data = config.load_allowlist()
    bucket = "users" if kind == "user" else "groups"
    data[bucket][args.openid] = {"label": args.label or "", "enabled": True}
    config.save_allowlist(data)
    print(f"[allow] {kind} {args.openid} label={args.label or '-'}")
    return 0


def cmd_deny(args, cfg):
    kind = "user" if args.kind == "user" else "group"
    if not _confirm(f"deny {kind} {args.openid}?", args.yes):
        return 1
    data = config.load_allowlist()
    bucket = "users" if kind == "user" else "groups"
    data[bucket].pop(args.openid, None)
    config.save_allowlist(data)
    print(f"[deny] {kind} {args.openid}")
    return 0


def cmd_reply(args, cfg):
    ev = store.find_event(args.event_id)
    if ev is None:
        print(f"[error] unknown event: {args.event_id}", file=sys.stderr)
        return 1
    if not ev.get("allowed"):
        print("[error] event chat is not on the allowlist", file=sys.stderr)
        return 1
    if not ev.get("msg_id"):
        print("[error] stored event has no msg_id; cannot send a passive reply", file=sys.stderr)
        return 1

    existing = store.sent_for(args.event_id)
    if existing and not args.resend:
        _print_json({"event_id": args.event_id, "already_replied": True, "sent": existing})
        return 0

    try:
        text = _read_text_file(args.text_file)
    except OSError as exc:
        print(f"[error] cannot read text file: {exc}", file=sys.stderr)
        return 1
    parts = api.split_text(text, cfg.get("max_reply_chars", 1800), cfg.get("max_reply_parts", 5))
    if not parts:
        print("[error] empty reply text", file=sys.stderr)
        return 1

    deadline = int(ev.get("deadline_epoch") or 0)
    now = int(time.time())
    expired = deadline <= now
    start_seq = int(args.seq) if args.seq else store.next_seq(args.event_id)
    if start_seq + len(parts) - 1 > 5:
        print("[error] passive reply limit is 5 parts per message (msg_seq 1..5)", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_json(
            {
                "event_id": args.event_id,
                "kind": ev.get("kind"),
                "chat": ev.get("chat_ref"),
                "expired": expired,
                "deadline": ev.get("deadline"),
                "start_seq": start_seq,
                "parts": [{"seq": start_seq + i, "chars": len(p), "text": p} for i, p in enumerate(parts)],
            }
        )
        return 0
    if expired:
        print(f"[error] passive reply window expired at {ev.get('deadline')}; active messaging is unavailable", file=sys.stderr)
        return 1

    try:
        token = auth.get_token(cfg)
    except Exception as exc:
        print(f"[error] auth: {exc}", file=sys.stderr)
        return 1

    sent = []
    for i, part in enumerate(parts):
        seq = start_seq + i
        try:
            try:
                result = api.send_passive(token, cfg, ev["kind"], ev["chat_id"], part, ev["msg_id"], seq)
            except api.TokenExpired:
                token = auth.get_token(cfg, force=True)
                result = api.send_passive(token, cfg, ev["kind"], ev["chat_id"], part, ev["msg_id"], seq)
        except api.ApiError as exc:
            print(f"[error] send failed at seq {seq}: {exc}", file=sys.stderr)
            if sent:
                print(f"[error] already sent: {json.dumps(sent, ensure_ascii=False)}", file=sys.stderr)
            return 1
        message_id = str(result.get("id") or "")
        store.record_sent(args.event_id, ev["kind"], seq, message_id, len(part))
        sent.append({"seq": seq, "message_id": message_id, "chars": len(part)})

    if args.ack:
        store.ack([args.event_id])
    _print_json({"event_id": args.event_id, "sent": sent, "acked": bool(args.ack)})
    return 0


def cmd_listen(args, cfg):
    if _pid_alive(_read_pid()) and not args.replace and not args.once:
        print(f"[error] listener already running pid {_read_pid()} (use --replace)", file=sys.stderr)
        return 1
    kwargs = {
        "once": args.once,
        "timeout": args.timeout,
        "max_events": args.max,
    }
    if args.detach:
        adapter = current_platform()
        if not adapter.supports_detach:
            print("[error] --detach is not supported on this platform", file=sys.stderr)
            return 1
        config.ensure_home()
        argv = [sys.executable, "-m", "qqcli"]
        if getattr(args, "home", None):
            argv += ["--home", args.home]
        if getattr(args, "debug", False):
            argv.append("--debug")
        # --replace lets the child start even though the parent has just written
        # the child's own pid into the pid file (a fresh process, not a fork).
        argv += ["listen", "--replace"]
        if args.once:
            argv.append("--once")
        if args.timeout:
            argv += ["--timeout", str(args.timeout)]
        if args.max:
            argv += ["--max", str(args.max)]
        pid = adapter.spawn_detached(argv, config.log_path())
        config.pid_path().write_text(f"{pid}\n", encoding="utf-8")
        config.chmod_600(config.pid_path())
        print(f"[listen] detached pid {pid}; log {config.log_path()}")
        return 0
    config.ensure_home()
    config.pid_path().write_text(f"{os.getpid()}\n", encoding="utf-8")
    config.chmod_600(config.pid_path())
    try:
        result = gateway.run_blocking(cfg, **kwargs)
    finally:
        try:
            if _read_pid() == os.getpid():
                config.pid_path().unlink()
        except OSError:
            pass
    if args.format == "json":
        _print_json(result)
    else:
        print(f"[listen] {result}")
    return 0


def cmd_wait(args, cfg):
    result = gateway.run_blocking(cfg, once=False, timeout=args.timeout, max_events=args.max)
    if args.format == "json":
        _print_json(result)
    else:
        print(f"[wait] {result}")
    return 0


def cmd_stop(args, cfg):
    pid = _read_pid()
    if not _pid_alive(pid):
        print("[stop] no listener running")
        try:
            config.pid_path().unlink()
        except OSError:
            pass
        return 0
    try:
        current_platform().stop_process(pid)
    except OSError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(f"[stop] signal sent to pid {pid}")
    return 0


def cmd_purge(args, cfg):
    result = store.purge(args.days)
    if args.format == "json":
        _print_json(result)
    else:
        print(f"[purge] removed {result['removed_files']} inbox file(s), kept {result['kept_days']} day(s)")
    return 0


def cmd_replay(args, cfg):
    try:
        payload = normalize.load_event_file(args.file)
        ev = normalize.normalize(payload, cfg)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    if args.allow:
        ev["allowed"] = True
    added = store.append_event(ev, cfg)
    out = normalize.public_view(ev)
    out["appended"] = added
    if args.format == "json":
        _print_json(out)
    else:
        print(f"[replay] {'appended' if added else 'deduped'} {out['event_id']} {out['kind']} {out['chat']}")
    return 0


def cmd_doctor(args, cfg):
    checks = []

    def add(level, name, detail=""):
        checks.append({"level": level, "name": name, "detail": detail})

    home = config.home()
    home_exists = home.is_dir()
    add("ok" if home_exists else "warning", "home", str(home) + ("" if home_exists else " (will be created on login)"))
    p = current_platform()
    add("ok", "platform", f"{p.key}/{p.os_name}, executor {p.executor}, detach {'yes' if p.supports_detach else 'no'}")
    cfg_ok = config.config_path().exists()
    add("ok" if cfg_ok else "warning", "config", str(config.config_path()))
    app_id = config.resolve_app_id(cfg)
    add("ok" if app_id else "error", "app_id", app_id or "unset")
    stored = config.credentials_stored()
    env_secret = bool(os.environ.get(config.ENV_CLIENT_SECRET))
    add(
        "ok" if stored or env_secret else "warning",
        "credentials",
        "stored (0600)" if stored else ("environment" if env_secret else "not stored; run `qq-cli secret set --app-id <AppID>` once"),
    )
    tok = auth.token_status()
    if tok["present"] and not tok.get("expired"):
        add("ok", "token", f"{tok['remaining']}s left")
    else:
        add("warning", "token", "missing or expired; run `qq-cli login`")
    allow = config.load_allowlist()
    n_users, n_groups = len(allow.get("users", {})), len(allow.get("groups", {}))
    add("ok" if n_users + n_groups else "warning", "allowlist", f"users {n_users}, groups {n_groups}")
    probe = home if home_exists else home.parent
    writable = os.access(probe, os.W_OK)
    add("ok" if writable else "error", "data_dir_writable", str(home))
    add("ok", "api_base", config.api_base(cfg))
    if not args.offline and app_id and tok["present"] and not tok.get("expired"):
        try:
            token = auth.get_token(cfg)
            url = api.get_gateway(token, cfg)
            add("ok", "gateway", url)
        except Exception as exc:
            add("warning", "gateway", str(exc))
    elif args.offline:
        add("ok", "gateway", "skipped (--offline)")
    for c in checks:
        print(f"[{c['level']}] {c['name']}: {c['detail']}")
    return 1 if any(c["level"] == "error" for c in checks) else 0


def cmd_selftest(args, cfg):
    import tempfile

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixtures = os.path.join(here, "tests", "fixtures")
    results = []

    def run(name, fn):
        try:
            fn()
            results.append((True, name, ""))
        except Exception as exc:
            results.append((False, name, str(exc)))

    old_home = os.environ.get(config.ENV_HOME)
    with tempfile.TemporaryDirectory(prefix="qq-cli-selftest-") as tmp:
        os.environ[config.ENV_HOME] = tmp
        try:
            allow = json.load(open(os.path.join(fixtures, "allowlist.json"), encoding="utf-8"))
            config.save_allowlist(allow)
            cfg2 = config.load_config()

            def replay(name):
                return normalize.normalize(
                    normalize.load_event_file(os.path.join(fixtures, name)), cfg2
                )

            def t_normalize():
                c2c = replay("c2c_message.json")
                grp = replay("group_at_message.json")
                assert c2c["kind"] == "c2c" and c2c["allowed"], c2c
                assert grp["kind"] == "group" and grp["allowed"], grp

            def t_spool_and_dedupe():
                store.append_event(replay("c2c_message.json"), cfg2)
                assert len(store.all_events()) == 1
                assert store.append_event(replay("c2c_message.json"), cfg2) is False
                assert len(store.all_events()) == 1

            def t_blocked():
                blocked = normalize.normalize(
                    normalize.load_event_file(os.path.join(fixtures, "blocked_c2c.json")), cfg2
                )
                assert blocked["allowed"] is False
                store.append_event(blocked, cfg2)
                assert all(e["allowed"] for e in store.inbox(cfg2))
                assert store.requests(), "blocked chat should surface in requests"

            def t_claim():
                rows = store.inbox(cfg2, claim=True, lease=60)
                assert len(rows) == 1, rows
                assert store.inbox(cfg2) == [], "claimed event must be hidden"
                store.release([rows[0]["event_id"]])
                assert len(store.inbox(cfg2)) == 1

            def t_split():
                parts = api.split_text("a" * 5000, 1800, 5)
                assert 1 <= len(parts) <= 5, len(parts)
                assert all(len(p) <= 1900 for p in parts)

            def t_platforms():
                from .platforms import detect

                assert detect("Linux").executor == "systemd"
                assert detect("Darwin").executor == "launchd"
                assert detect("Windows").key == "windows"
                assert detect("Windows").executor == "taskscheduler"
                assert detect("Linux").supports_detach is True

            run("normalize", t_normalize)
            run("spool_dedupe", t_spool_and_dedupe)
            run("blocked", t_blocked)
            run("claim", t_claim)
            run("split", t_split)
            run("platforms", t_platforms)
        finally:
            if old_home is None:
                os.environ.pop(config.ENV_HOME, None)
            else:
                os.environ[config.ENV_HOME] = old_home

    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        print(f"[{'ok' if ok else 'fail'}] {name}" + (f": {detail}" if detail else ""))
    print(f"[selftest] {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qq-cli",
        description="Transport-only CLI for the official QQ Bot open platform (v2 API). "
        "It receives messages and sends passive replies; it never reads wiki content or runs an LLM.",
    )
    p.add_argument("--home", help="override QQ_CLI_HOME (default ~/.qq-cli)")
    p.add_argument("--debug", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("login", help="validate AppID/ClientSecret and cache an access token")
    s.add_argument("--app-id", default="")
    s.add_argument("--no-store", action="store_true", help="do not write the client secret to disk")
    s.set_defaults(func=cmd_login)

    s = sub.add_parser("logout", help="clear the cached access token")
    s.add_argument("--forget-secret", action="store_true")
    s.set_defaults(func=cmd_logout)

    s = sub.add_parser("secret", help="store/clear the local AppID+ClientSecret (0600)")
    s.add_argument("action", choices=["set", "clear", "status"])
    s.add_argument("--app-id", default="")
    s.add_argument("--file", default="", help="read the secret from a file (instead of a prompt)")
    s.add_argument("--stdin", action="store_true", help="read the secret from stdin")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_secret)

    s = sub.add_parser("ensure", help="idempotent auth check: refresh token + gateway (no TTY needed)")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_ensure)

    s = sub.add_parser("status", help="auth, listener, inbox and allowlist status")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("whoami", help="local bot identity and allowlist counts")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser("inbox", help="list pending messages")
    s.add_argument("--unread", action="store_true", default=True, help="unread only (default)")
    s.add_argument("--all", action="store_true", help="include blocked and acknowledged")
    s.add_argument("--include-blocked", action="store_true")
    s.add_argument("--claim", action="store_true", help="lease the returned events to this session")
    s.add_argument("--lease", type=int, default=120, help="lease seconds (default 120)")
    s.add_argument("--kind", choices=["c2c", "group"], default="")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--count", action="store_true", help="print only the number of matching events")
    s.add_argument("--format", choices=["text", "json"], default="json")
    s.set_defaults(func=cmd_inbox)

    s = sub.add_parser("release", help="release claimed events")
    s.add_argument("event_ids", nargs="+")
    s.set_defaults(func=cmd_release)

    s = sub.add_parser("ack", help="acknowledge processed events")
    s.add_argument("event_ids", nargs="*")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_ack)

    s = sub.add_parser("requests", help="show senders/groups not on the allowlist (human-only)")
    s.add_argument("--no-snippet", action="store_true")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_requests)

    s = sub.add_parser("allow", help="add a chat to the local allowlist (human-only)")
    s.add_argument("kind", choices=["user", "group"])
    s.add_argument("openid")
    s.add_argument("--label", default="")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_allow)

    s = sub.add_parser("deny", help="remove a chat from the local allowlist (human-only)")
    s.add_argument("kind", choices=["user", "group"])
    s.add_argument("openid")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_deny)

    s = sub.add_parser("reply", help="send passive replies to a stored event")
    s.add_argument("event_id")
    s.add_argument("--text-file", required=True, help="UTF-8 text file, or - for stdin")
    s.add_argument("--seq", type=int, default=0, help="starting msg_seq (default: next free)")
    s.add_argument("--ack", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--resend", action="store_true")
    s.set_defaults(func=cmd_reply)

    s = sub.add_parser("listen", help="receive events over the official WebSocket gateway")
    s.add_argument("--detach", action="store_true")
    s.add_argument("--replace", action="store_true")
    s.add_argument("--once", action="store_true", help="exit after the first spooled event")
    s.add_argument("--timeout", type=float, default=None)
    s.add_argument("--max", type=int, default=0)
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_listen)

    s = sub.add_parser("wait", help="bounded receive for one agent turn (no daemon)")
    s.add_argument("--timeout", type=float, default=60.0)
    s.add_argument("--max", type=int, default=1)
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_wait)

    s = sub.add_parser("stop", help="stop the detached listener")
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("purge", help="drop inbox files/state older than N days")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_purge)

    s = sub.add_parser("replay", help="offline: normalize and spool a saved event JSON")
    s.add_argument("--file", required=True)
    s.add_argument("--allow", action="store_true", help="mark as allowed (test only)")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_replay)

    s = sub.add_parser("doctor", help="preflight checks")
    s.add_argument("--offline", action="store_true")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("selftest", help="run offline fixtures")
    s.set_defaults(func=cmd_selftest)

    s = sub.add_parser("version", help="print the version")
    s.set_defaults(func=cmd_version)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.home:
        os.environ[config.ENV_HOME] = args.home
    cfg = config.load_config()
    try:
        return int(args.func(args, cfg) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if args.debug:
            raise
        print(f"[error] {exc}", file=sys.stderr)
        return 1
