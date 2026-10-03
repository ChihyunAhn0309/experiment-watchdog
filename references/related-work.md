# Related work and design decisions

Reviewed 2026-10-03. Sources below are original project documentation, official manuals, or author abstracts. Searches covered zero-LLM experiment monitoring, autonomous experiment skills, Codex interruption recovery, agent watchdogs, local validation, and retry/circuit-breaker designs. This is a curated comparison, not proof of an exhaustive search or independent validation of those projects' advertised behavior. Related repositories and their papers are not counted as independent implementations.

## Existing similar work

Yes: both closely related projects and an existing experiment-orchestration skill are public. Zero-model monitoring is an established architecture. The useful distinction here is a small, host-local supervisor for a fixed experiment command, with explicit failure-triggered Codex repair and no model-based healthy polling.

| Source | Relevant behavior described by its authors | Relationship to this skill |
|---|---|---|
| 1. [auto-deep-researcher-24x7](https://github.com/Xiangyue-Zhang/auto-deep-researcher-24x7) | Autonomous experiment cycles, zero-LLM training monitoring, bounded memory, experiment ledger, dry-run and optional cycle limits. | Closest experiment-level precedent. Inspired bounded recent history and preflight checks. This skill does not select new scientific hypotheses or training recipes. |
| 2. [Auto-Deep-Researcher paper, arXiv:2604.05854](https://arxiv.org/abs/2604.05854) | Describes the same broader research loop and bounded monitoring/context design. | Architectural reference; reported cost or success figures are not measurements of this skill. |
| 3. [AREX autonomous-experiments SKILL.md](https://github.com/VectorSpaceLab/AREX-Skill/blob/main/skills/repositories/repo-skills/auto-deep-researcher-24x7/sub-skills/autonomous-experiments/SKILL.md) | Existing skill for the preceding project, including dry-run before launch, persistent cycle counters and authoritative job-state checks. | Confirms an existing skill-level counterpart. Supports executable preflight and durable budgets, while this skill preserves a fixed experiment. |
| 4. [Ralph for Claude Code](https://github.com/frankbria/ralph-claude-code) | Agent development loop with rate limits, completion gates and repeated-error/no-progress circuit breakers. | Inspired optional identical-failure blocking. Its continuous agent loop and Claude invocation are not incorporated. |
| 5. [Aider linting and testing](https://aider.chat/docs/usage/lint-test.html) | User-configured test commands and automatic testing after edits. | Inspired supervisor-owned local validation after repairs, independent of a model's textual claim. |
| 6. [Supervisor subprocess state machine](https://supervisord.org/subprocess.html) | Startup backoff, finite startup retries, and expected/unexpected exit handling. | Supports explicit retry eligibility and finite attempts. This skill also bounds retries after established runs. |
| 7. [Tenacity documentation](https://tenacity.readthedocs.io/en/latest/) | Conditional retries, exponential waits, jitter, and stopping strategies. | Inspired capped backoff with jitter for a separate model-free retry budget; Tenacity is not a dependency. |
| 8. [systemd service reference source](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml) | Restart policies, excluded exit statuses, and distinction between failure and administrative stop. | Supports preserving intentional cancellation and precise exit-code policy. No system service is silently installed. |
| 9. [TanChuping/codex-task-watchdog](https://github.com/TanChuping/codex-task-watchdog) | Read-only Codex task monitoring, per-attempt arm/heartbeat/disarm, bounded evidence and no automatic wakeup. | Different target: Codex tasks. Reinforces attempt-scoped evidence and avoiding conclusions from missing logs alone. |
| 10. [sybxxx/codex-auto-retry](https://github.com/sybxxx/codex-auto-retry) | Windows recovery of interrupted Codex tasks using app-server/IPC, with limits, backoff and pause handling. | Related recovery tool; desktop task resumption is different from repairing an experiment process. Private desktop coupling is not adopted. |
| 11. [EliteHorizonGames/codex-crash-recovery](https://github.com/EliteHorizonGames/codex-crash-recovery) | Explicitly armed Windows process-loss monitoring, confirmation checks, mutex and pause-aware recovery. | Reinforces explicit activation and intentional-stop handling. Reopening a desktop window is outside this skill's contract. |
| 12. [flowing-water1/codex-watchdog](https://github.com/flowing-water1/codex-watchdog) | Codex CLI continuation after transient/context interruption, with human-pause, authentication, usage and budget stop conditions. | Similar stop-policy concerns but monitors an agent loop rather than a fixed foreground experiment. |
| 13. [tigercosmos/codexmon](https://github.com/tigercosmos/codexmon) | Agent CLI wrapper with phase-aware timeouts, structured status, cancellation and offline fake-agent tests. | Useful cross-check for process lifetime, explicit local state and realistic offline testing. Idle text output is not treated as training progress here. |
| 14. [harveyxiacn/codex-usage-monitor](https://github.com/harveyxiacn/codex-usage-monitor) | Reads local session data to report token usage without model-based monitoring. | Supports separating local observation from inference. It is a usage monitor, not experiment recovery or a guaranteed billing hard cap. |
| 15. [BuilderIO agent-watchdog skill](https://github.com/BuilderIO/skills/blob/main/skills/agent-watchdog/SKILL.md) | Reviews another agent's work against evidence and authorized scope. | An independent model review skill, not a dormant runtime monitor. Relevant to the separate audits used during development. |
| 16. [Agent-MD, arXiv:2608.07637](https://arxiv.org/abs/2608.07637) | Author abstract describes persistent scientific campaigns with deterministic execution and selective event-triggered LLM review. | Broader scientific-workflow precedent for keeping routine execution local. No molecular-simulation component is included. |

## Features adopted in this revision

| Feature | Concrete behavior | Why it fits |
|---|---|---|
| Local preflight and post-repair check | Optional trusted argv runs before every experiment launch; failure/timeout blocks launch. | Detects configuration or repair regressions without asking a model to judge a success message. Inspired by AREX, Auto-Deep-Researcher and Aider. |
| Model-free transient retry | Explicit exit-code allowlist, separate persistent total budget, capped exponential delay and jitter. | Known temporary resource failures need not trigger paid diagnosis immediately. Inspired by Supervisor and Tenacity. |
| Repeated-failure breaker | Optional threshold on consecutive equal hashes of the failure reason and bounded output tail; persists on resume. | Stops unchanged unsuccessful repairs earlier than the overall model-attempt limit. Inspired by Ralph; variable logs intentionally do not match. |
| Bounded recovery history | Last five events only, with clipped text, included as diagnostic data in the next repair prompt. | Provides recent context without an ever-growing transcript. Inspired by Auto-Deep-Researcher's bounded memory. |

These are independent standard-library implementations of general patterns. No external project source code was copied, vendored, executed, or installed for this comparison. Local retries and the repeated-failure breaker are disabled by default because safe exit codes and useful thresholds depend on the experiment. Validation is optional because a valid command cannot be inferred for every project.

Existing behavior retained: attempt-specific progress, explicit cancellation, durable model limits, bounded logs, process-tree cleanup, duplicate-supervisor locks, and structured repair decisions. Autonomous recipe changes, continuous model loops, unrestricted self-improvement, and desktop-session internals are outside this skill's scope.

## 한국어 요약

비슷한 구현은 이미 있습니다. 특히 Auto-Deep-Researcher와 AREX의 실험 자동화 스킬이 가장 가깝습니다. 따라서 이 스킬을 최초 구현이라고 주장하지 않습니다. 이번 비교에서는 사용 목적에 맞는 로컬 검증, 비용 없는 일시 오류 재시도, 같은 실패 반복 차단, 제한된 복구 이력을 채택했습니다.

외부 프로젝트의 기능은 작성자가 공개한 문서 기준입니다. 해당 프로젝트들을 직접 실행해서 검증한 것은 아니며, 논문에 적힌 비용이나 성공률을 이 스킬의 성능으로 제시하지 않습니다. 이 스킬의 테스트와 독립 검수 결과는 별도의 [검증 기록](validation.md)에 정리합니다.
