---
verb: init
verify: init.py
---
First-run setup for the QQ domain (relay to the user in their language):

1. **Platform (human)** — create an official QQ Bot at q.qq.com; enable the group @
   and private-chat (C2C) scenarios; add the operator's QQ number as a development
   / test user; copy the AppID and ClientSecret.
2. **Connector** — install `connectors/qq-cli`:
   `python3 -m pip install --user --break-system-packages -e connectors/qq-cli`
   (or run `connectors/qq-cli/scripts/bootstrap.sh`, which installs it, runs
   `qq-cli doctor --offline`, and prints the platform steps). In the operator's own
   terminal run `qq-cli secret set --app-id <AppID>` (interactive ClientSecret,
   stored 0600 in `~/.qq-cli/credentials.json`), then `qq-cli ensure --format json`.
   Never put the secret in the repository, a chat message, or a command line.
3. **Allowlist** — send a private message and a group @ to the bot; run
   `qq-cli requests` (human-only), then `qq-cli allow user|group <openid> --label ...`.
   Approval is human-only; the agent never widens the allowlist.
4. **Wiki declaration** — create `wiki/qq/policy.md` (`type: qq` + the `qq` block
   mapping: bot_appid, public_field/public_value, passive windows; no raw openids or
   secrets). Mark pages that may be read in groups with `audience: public`.
5. **Unattended mode (optional — ask, never force)** — if the user wants automatic
   replies:
   - create `wiki/cron/qq-inbox.md` (`type: cron`; trigger `*/1 * * * *`;
     action = process the qq-cli inbox per the `qq` command; form: session;
     domain: qq; status: paused first);
   - after explicit confirmation run the platform installer:
     `connectors/qq-cli/scripts/install-executor.sh` (systemd on Linux, launchd on
     macOS) or `connectors/qq-cli/windows/install-taskscheduler.ps1` (native
     Windows, experimental). It installs the listener plus the every-minute agent
     trigger and writes `~/.qq-cli/executor.json`;
   - verify the executor (`systemctl --user list-timers qq-agent.timer` /
     `launchctl list | grep qq-cli` / `Get-ScheduledTask`) and one real reply,
     then set the cron page `status: active`.
   Installing a service/task is a system-state write: ask first. If declined, skip —
   do not create the page or the units.

Completion = `wiki/qq/policy.md` exists with the `qq` block; the optional cron page is
warning-level only; credentials and the allowlist are warning-level (the user may
finish them later). The package ships the executor recipe in `scripts/` + the
per-platform template directories; the init step installs it only after confirmation.
