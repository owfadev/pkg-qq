# -*- coding: utf-8 -*-
"""App access-token exchange and cache.

Official API v2: POST /app/getAppAccessToken with {appId, clientSecret} returns
{access_token, expires_in}. The token is cached in ~/.qq-cli/token.json (0600)
and refreshed 60 seconds before expiry. The client secret is never written
unless the operator explicitly stores it at login time.
"""
import json
import time
import urllib.error
import urllib.request

from . import config


class AuthError(RuntimeError):
    pass


def _post_json(url: str, body: dict, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw or "{}")


def fetch_app_token(cfg: dict, app_id: str, secret: str):
    last = None
    for base in config.token_bases(cfg):
        url = base.rstrip("/") + "/app/getAppAccessToken"
        try:
            data = _post_json(url, {"appId": app_id, "clientSecret": secret})
        except Exception as exc:  # try the next documented host
            last = exc
            continue
        token = data.get("access_token") or data.get("accessToken")
        if not token:
            last = AuthError(str(data)[:300])
            continue
        try:
            expires = int(float(data.get("expires_in") or 7200))
        except (TypeError, ValueError):
            expires = 7200
        return str(token), expires
    raise AuthError(f"token exchange failed: {last}")


def get_token(cfg: dict, force: bool = False) -> str:
    app_id = config.resolve_app_id(cfg)
    if not app_id:
        raise AuthError("app id unavailable: run `qq-cli login` or set QQ_CLI_APP_ID")
    now = int(time.time())
    cached = config.load_token()
    if (
        not force
        and cached.get("app_id") == app_id
        and cached.get("access_token")
        and int(cached.get("expires_at") or 0) - 60 > now
    ):
        return str(cached["access_token"])
    secret = config.resolve_client_secret(cfg)
    token, expires = fetch_app_token(cfg, app_id, secret)
    config.save_token(
        {
            "app_id": app_id,
            "access_token": token,
            "expires_at": now + expires,
            "obtained_at": now,
        }
    )
    return token


def token_status() -> dict:
    cached = config.load_token()
    if not cached.get("access_token"):
        return {"present": False, "remaining": 0}
    remaining = int(cached.get("expires_at") or 0) - int(time.time())
    return {
        "present": True,
        "app_id": cached.get("app_id", ""),
        "remaining": remaining,
        "expired": remaining <= 0,
    }
