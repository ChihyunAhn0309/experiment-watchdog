# Verified product baseline

Checked 2026-10-03 on Windows. PowerShell npm CLI: `codex-cli 0.159.2`. The supervisor's native-executable resolver selected the desktop-bundled `codex-cli 0.159.0-alpha.12.1`; doctor successfully checked its required flags and ChatGPT authentication. No inference was requested from either build.

- [Official non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): unattended `codex exec`, stdin prompts, JSON events, structured final output, saved CLI authentication and ephemeral sessions.
- [Official developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli): CLI command reference. Local `codex exec --help` additionally verified the installed flags used here.
- [Official pricing and usage](https://learn.chatgpt.com/docs/pricing): included usage/credits as applicable; API-key calls follow API pricing. This tool does not promise free repair inference.

Zero-model-call monitoring is a property of watchdog.py, not a free Codex API tier. Codex starts only in the failure branch. Local CLI auth was ChatGPT-authenticated; authentication elsewhere must be checked on that host.

Repair uses `codex exec --sandbox danger-full-access -c approval_policy="never"` for the user's full-access assumption, without changing persistent settings. A validated structured decision permits restarting the same command. The CLI inherits its configured model/provider/auth. Rerun doctor and offline tests after CLI upgrades; documentation and behavior can change.
