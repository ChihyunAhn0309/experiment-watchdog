# Validation record

Tests use fake Codex processes and isolated temporary experiments. They do not perform model inference, launch GPU training, alter account settings, or validate scientific results.

## First independent review

A separate agent, with no inherited conversation, copied the installed baseline into an isolated workspace and exercised realistic failure, cancellation, and repeated-repair scenarios. It identified three reproducible defects:

- Explicit Codex argv could accumulate arguments between repairs.
- A late intentional cancellation event could lose priority to a nonzero process exit.
- A repair output error found during final draining could be discarded before restart.

All were corrected, and five independent regression tests were integrated into the main suite. The reviewer reran the isolated tests after the fixes: 29 passed on Windows. The same revision passed 28 tests on WSL Ubuntu, with one Windows-specific test skipped.

## Reference-informed extension

Added local validation, bounded model-free transient retries, an optional identical-failure breaker, and a five-event recovery history. Fourteen behavioral tests exercise these additions. The expanded 43-test suite passed on Windows (Python 3.11.7) and WSL Ubuntu (42 passed, one Windows-specific skip).

## Second independent review and final fixes

A fresh agent, without inherited conversation or the earlier review's conclusions, inspected an isolated copy of the expanded implementation. It wrote 18 independent scenarios using real subprocesses and a fake repair CLI. It found three reproducible defects:

- A fatal pattern discovered during final output draining could still permit an allowlisted local retry. The main implementation pass also independently reproduced this case.
- A UTF-8 fatal message split across pipe reads could evade regex detection.
- Detached `start --resume` reported a startup error for an already completed experiment, even though it correctly avoided another launch.

The fixes exclude late fatal output from retry eligibility, decode streaming UTF-8 incrementally, and return success for completed resume requests. Three regressions were added to the main suite. An initial Windows CI run also revealed a synthetic crash-state test using an unresolved directory spelling; the fixture now builds its identity from the loaded configuration, as the real supervisor does.

The independent reviewer then copied the corrected source into another snapshot and verified:

- **46/46 bundled tests passed** on Windows/Python 3.11.7 (24.578 seconds).
- **All 18 independent scenarios passed across the final runs**: 17 on the first post-fix run, and the remaining crash-during-repair case on an unchanged sequential rerun. The first attempt at that case reached the fixture's short timeout under host load; the supervisor correctly stopped at its repair budget. A concurrent test-launch attempt also reported a host `System.OutOfMemoryException`. These interrupted attempts were preserved rather than represented as a clean first pass.
- Scenarios covered zero-model healthy runs, doctor arguments, cancellation priority, four concurrent supervisors, persistent budgets, local retry eligibility, independent validation gates, output errors, process-tree cleanup, bounded logs, UTF-8 output, and completed resume behavior.
- No reproducible unresolved code defect remained within that Windows review scope. The audit did not test real model inference or scientific outcomes.

The final reviewed `scripts/watchdog.py` SHA-256 is `7a56e102f60a0ebfd9f947bb65d6b1bfc969363f0139684693a20ebcebcb9ede`.

## Platform evidence and CI

The intermediate 44-test revision passed locally on Windows and WSL Ubuntu (43 passes plus one Windows-only skip on WSL). Its [four-job GitHub CI run](https://github.com/ChihyunAhn0309/experiment-watchdog/actions/runs/37095152858) also passed on Windows Server 2022 and Ubuntu 24.04, each on Python 3.10 and 3.13. The final local WSL rerun was interrupted during host resource pressure, so it is not reported as a final 46-test WSL pass.

The final 46-test code is submitted to the same matrix. Its status is available in the [Actions history](https://github.com/ChihyunAhn0309/experiment-watchdog/actions/workflows/tests.yml) and README badge. Consult the result for the commit being installed; the matrix contains one Windows-only crash-containment test that is skipped on Linux.

## Limits of the evidence

Offline tests establish only the simulated process/control behavior covered by their cases. They do not establish real Codex model access, remaining quota, the quality of generated code repairs, production GPU behavior, or checkpoint correctness for an arbitrary experiment. No real model repair is represented as tested.

Full access does not guarantee successful repairs, and invocation/time limits are not token or currency hard caps. Initial creation and independent agent review are normal model-assisted work; only the offline test processes and healthy monitoring path are claimed to make zero inference calls.
