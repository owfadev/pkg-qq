import os


def _text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def verify(ctx):
    """Read-only check that the connector carries the 0.2 portability layer."""
    issues = []
    base = os.path.join(ctx.root, "connectors", "qq-cli")
    platforms = os.path.join(base, "qqcli", "platforms", "__init__.py")
    store = os.path.join(base, "qqcli", "store.py")
    watcher = os.path.join(base, "scripts", "qq-agent-watch.py")
    installer = os.path.join(base, "scripts", "install-executor.sh")

    if not os.path.exists(platforms):
        issues.append(("warning", "qqcli/platforms/ missing — update/reinstall the connector"))
    if not os.path.exists(watcher):
        issues.append(("warning", "scripts/qq-agent-watch.py missing — update/reinstall the connector"))
    if not os.path.exists(installer):
        issues.append(("warning", "scripts/install-executor.sh missing — update/reinstall the connector"))
    if os.path.exists(store) and "import fcntl" in _text(store):
        issues.append(("warning", "store.py still imports fcntl — the connector was not updated"))

    cases = _text(os.path.join(base, "qqcli", "cli.py"))
    if cases and "platforms" not in cases:
        issues.append(("warning", "cli.py does not use the platform adapter"))
    return issues
