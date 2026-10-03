# Validation record

Tests use fake Codex processes and isolated temporary experiments. They do not perform model inference, launch GPU training, alter account settings, or validate scientific results.

## First independent review

A separate agent, with no inherited conversation, copied the installed baseline into an isolated workspace and exercised realistic failure, cancellation, and repeated-repair scenarios. It identified three reproducible defects:

- Explicit Codex argv could accumulate arguments between repairs.
- A late intentional cancellation event could lose priority to a nonzero process exit.
- A repair output error found during final draining could be discarded before restart.

All were corrected, and five independent regression tests were integrated into the main suite. The reviewer reran the isolated tests after the fixes: 29 passed on Windows. The same revision passed 28 tests on WSL Ubuntu, with one Windows-specific test skipped.

## Reference-informed extension

Added local validation, bounded model-free transient retries, an optional identical-failure breaker, and a five-event recovery history. Fourteen behavioral tests exercise these additions. The 43-test suite passed on Windows (Python 3.11.7). A fresh independent review of this expanded revision is in progress; this record will be updated with its actual outcome before delivery.

## Limits of the evidence

Offline tests establish only the simulated process/control behavior covered by their cases. They do not establish real Codex model access, remaining quota, the quality of generated code repairs, production GPU behavior, or checkpoint correctness for an arbitrary experiment. No real model repair is represented as tested.

The GitHub Actions workflow defines Ubuntu 24.04 and Windows Server 2022 jobs on Python 3.10 and 3.13. Check the workflow result for the relevant commit; a workflow file alone is not proof that CI passed.
