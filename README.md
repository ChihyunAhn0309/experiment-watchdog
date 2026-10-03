# Experiment Watchdog

[![Offline watchdog tests](https://github.com/ChihyunAhn0309/experiment-watchdog/actions/workflows/tests.yml/badge.svg)](https://github.com/ChihyunAhn0309/experiment-watchdog/actions/workflows/tests.yml)

Keep long-running experiments under local supervision. Invoke Codex only after a failure to diagnose, repair, validate, and restart the same experiment command.

**Healthy monitoring makes zero model inference calls.** A small Python process checks the experiment locally. Setup conversations and actual Codex repairs use normal account usage or API billing. GPU, electricity, and experiment-specific API costs are separate.

## How it works

```text
Experiment running → local process/progress checks → normal completion
                                │
                            failure
                                ↓
                   stop owned experiment processes
                                ↓
                   Codex: diagnose → fix → validate
                                ↓
                    restart the configured command
```

- Nonzero exits and explicit failure signals work without a model reading logs continuously.
- Optional progress counters detect stalls; output silence alone is never a default failure signal.
- Logs have time and size limits: 24 hours and 16 MiB by default.
- Default recovery limits: 3 total attempts per state directory, a 120-second cooldown, and 15 minutes per repair.
- A persistent attempt count, OS lock, and process-tree cleanup prevent duplicate supervision and unbounded repair loops.
- Intentional cancellation does not trigger recovery. Auth/quota errors, timeout, invalid results, and blocked decisions stop automatic repair.
- Optional local checks run before the first launch and after repairs; a failed check prevents restart.
- Known transient exit codes can use bounded local retries with backoff and jitter, without invoking Codex.
- An optional identical-failure limit stops repeated unsuccessful recovery; the last five recovery events provide bounded diagnostic context.

The recovery process uses full-access Codex with no interactive approval. This is appropriate only for the scope you have authorized. It does not change your global Codex configuration. Repair instructions preserve datasets, checkpoints, seeds, hyperparameters, and experiment meaning by default.

## Install as a Codex skill

Requires Python 3.10+ and an authenticated Codex CLI on the experiment's execution host. The watchdog itself uses only the Python standard library.

PowerShell:

```powershell
git clone https://github.com/ChihyunAhn0309/experiment-watchdog.git "$env:USERPROFILE/.codex/skills/experiment-watchdog"
```

Linux/macOS:

```bash
git clone https://github.com/ChihyunAhn0309/experiment-watchdog.git "${CODEX_HOME:-$HOME/.codex}/skills/experiment-watchdog"
```

If the destination already exists, inspect and update it instead of overwriting local changes. When `CODEX_HOME` is customized on Windows, use its `skills` directory.

Then ask Codex in the experiment project:

> Use $experiment-watchdog to supervise this experiment. Do not invoke a model during healthy execution. Repair only after failure, preserving the existing checkpoint-resume behavior.

## Run directly

Replace the example paths and experiment arguments with your actual environment. The command must represent a foreground process, not a detached job submission.

```bash
python scripts/watchdog.py init --config /work/project/watchdog.json --project /work/project -- /work/venv/bin/python -u train.py
python scripts/watchdog.py doctor --config /work/project/watchdog.json
python scripts/watchdog.py start --config /work/project/watchdog.json
python scripts/watchdog.py status --config /work/project/watchdog.json
python scripts/watchdog.py stop --config /work/project/watchdog.json
```

Use `run` instead of `start` for foreground diagnostics. `start` detaches the supervisor and hides its helper window on Windows. `doctor` checks local CLI flags and authentication; it does not request inference. After correcting a blocked condition, use `start --config ... --resume`; the repair count remains intact.

## Detect stalled work

Copy `scripts/progress.py` into your project as `watchdog_progress.py`, and report from the real training loop:

```python
from watchdog_progress import report

for global_step, batch in enumerate(loader, start=1):
    train_step(batch)
    if global_step % 100 == 0:
        report("progress", global_step)

save_final_checkpoint()
report("succeeded")
```

Choose a global counter across epochs, report from rank 0 for distributed jobs, and report at an existing observed completion point for asynchronous GPU work. Do not use an independent timer as proof of progress. Enable `stall_seconds` only after integrating the signal, with thresholds beyond normal evaluation, startup, and checkpoint delays. Set `require_success_event` if exit code 0 alone is insufficient.

## Boundaries

- The host and supervisor must remain running. For remote training, deploy them on the server itself.
- Recovery starts a fresh Codex CLI invocation; the desktop application does not need to stay open.
- Invocation/time limits are not hard token or currency limits. Recovery can consume usage.
- Automatic repair is not guaranteed to resolve every failure. Preserve and inspect partial edits after a repair timeout.
- Checkpoint resume must already be supported by the experiment command. Scientific correctness still requires experiment-specific validation.
- Slurm, Kubernetes, detached containers, and deliberately daemonized child processes require separate adapters.
- Only watchdog-owned log chunks are rotated. Experiment-created files, checkpoints, and datasets are preserved.

See [operation/configuration details](references/operations.md), [skill instructions](SKILL.md), and [official CLI references](references/sources.md).

## Related work

This is not the first zero-model monitoring or agent recovery design. [auto-deep-researcher-24x7](https://github.com/Xiangyue-Zhang/auto-deep-researcher-24x7) and its [AREX skill](https://github.com/VectorSpaceLab/AREX-Skill/blob/main/skills/repositories/repo-skills/auto-deep-researcher-24x7/sub-skills/autonomous-experiments/SKILL.md) cover broader autonomous research. Codex watchdog projects target interrupted agent sessions rather than the experiment process.

The [16-source comparison](references/related-work.md) records overlap, differences, and the sources behind local validation, bounded retries, repeated-failure limits, and bounded history. External implementations were not executed or vendored; the supervisor remains standard-library-only and focused on preserving the same experiment.

## Offline tests

```bash
python -m unittest discover -s scripts -p test_watchdog.py -v
```

Tests use isolated experiments and a fake Codex executable. They do not contact any model API or run real training jobs. GitHub Actions runs the same suite on Windows and Linux; check the run results for the exact commit before relying on a platform claim.

See the [validation record](references/validation.md) for independent review and the distinction between simulated recovery and real model repair.

## 한국어 안내

정상 실행 중에는 로컬 Python 프로그램만 실험을 확인합니다. 감시를 위한 Codex·Claude 모델 호출은 0회이며, 실패를 감지했을 때만 Codex CLI로 분석·수정·검증을 실행합니다. 초기 설정 대화와 실제 복구에는 일반적인 사용량이 발생합니다.

스킬 설치 후 실험 프로젝트에서 다음과 같이 요청하세요.

> `$experiment-watchdog 이 실험에 연결해줘. 정상 실행 중에는 모델을 호출하지 말고, 실패할 때만 복구해줘. 기존 체크포인트 재개 방식을 유지해줘.`

프로세스가 살아 있지만 학습이 전진하지 않는 상황까지 감지하려면 실제 작업 루프에 진행 신호를 연결해야 합니다. 정체 감지는 기본적으로 꺼져 있습니다. 로그가 조용하다는 이유만으로 실패로 판정하지 않습니다. 의도적으로 중지할 때는 `stop` 명령을 사용하세요.

선택 설정으로 실행 전·복구 후 로컬 검사, 지정한 일시적 종료 코드의 모델 없는 재시도, 동일 실패 반복 차단을 사용할 수 있습니다. 최근 복구 이력은 최대 5개만 보관합니다. 기존 유사 스킬과 프로젝트의 비교 및 채택 이유는 [참고 자료](references/related-work.md), 설정 예시는 [운영 안내](references/operations.md)에 정리했습니다.
