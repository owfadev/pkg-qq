# -*- coding: utf-8 -*-
"""Paths, configuration, credentials and the local allowlist.

Everything under QQ_CLI_HOME (default ~/.qq-cli) is 0600/0700 and never enters
the repository. The config file holds non-secret settings plus the app id; the
client secret is taken from the environment or stored explicitly (login without
--no-store); the access token is cached separately.
"""
import getpass
import json
import os
import stat
from pathlib import Path

DEFAULT_API_BASE = "https://api.bot.qq.com"
# The official docs have shown both hosts for the token exchange; try in order.
DEFAULT_TOKEN_BASES = ("https://api.bot.qq.com", "https://bots.qq.com")

ENV_HOME = "QQ_CLI_HOME"
ENV_APP_ID = "QQ_CLI_APP_ID"
ENV_CLIENT_SECRET = "QQ_CLI_CLIENT_SECRET"
ENV_API_BASE = "QQ_CLI_API_BASE"

DEFAULTS = {
    "app_id": "",
    "api_base": DEFAULT_API_BASE,
    "max_reply_chars": 1800,
    "max_reply_parts": 5,
    "group_passive_seconds": 300,
    "c2c_passive_seconds": 3600,
    "retention_days": 7,
}


def home() -> Path:
    root = os.environ.get(ENV_HOME)
    return Path(root).expanduser() if root else Path.home() / ".qq-cli"


def ensure_home() -> Path:
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(h, 0o700)
    except OSError:
        pass
    for sub in ("inbox", "outbox"):
        (h / sub).mkdir(exist_ok=True)
    return h


def config_path() -> Path:
    return home() / "config.json"


def token_path() -> Path:
    return home() / "token.json"


def credentials_path() -> Path:
    return home() / "credentials.json"


def allowlist_path() -> Path:
    return home() / "allowlist.json"


def state_path() -> Path:
    return home() / "state.json"


def sent_path() -> Path:
    return home() / "sent.jsonl"


def pid_path() -> Path:
    return home() / "listen.pid"


def log_path() -> Path:
    return home() / "listen.log"


def outbox_dir() -> Path:
    ensure_home()
    return home() / "outbox"


def chmod_600(path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path, data) -> None:
    ensure_home()
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    chmod_600(tmp)
    os.replace(tmp, path)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(_read_json(config_path(), {}))
    env_base = os.environ.get(ENV_API_BASE)
    if env_base:
        cfg["api_base"] = env_base.rstrip("/")
    return cfg


def save_config(cfg: dict) -> None:
    merged = dict(DEFAULTS)
    merged.update(cfg)
    _write_json(config_path(), merged)


def update_config(**kwargs) -> dict:
    cfg = load_config()
    cfg.update(kwargs)
    save_config(cfg)
    return cfg


def load_allowlist() -> dict:
    data = _read_json(allowlist_path(), {})
    data.setdefault("users", {})
    data.setdefault("groups", {})
    return data


def save_allowlist(data: dict) -> None:
    data.setdefault("users", {})
    data.setdefault("groups", {})
    _write_json(allowlist_path(), data)


def allowlist_entries(kind: str):
    key = "users" if kind in ("user", "c2c") else "groups"
    return load_allowlist().get(key, {})


def is_allowed(kind: str, chat_id: str) -> bool:
    entry = allowlist_entries(kind).get(chat_id)
    return bool(entry and entry.get("enabled", True))


def entry_label(kind: str, chat_id: str) -> str:
    entry = allowlist_entries(kind).get(chat_id) or {}
    return str(entry.get("label") or "")


def load_token() -> dict:
    return _read_json(token_path(), {})


def save_token(data: dict) -> None:
    _write_json(token_path(), data)


def clear_token() -> None:
    try:
        os.remove(token_path())
    except OSError:
        pass


def load_credentials() -> dict:
    """Local AppID + ClientSecret (0600), written by `qq-cli secret set`.

    Storing the secret is deliberate: a detached listener must refresh its access
    token without a TTY. The file never leaves this machine and is never printed.
    """
    return _read_json(credentials_path(), {})


def save_credentials(app_id: str, client_secret: str) -> None:
    _write_json(credentials_path(), {"app_id": app_id, "client_secret": client_secret})


def clear_credentials() -> None:
    try:
        os.remove(credentials_path())
    except OSError:
        pass


def credentials_stored() -> bool:
    cred = load_credentials()
    return bool(cred.get("app_id") and cred.get("client_secret"))


def resolve_app_id(cfg: dict, cli_value: str = "") -> str:
    cred = load_credentials()
    return (
        cli_value
        or os.environ.get(ENV_APP_ID)
        or cfg.get("app_id")
        or cred.get("app_id")
        or ""
    ).strip()


def resolve_client_secret(cfg: dict, allow_prompt: bool = True) -> str:
    cred = load_credentials()
    secret = (
        os.environ.get(ENV_CLIENT_SECRET)
        or cred.get("client_secret")
        or cfg.get("client_secret")
        or ""
    )
    if secret:
        return secret.strip()
    if not allow_prompt:
        raise RuntimeError(
            "client secret unavailable: run `qq-cli secret set --app-id <AppID>` once, "
            "or set QQ_CLI_CLIENT_SECRET"
        )
    if not os.isatty(0):
        raise RuntimeError(
            "client secret unavailable in a non-interactive shell: run "
            "`qq-cli secret set --app-id <AppID>` in a terminal, or set QQ_CLI_CLIENT_SECRET"
        )
    return getpass.getpass("QQ Bot ClientSecret: ").strip()


def api_base(cfg: dict) -> str:
    return str(cfg.get("api_base") or DEFAULT_API_BASE).rstrip("/")


def token_bases(cfg: dict):
    base = api_base(cfg)
    out = [base]
    for b in DEFAULT_TOKEN_BASES:
        if b not in out:
            out.append(b)
    return out
