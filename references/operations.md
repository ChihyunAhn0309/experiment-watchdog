# Operation and configuration

## Architecture

`optional local validation -> foreground experiment -> local supervisor -> failure -> optional bounded local retry -> codex exec -> structured restart decision -> local validation -> same command`

Healthy monitoring reads process state and a small progress file, overwrites `state.json`, writes bounded logs, and sleeps. It contains no network client, model SDK or healthy-path Codex call: **zero inference tokens/credits for monitoring**. Setup conversations, CPU/disk/electricity, and the experiment's GPU/cloud/API usage are separate. A poorly configured failure condition can trigger paid inference, so choose stall thresholds and regexes carefully.

Exit failures work without experiment changes. Hangs require actual progress integration. A successful return code is the default completion condition; optional explicit success tightens it. Scientific validity still requires experiment-specific checks.

## Windows PowerShell

Replace these example paths with the actual project/interpreter. Use a stable config outside folders deleted by experiments. Do not put secrets in argv/config.

```powershell
$watchdogScript = Join-Path $env:USERPROFILE '.codex/skills/experiment-watchdog/scripts/watchdog.py'
$watchdogConfig = 'D:/research/my-project/watchdog.json'
python $watchdogScript init --config $watchdogConfig --project 'D:/research/my-project' -- 'D:/research/venv/Scripts/python.exe' -u train.py --config train.yaml
python $watchdogScript doctor --config $watchdogConfig
python $watchdogScript start --config $watchdogConfig
python $watchdogScript status --config $watchdogConfig
python $watchdogScript stop --config $watchdogConfig
```

`start` launches a hidden detached helper; `run` stays in the foreground for diagnosis. `stop` writes a local request. The supervisor stops its experiment or repair tree; check status for `cancelled` before doing further work. Usual stop latency is up to `poll_seconds` plus process cleanup. Foreground Ctrl+C is intentional cancellation. Killing just the experiment in Task Manager looks like failure; use the stop command for deliberate shutdown.

Commands are argv arrays without implicit shell evaluation. Direct `.cmd`, `.bat` and `.ps1` executables are rejected. For scripts, use e.g. `["powershell.exe", "-NoProfile", "-File", "D:/project/run.ps1"]`. Preserve native nonzero exit codes (`exit $LASTEXITCODE`). A script that backgrounds training and exits cannot represent training's lifetime.

Windows uses a gated launcher plus a Job Object: user code cannot spawn before containment is assigned, and closing the job stops owned descendants even after their parent exits.

## Linux / remote GPU hosts

Copy the skill folder to the server and use that server's paths and CLI authentication. A desktop login does not establish remote CLI authentication.

```bash
WATCHDOG_SCRIPT="$HOME/.codex/skills/experiment-watchdog/scripts/watchdog.py"
python3 "$WATCHDOG_SCRIPT" init --config /work/project/watchdog.json --project /work/project -- /work/venv/bin/python -u train.py
python3 "$WATCHDOG_SCRIPT" doctor --config /work/project/watchdog.json
python3 "$WATCHDOG_SCRIPT" start --config /work/project/watchdog.json
python3 "$WATCHDOG_SCRIPT" status --config /work/project/watchdog.json
python3 "$WATCHDOG_SCRIPT" stop --config /work/project/watchdog.json
```

`start` detaches a new session. If a host kills user processes at logout, use its persistent service/job facility to run the **Python supervisor**, not recurring Codex checks. The experiment must stay in the foreground. Slurm submission, Docker detached mode, daemonization and remote SSH clients need host-specific adapters; none are bundled. Normal POSIX cleanup terminates the owned process group; deliberately detached child sessions are unsupported. Use a service cgroup for stronger containment. SIGKILL/host crashes may leave POSIX children; interrupted state blocks duplicate automatic starts.

Offline behavior tests have run on Windows and WSL Ubuntu; GitHub Actions also defines a Windows/Linux matrix. See [validation.md](validation.md) and the latest Actions run for actual results. Run the suite on the target GPU server before unattended use; WSL tests do not establish Slurm or production-host behavior. The skill does not automatically install services, change sleep settings, schedule model turns or modify remote hosts.

## Genuine progress

Copy `scripts/progress.py` into the project as `watchdog_progress.py`, or import it from the skill scripts directory. With no watchdog, `report` returns False without writing. Under supervision it inherits attempt-specific environment variables; stale attempts cannot satisfy current progress.

```python
from watchdog_progress import report

for global_step, batch in enumerate(loader, start=1):
    train_step(batch)
    if global_step % 100 == 0:
        report("progress", global_step)

save_final_checkpoint()
report("succeeded")
```

Emit from the primary/rank-0 work loop, not a timer. With asynchronous GPU work, report at an existing synchronization/observed completion point; do not add an expensive GPU sync every step just for monitoring. Choose a reporting interval with little overhead and a global counter spanning epochs/evaluation. Repeated or decreasing values do not reset the stall timer. The progress file is atomically replaced, not appended. Timeout decisions use the supervisor's monotonic clock.

Emit `report("failed", message="...")`, `report("blocked", message="...")` or `report("stopped", message="unexpected stop")` for failure, then stop reporting progress/exit. Another worker must not overwrite terminal events. `report("cancelled")` means intentional cancellation and never invokes repair. The shell helper supports `progress --step 123`, `failed --message ...`, and `succeeded` when run inside the supervised experiment environment.

After integration, example config edits are:

```json
{
  "stall_seconds": 1800,
  "startup_grace_seconds": 900,
  "require_success_event": true
}
```

These are examples, not universal thresholds. Before the first progress, both startup grace and stall interval must elapse. No default time limit applies to the entire experiment.

## Config fields

`init` emits all fields/defaults. Relative project/state paths resolve against the config directory; command arguments resolve in the project. Use absolute interpreter paths for unattended work.

| Field | Default | Meaning |
|---|---:|---|
| `command` | required argv | Foreground experiment, unchanged at restart |
| `env` | `{}` | Extra experiment-only environment, avoid stored secrets |
| `poll_seconds` | 5 | Local checks |
| `status_seconds` | 60 | Local liveness summary and state refresh |
| `stall_seconds` | 0 | Disabled until real progress is integrated |
| `startup_grace_seconds` | 300 | Startup grace for stalls |
| `failure_regex` | `[]` | Opt-in fatal matching on a bounded output window; `(?m)` for line anchors |
| `require_success_event` | false | Require succeeded event plus exit code 0 |
| `log_retention_hours` | 24 | Log chunk retention |
| `log_max_bytes` | 16777216 | Total retained watchdog logs, 16 MiB |
| `log_segment_bytes` | 1048576 | Per chunk maximum, 1 MiB |
| `log_segment_seconds` | 60 | Maximum write interval per chunk |
| `tail_bytes` | 24000 | Recent output attached to a repair prompt |
| `validation.command` | null | Optional local argv check before every experiment launch |
| `validation.timeout_seconds` | 120 | Local check process-tree timeout |
| `local_retry.exit_codes` | `[]` | Explicit positive transient exit codes; success/signals excluded |
| `local_retry.max_attempts` | 0 | Total durable model-free retry budget; disabled by default |
| `local_retry.delay_seconds` | 5 | Initial retry delay |
| `local_retry.backoff` | 2 | Delay multiplier for subsequent retries |
| `local_retry.max_delay_seconds` | 120 | Maximum delay including jitter |
| `local_retry.jitter_fraction` | 0.2 | Additional random fraction of delay, from 0 to this value |
| `repair.enabled` | true | false records failures without repair calls |
| `repair.max_attempts` | 3 | Total durable CLI invocation budget per state directory |
| `repair.cooldown_seconds` | 120 | Interruptible delay before each repair |
| `repair.timeout_seconds` | 900 | Per repair process-tree timeout |
| `repair.model` | null | Inherit CLI model setting |
| `repair.codex_argv` | null | Resolve native Codex/npm Node entry, or explicit argv |
| `repair.same_failure_limit` | 0 | Stop before repair at this consecutive identical-failure count; 0 disables |
| `repair.instructions` | preserve science/data | Authorized changes and experiment invariants |

Use one state directory per experiment; the OS lock protects that directory, not arbitrary duplicate commands under other state directories.

Age retention is chunk-based: records can remain up to the rotation interval plus the next cleanup check past the threshold. Limits cover watchdog logs, not datasets/checkpoints, experiment-created files, Codex global diagnostics, or the latest failure/result snapshots. `--ephemeral` avoids persistent CLI session rollouts. Latest failure evidence stays independently of old log cleanup. Cleanup pauses when the watchdog is stopped and resumes when started.

## Resume and failure limits

Inspect `state.json`, `failure.json`, `repair-result.json`, optional `validation-result.json`, and `logs/`. `repair_attempts` is conservatively charged before CLI launch and is not a token meter. The supervisor validates the CLI exit code and result shape (`decision`, `summary`, `validation`); it cannot independently prove every proposed fix scientifically correct. An optional local validation command supplies an independent executable gate.

After resolving a blocked condition, `run/start --resume` preserves the repair count and starts another experiment attempt. It removes a previous intentional STOP. A completed experiment stays completed. A deliberately new experiment requires a new state directory. Changing project/argv also requires a deliberate new run. Never delete state simply to evade a repair cap.

If the supervisor crashes, it refuses automatic resume of active states such as `running`/`repairing`. Inspect recorded PIDs and the actual process tree, clean up owned processes and review partial code edits, then:

```text
python watchdog.py acknowledge --config <config.json> --processes-cleaned-up
python watchdog.py start --config <config.json> --resume
```

`acknowledge` is an explicit operator assertion, not a cleanup command or proof. It cannot take a live supervisor's lock. No old PID is blindly killed. The retry budget remains intact.

CLI/auth/quota/network errors, output errors, invalid decisions and timeout stop automatic recovery. A repair may partially edit files before timing out; inspect the diff before resuming. Keep checkpoints and use a command with existing safe resume logic. Generic supervision cannot choose the correct checkpoint or guarantee exactly-once writes.

Three invocations and a 15-minute timeout do not impose a hard token/dollar budget; usage varies and stopping a process does not undo already sent requests. Healthy monitoring calls no model. Repairs use normal included usage/credits/API billing. No Claude process is called, and authentication/billing settings are unchanged.

## Optional validation and model-free retries

The following fields illustrate a project that already defines `checks/preflight.py` and reserves exit code 75 for a temporary resource problem. They are not universal defaults:

```json
{
  "validation": {
    "command": ["/work/venv/bin/python", "checks/preflight.py"],
    "timeout_seconds": 120
  },
  "local_retry": {
    "exit_codes": [75],
    "max_attempts": 2,
    "delay_seconds": 5,
    "backoff": 2,
    "max_delay_seconds": 120,
    "jitter_fraction": 0.2
  },
  "repair": {"same_failure_limit": 2}
}
```

Validation runs initially and before every subsequent launch, including after a model repair or local retry. Exit 0 permits the launch; nonzero exit, timeout, launch/output errors block it. A stop request cancels the check and its owned descendants. Failed initial validation never invokes Codex. A failed post-repair check also blocks instead of starting another repair loop. The check inherits the configured experiment environment but no progress-reporting context. Use a trusted, bounded command that checks imports, fixtures or configuration without training, model calls, or destructive side effects. A generic supervisor cannot enforce that a user-supplied command is offline.

Local retry is permitted only after an observed allowlisted nonzero exit. Explicit `failed`/`blocked`/`stopped` events, regex matches, stalls, monitoring errors, and intentional cancellation are not treated as transient exits. The supervisor cleans up the previous process tree first. Delays increase exponentially with random additive jitter and a strict cap. The budget is charged before waiting, survives `--resume`, and never resets after repair. After the local budget is exhausted, the usual model repair policy applies; `repair.enabled: false` still permits configured local retries but never invokes a model. Checkpoint handling and idempotence must come from the experiment itself.

`same_failure_limit: 2` allows the first failure to reach repair, then blocks before a second model call if the next failure is identical. The fingerprint hashes the failure reason plus the last 4,000 characters of experiment output. Variable timestamps, paths or counters can prevent a match: this is conservative exact evidence matching, not semantic classification. All observed experiment failures count, including failures preceding local retries. A changed fingerprint resets the consecutive streak, but never the overall local/model budgets. The streak survives `--resume`.

The state retains at most five recent failure, retry, validation, or repair events, with bounded text fields. This context is supplied to repair as untrusted diagnostic data. It is not an append-only transcript. The latest validation result replaces its predecessor; output tails and rotating logs remain bounded.

## Offline checks

```text
python -m unittest discover -s <skill>/scripts -p test_watchdog.py -v
```

Fixtures simulate success, repair, stalls, failure/stop signals, invalid output, timeouts, persistent budgets, duplicate supervision, descendant cleanup, bounded logs, local validation, transient retries, and repeated-failure blocking without model services. `doctor` only runs `codex exec --help` and `codex login status`; it cannot verify remaining quota or real inference access. A real model-repair integration test consumes usage and must be identified separately.
