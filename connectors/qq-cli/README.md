# qq-cli — official QQ Bot transport

A transport-only CLI for the **official QQ Bot open platform** (v2 API). It receives
private (C2C) and group `@` messages over the WebSocket gateway, normalizes them into a
local spool, enforces a local allowlist, and sends **passive replies**. It contains no
LLM, no retrieval, and no answer composition — the agent session is the only answerer.

> End-to-end setup (platform app → login → allowlist → listener → agent command) lives
> in the package guide at the repository root (`README.md`; inside an installed
> instance: `.meta/plugins/domains/qq/README.md`).

## Scope

| | |
|---|---|
| Read | QQ event stream: `C2C_MESSAGE_CREATE`, `GROUP_AT_MESSAGE_CREATE` |
| Write | QQ passive replies; local spool/config under `~/.qq-cli/` |
| Never | `wiki/`, `vault/`, `.meta/`, `.agents/`, attachments, active/proactive messages |

Sending a reply is a write to QQ, not to the wiki. The connector never reads wiki
content; grounding is the agent command's responsibility.

## Install into an owfa instance (first use)

Downloading the repository is not enough to start. The plugin must be installed
into an owfa instance, and the connector's Python package must be installed.

1. **Get the package directory.** In the source repository run
   `scripts/package-qq.sh`; it assembles `dist/qq/` in the layout the kernel
   expects (`PKG.yaml`, `qq/`, `command/qq/`, `connectors/qq-cli/`, `migrations/`).
   A published package repository has the same layout at its root.
2. **Install the plugin** from the instance root:
   ```bash
   python3 .meta/scripts/wiki_plugin_kernel.py install qq --path /path/to/dist/qq
   # published unindexed repo:
   # python3 .meta/scripts/wiki_plugin_kernel.py install <owner>/<repo> --yes
   ```
3. **Run the init migration** and follow it:
   `python3 .meta/scripts/wiki_plugin_kernel.py migrate qq`.
   It creates `wiki/qq/policy.md`, asks for credentials and allowlist approval,
   and offers the unattended executor.
4. **Install the connector**: `connectors/qq-cli/scripts/bootstrap.sh`
   (Windows: `scripts/bootstrap.ps1`), or the pip command below.
5. **Human platform steps** (next section), then start:
   `qq-cli ensure && qq-cli listen --detach`.

The plugin cannot start itself: the agent session executes the init migration,
and the QQ platform steps need a human.

## Install the connector

```bash
cd connectors/qq-cli
python3 -m pip install --user --break-system-packages -e .
qq-cli version
```

Python 3.10+. The only dependency is `websockets`; HTTP uses the standard library.

## Platform setup (human)

1. Create a bot at the QQ open platform (q.qq.com); obtain `AppID` / `ClientSecret`.
2. Enable the private-chat (C2C) and group `@` scenarios. Group messages arrive only
   when the bot is `@`-mentioned.
3. Add the bot to a test group. After the first `@` and the first private message,
   read the `group_openid` / `user_openid` from `qq-cli requests` and approve them.
4. Optional: configure the API base for a sandbox environment with
   `QQ_CLI_API_BASE` or `config.json`.

## Auth and config

Credentials live only in `~/.qq-cli/` (override with `QQ_CLI_HOME`):

| File | Content | Mode |
|---|---|---|
| `config.json` | app id, api base, limits | 0600 |
| `credentials.json` | AppID + ClientSecret (one-time `secret set`) | 0600 |
| `token.json` | access token + expiry | 0600 |
| `allowlist.json` | alias ↔ raw openid (private) | 0600 |
| `salt` | openid-hash salt | 0600 |
| `inbox/YYYY-MM-DD.jsonl` | normalized events | 0600 |
| `state.json` | dedupe, ack, leases, gateway cursor | 0600 |
| `sent.jsonl` | sent sequence records (no text) | 0600 |
| `outbox/` | reply text awaiting send | 0600 |

- `QQ_CLI_APP_ID`, `QQ_CLI_CLIENT_SECRET`, `QQ_CLI_API_BASE`, `QQ_CLI_HOME`.
- **Recommended one-time setup** (operator's terminal, needs a TTY):
  `qq-cli secret set --app-id <AppID>` — the ClientSecret is prompted and stored 0600
  in `~/.qq-cli/credentials.json`. After that `qq-cli ensure` is the agent-runnable
  login/refresh path; it never needs a TTY and never prints the secret.
- `login` also stores the secret (0600) unless `--no-store`; `logout --forget-secret`
  removes it. `--no-store` is intended for one-shot `wait` runs with
  `QQ_CLI_CLIENT_SECRET` in the environment.
- The access token is cached and refreshed 60 seconds before expiry. A long-running
  `listen --detach` must be able to re-fetch the token, so use stored credentials or
  run the listener with `QQ_CLI_CLIENT_SECRET` in its environment.

## Commands

| Command | Purpose |
|---|---|
| `login [--no-store]` | validate credentials, cache a token, check the gateway |
| `secret set\|status\|clear` | one-time local AppID+ClientSecret storage (0600); status never prints the secret |
| `ensure [--format json]` | idempotent agent-side login/refresh + gateway check (no TTY) |
| `logout [--forget-secret]` | clear the token (and optionally the stored secret) |
| `status [--format json]` | token, listener, inbox counts, allowlist sizes |
| `whoami` | local app id and allowlist counts |
| `inbox [--claim] [--lease N] [--kind c2c\|group] [--limit N] [--count]` | list pending messages; `--count` prints only processable (unexpired, unclaimed) events |
| `release <event-id>...` | release claimed messages |
| `ack <event-id>...` / `--all` | mark processed |
| `requests` | senders/groups not on the allowlist (human-only) |
| `allow user\|group <openid> [--label X] [--yes]` | add to the local allowlist |
| `deny user\|group <openid> [--yes]` | remove from the allowlist |
| `reply <event-id> --text-file <path\|-> [--dry-run] [--ack]` | passive reply, split and idempotent |
| `listen [--detach] [--once] [--timeout S] [--max N]` | receive over WebSocket |
| `wait [--timeout S] [--max N]` | bounded receive for one agent turn |
| `stop` | stop the detached listener |
| `purge [--days N]` | drop old inbox/state |
| `replay --file <json> [--allow]` | offline: normalize and spool a saved event |
| `doctor [--offline]` | preflight checks |
| `selftest` | offline fixtures (no credentials) |

`inbox` returns aliases or salted short hashes, **not** raw openids. `reply` resolves
the chat from the stored event, so the agent never needs an openid. `requests` is the
only surface that prints raw ids, and it is for the human operator.

## Passive reply rules

- Every reply carries the event's `msg_id` and an increasing `msg_seq` (1..5).
- A group passive window is about 5 minutes; a private-chat window about 60 minutes
  (verify against the current console). Once expired, the CLI refuses; there is no
  active-message fallback (the platform no longer offers proactive sends).
- Text is split at paragraph/line boundaries, never inside an unterminated `[[...]]`,
  and capped at `max_reply_chars` (default 1800) with at most 5 parts.
- A duplicate `msg_id + msg_seq` is refused by the platform; `qq-cli` also records
  sent sequences and treats a repeat call as idempotent (`--resend` to override).
- `--dry-run` prints the parts, sequences and expiry state without sending.

## Receive loop

- `GET /gateway` → WebSocket; identify with intent `GROUP_AND_C2C_EVENT` (`1<<25`).
- Heartbeat (`op 1`), resume (`op 6`), reconnect (`op 7`), invalid session (`op 9`).
- Events are deduplicated by `event_id + msg_idx`, marked allowed/blocked, and appended
  to the daily inbox. The official gateway has **no offline queue**: events sent while
  the listener is down are lost.
- `listen --detach` starts a detached child interpreter through the platform
  adapter (POSIX `setsid`, Windows `DETACHED_PROCESS`). It is a dumb socket reader,
  not an agent. `wait` is the no-daemon alternative for a single agent turn.

## Unattended mode (optional)

The package ships an executor recipe per platform; installing it is a
**system-state change**: run an installer only after the operator confirms.

| File | Purpose |
|---|---|
| `scripts/qq-agent-watch.py` | one turn (cross-platform): status gate → count → lock → `claude -p` → `last_run`/log |
| `scripts/qq-agent-watch.sh` | compatibility shim that execs the Python watcher |
| `scripts/qq-agent-inbox.py` / `.sh` | restricted inbox wrapper (kind/limit from env, lease 180) |
| `scripts/qq-agent-send.py` / `.sh` | restricted reply wrapper: one event id, text on stdin, `--ack` |
| `scripts/install-executor.sh` | POSIX dispatcher: systemd on Linux, launchd on macOS |
| `scripts/install-systemd.sh` | render units, `daemon-reload`, enable listener + timer |
| `scripts/install-launchd.sh` | render LaunchAgents, load listener + agent |
| `windows/install-taskscheduler.ps1` | register the listener and every-minute agent tasks |
| `systemd/*.in`, `launchd/*.in` | unit templates (`@ROOT@` / `@HOME@` / `@QQCLI@` / `@PYTHON@`) |

Every installer writes `~/.qq-cli/executor.json` (`kind`, `root`, `installed_at`);
the QQ plugin's `init` verify reads that marker instead of hard-coding systemd paths.

Install:

```bash
qq-cli stop                       # retire a manual detached listener
connectors/qq-cli/scripts/install-executor.sh          # Linux / macOS
# Windows PowerShell (native CPython, experimental):
#   powershell -ExecutionPolicy Bypass -File connectors\qq-cli\windows\install-taskscheduler.ps1
```

Check: `systemctl --user list-timers qq-agent.timer` (Linux),
`launchctl list | grep qq-cli` (macOS),
`Get-ScheduledTask -TaskName 'owfa-qq-*'` (Windows).

The timer fires every minute. The watcher exits immediately unless
`wiki/cron/qq-inbox.md` has `status: active` and there are processable messages.
One agent run handles **one kind**: groups first (Read restricted to
`audience: public` pages plus the task/skill/policy files), then private chats (full
repo). This two-pass isolation prevents private context from leaking into a group
reply. Replies go through the stdin-only wrapper, so the agent cannot use
`--text-file <path>` to exfiltrate arbitrary files.

The agent runs `claude -p` with `--permission-mode dontAsk`, an explicit tool
allowlist, and no Write/Edit/Web/MCP/subagents. It never sees `~/.qq-cli`
credentials.

Pause the executor (the watcher also honors the page status; set
`wiki/cron/qq-inbox.md` to `status: paused` as well):

| Platform | Pause agent | Stop listener |
|---|---|---|
| systemd | `systemctl --user disable --now qq-agent.timer` | `systemctl --user disable --now qq-listen.service` |
| launchd | `launchctl unload ~/Library/LaunchAgents/com.qq-cli.agent.plist` | `launchctl unload ~/Library/LaunchAgents/com.qq-cli.listen.plist` |
| Task Scheduler | `Disable-ScheduledTask -TaskName owfa-qq-agent` | `Disable-ScheduledTask -TaskName owfa-qq-listen` |

Logs: `~/.qq-cli/listen.log` and `~/.qq-cli/agent.log` on every platform;
`journalctl --user -u qq-agent` on systemd only.

WSL2: units stop on `wsl --shutdown` and Windows sleep; the gateway has no offline
queue, so messages sent while down are lost. Enable lingering
(`loginctl enable-linger "$USER"`) if the user session is not kept logged in.

## Known limits

- Group events only fire on `@`; private chat availability depends on the bot's
  approved scenario.
- No message history API: the spool is the only record.
- Text only in v0.1; attachments are recorded as metadata, never downloaded.
- No active/proactive messages, no recall, no guild/channel events.
- URLs in message text may be rejected by the platform unless registered in the bot
  console; the reply command does not add URLs.
- Credentials and raw message content never enter the repository.
- Platform adapter: `qqcli/platforms/` separates process and permission hooks from
  the core. Linux/WSL is the verified path. macOS runs the same POSIX core but the
  launchd recipe is not yet exercised in CI; native Windows runs the core and can
  detach, while the Task Scheduler recipe is shipped as experimental. `selftest`
  exercises adapter selection but not the service managers.

## Tests

```bash
qq-cli selftest                 # normalize, dedupe, allowlist, claim, split
qq-cli replay --file tests/fixtures/c2c_message.json
qq-cli reply EVENT_C2C_1 --text-file - --dry-run
```

`tests/fixtures/allowlist.json` contains the fixture ids. Use a temporary
`QQ_CLI_HOME` for offline tests.

## Version

`0.2.0` — platform-neutral process layer (`qqcli/platforms`), cross-platform
watcher, systemd/launchd/Task Scheduler recipes, `executor.json` marker, bootstrap;
0.1.0 was the first transport implementation (auth, WebSocket receive, allowlist,
normalized spool, passive replies, offline self-test).
