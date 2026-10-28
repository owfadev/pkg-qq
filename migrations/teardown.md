---
verb: teardown
---
Semantic deletion (x->0) for the QQ domain — relay to the user, confirm before each
step; data deletion always belongs to the human:

1. **Stop the transport** — run `qq-cli stop` to retire a manual detached listener,
   then disable the platform service: systemd `systemctl --user disable --now
   qq-listen.service` (remove the unit + `daemon-reload`), launchd `launchctl unload
   ~/Library/LaunchAgents/com.qq-cli.listen.plist` (remove the plist), or Windows
   `Unregister-ScheduledTask -TaskName owfa-qq-listen`.
2. **Stop the unattended executor** — systemd `systemctl --user disable --now
   qq-agent.timer` (remove the timer/service units + `daemon-reload`), launchd
   `launchctl unload ~/Library/LaunchAgents/com.qq-cli.agent.plist` (remove the plist),
   or Windows `Unregister-ScheduledTask -TaskName owfa-qq-agent`. Remove
   `~/.qq-cli/executor.json`. If `wiki/cron/qq-inbox.md` exists, mark it
   `status: deprecated` / keep it as a record (never delete); delete/stop any other
   executor-side task on confirmation.
3. **Declaration** — `wiki/qq/policy.md` and any `audience: public` marks stay;
   mark the policy page `status: deprecated` if the domain is retired.
4. **Credentials** — `~/.qq-cli/` is never auto-deleted; remind the user, then
   `qq-cli logout --forget-secret` or delete the directory only on explicit
   instruction.
5. **Local spool** — `~/.qq-cli/inbox/` and `~/.qq-cli/sent.jsonl` are local only;
   purge on explicit instruction.

Default gate: the kernel residual scan (anchor surfaces clean = clear).
