import json
import os
import platform
import re


def _executor_state():
    """Return (kind, installed) for the unattended executor on this OS.

    All installers write ~/.qq-cli/executor.json; known platform paths are a
    fallback for installations made before the marker existed.
    """
    kind = ""
    marker = os.path.expanduser("~/.qq-cli/executor.json")
    try:
        with open(marker, encoding="utf-8") as f:
            kind = str(json.load(f).get("kind") or "")
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    system = platform.system()
    if system == "Darwin":
        installed = os.path.exists(
            os.path.expanduser("~/Library/LaunchAgents/com.qq-cli.agent.plist")
        )
    elif system == "Windows":
        installed = bool(kind)  # Task Scheduler is not readable from here
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        installed = os.path.exists(
            os.path.join(config_home, "systemd", "user", "qq-agent.timer")
        )
    return kind or "executor", bool(installed)


def _text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def verify(ctx):
    """Read-only init check: the declaration page exists and is structurally usable."""
    issues = []
    policy = os.path.join(ctx.root, "wiki", "qq", "policy.md")
    if not os.path.exists(policy):
        issues.append(("error", "wiki/qq/policy.md missing — create the QQ domain declaration page"))
    else:
        text = _text(policy)
        if not re.search(r"^type:\s*qq\s*$", text, re.M):
            issues.append(("error", "wiki/qq/policy.md missing `type: qq`"))
        if not re.search(r"^qq:\s*$", text, re.M):
            issues.append(("error", "wiki/qq/policy.md missing the qq block mapping"))
        elif not re.search(r"^\s+bot_appid:\s*['\"]?[^'\"\s]", text, re.M):
            issues.append(("warning", "wiki/qq/policy.md has an empty qq.bot_appid"))

    cron = os.path.join(ctx.root, "wiki", "cron", "qq-inbox.md")
    cron_text = _text(cron)
    cron_exists = os.path.exists(cron)
    cron_status = ""
    if not cron_exists:
        issues.append(("warning", "unattended mode not registered (wiki/cron/qq-inbox.md absent; optional)"))
    else:
        if not re.search(r"^type:\s*cron\s*$", cron_text, re.M):
            issues.append(("warning", "wiki/cron/qq-inbox.md should be `type: cron`"))
        m = re.search(r"(?m)^  status:\s*(\S+)", cron_text)
        cron_status = m.group(1) if m else ""
        if not cron_status:
            issues.append(("warning", "wiki/cron/qq-inbox.md missing `cron.status`"))

    executor_kind, executor_installed = _executor_state()
    if cron_exists:
        if not executor_installed:
            issues.append(("warning", "wiki/cron/qq-inbox.md exists but the unattended executor is not installed; run connectors/qq-cli/scripts/install-executor.sh (Windows: windows/install-taskscheduler.ps1) after confirmation"))
        elif cron_status != "active":
            issues.append(("warning", f"{executor_kind} is installed but the cron page is not `status: active`"))
    elif executor_installed:
        issues.append(("warning", f"{executor_kind} is installed but wiki/cron/qq-inbox.md is missing"))

    home = os.path.expanduser("~/.qq-cli")
    if not os.path.isdir(home):
        issues.append(("warning", "qq-cli credentials absent (~/.qq-cli); run `qq-cli secret set` at first use"))
    else:
        try:
            with open(os.path.join(home, "allowlist.json"), encoding="utf-8") as f:
                allow = json.load(f)
        except (OSError, json.JSONDecodeError):
            allow = {}
        if not (allow.get("users") or allow.get("groups")):
            issues.append(("warning", "qq-cli allowlist is empty; approve the operator's chat before use"))
    return issues
