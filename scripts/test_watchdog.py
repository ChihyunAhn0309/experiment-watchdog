"""Offline behavioral tests. NEVER invokes the actual Codex or any model API."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import watchdog as wd

SCRIPT = str(Path(wd.__file__).resolve())
PROGRESS = str(Path(SCRIPT).with_name("progress.py"))
FIXTURE = r'''
import json,sys,time,os
from pathlib import Path
mode=sys.argv[1]
count=Path('model_calls')
count.write_text(str(int(count.read_text())+1) if count.exists() else '1')
prompt=sys.stdin.buffer.read().decode('utf-8')
Path('received_prompt').write_text(prompt,encoding='utf-8')
if mode=='timeout': time.sleep(20)
if mode=='exit': sys.exit(1)
result=Path(sys.argv[sys.argv.index('-o')+1])
if mode=='invalid': result.write_text('{}'); sys.exit(0)
if mode=='repair': Path('fixed').write_text('yes')
result.write_text(json.dumps({'decision':'blocked' if mode=='blocked' else 'restart',
                             'summary':'fixture decision','validation':'fixture verification'}))
'''


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="watchdog-test-")
        self.root = Path(self.tmp.name)
        self.fake = self.root / "fake_codex.py"
        self.fake.write_text(FIXTURE, encoding="utf-8")
        self.cfg = json.loads(json.dumps(wd.DEFAULTS))
        self.cfg.update(project_dir=str(self.root), state_dir=str(self.root / "state"),
                        command=[sys.executable, "-u", "experiment.py"], poll_seconds=.05,
                        status_seconds=.1, startup_grace_seconds=0,
                        log_segment_bytes=512, log_max_bytes=4096)
        self.cfg["repair"].update(codex_argv=[sys.executable, str(self.fake), "repair"],
                                  cooldown_seconds=0, timeout_seconds=5)
        self.path = self.root / "config.json"
        self.prologue = f"import sys\nsys.path.insert(0, {str(Path(PROGRESS).parent)!r})\nfrom progress import report\n"
        self.processes = []

    def tearDown(self):
        for p in self.processes:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=15)
        self.tmp.cleanup()

    def experiment(self, text):
        (self.root / "experiment.py").write_text(self.prologue + text, encoding="utf-8")

    def write(self):
        wd.atomic_json(self.path, self.cfg)

    def run_watch(self, resume=False):
        self.write()
        p = subprocess.run([sys.executable, SCRIPT, "run", "--config", str(self.path)] + (["--resume"] if resume else []), capture_output=True, text=True, timeout=25)
        return p

    def launch(self):
        self.write()
        p = subprocess.Popen([sys.executable, SCRIPT, "run", "--config", str(self.path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(p)
        return p

    def state(self):
        return wd.read_json(self.root / "state" / "state.json")

    def wait_phase(self, phase):
        until = time.monotonic() + 8
        while time.monotonic() < until:
            try:
                state = self.state()
                if state["phase"] == phase and state.get("child_pid"):
                    return state
            except (OSError, ValueError):
                pass
            time.sleep(.03)
        self.fail(f"Did not reach {phase}")

    def calls(self):
        p = self.root / "model_calls"
        return int(p.read_text()) if p.exists() else 0

    def test_healthy_progress_uses_zero_models(self):
        self.cfg["stall_seconds"] = .5
        self.experiment("import time\nfor i in range(5):\n report('progress',i); time.sleep(.08)\nreport('succeeded')\n")
        p = self.run_watch()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.state()["phase"], "completed")
        self.assertEqual(self.calls(), 0)

    def test_quiet_healthy_job_is_not_a_failure(self):
        self.experiment("import time\ntime.sleep(.35)\n")
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertEqual(self.calls(), 0)

    def test_healthy_path_does_not_even_resolve_codex(self):
        self.cfg["repair"]["codex_argv"] = [str(self.root / "codex-does-not-exist.exe")]
        self.experiment("print('normal experiment')\n")
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertEqual(self.state()["repair_attempts"], 0)

    def test_fail_repair_restart_success(self):
        self.experiment("from pathlib import Path\nprint('intentional failure fixture')\nsys.exit(0 if Path('fixed').exists() else 7)\n")
        p = self.run_watch()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(self.state()["attempt"], 2)
        self.assertEqual(self.state()["repair_attempts"], 1)
        self.assertIn("UNTRUSTED", (self.root / "received_prompt").read_text())

    def test_explicit_blocked_status_stops_a_live_process(self):
        self.cfg["repair"]["codex_argv"][-1] = "blocked"
        self.experiment("import time\nreport('blocked',message='fixture deadlock'); time.sleep(20)\n")
        p = self.run_watch()
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(self.calls(), 1)
        self.assertIn("Explicit blocked", self.state()["failure"])

    def test_advancing_progress_is_required(self):
        self.cfg["stall_seconds"] = .25
        self.cfg["repair"]["codex_argv"][-1] = "blocked"
        self.experiment("import time\nfor i in range(200):\n report('progress',1); time.sleep(.05)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertIn("No advancing progress", self.state()["failure"])
        self.assertEqual(self.calls(), 1)

    def test_stale_event_is_ignored(self):
        wd.atomic_json(self.root / "state" / "progress.json", {"run_id": "old", "status": "failed"})
        self.experiment("import time\ntime.sleep(.12)\n")
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertEqual(self.calls(), 0)

    def test_repair_cap_persists_across_resume(self):
        self.cfg["repair"]["max_attempts"] = 2
        self.experiment("sys.exit(9)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 2)
        self.assertEqual(self.run_watch(resume=True).returncode, 2)
        self.assertEqual(self.calls(), 2)
        self.assertEqual(self.state()["repair_attempts"], 2)

    def test_invalid_result_does_not_restart(self):
        self.cfg["repair"]["codex_argv"][-1] = "invalid"
        self.experiment("sys.exit(1)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.state()["attempt"], 1)
        self.assertEqual(self.calls(), 1)

    def test_cli_error_does_not_loop(self):
        self.cfg["repair"]["codex_argv"][-1] = "exit"
        self.experiment("sys.exit(1)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 1)
        self.assertIn("Codex exited", self.state()["reason"])

    def test_repair_timeout_does_not_loop(self):
        self.cfg["repair"].update(timeout_seconds=.3)
        self.cfg["repair"]["codex_argv"][-1] = "timeout"
        self.experiment("sys.exit(1)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 1)
        self.assertIn("timed out", self.state()["reason"])

    def test_cancel_event_never_repairs(self):
        self.experiment("import time\nreport('cancelled'); time.sleep(20)\n")
        self.assertEqual(self.run_watch().returncode, 130)
        self.assertEqual(self.calls(), 0)

    def test_stop_request_never_repairs(self):
        self.experiment("import time\ntime.sleep(20)\n")
        p = self.launch()
        self.wait_phase("running")
        (self.root / "state" / "STOP").write_text("stop")
        self.assertEqual(p.wait(timeout=10), 130)
        self.assertEqual(self.state()["phase"], "cancelled")
        self.assertEqual(self.calls(), 0)

    def test_stop_during_repair(self):
        self.cfg["repair"]["codex_argv"][-1] = "timeout"
        self.experiment("sys.exit(1)\n")
        p = self.launch()
        self.wait_phase("repairing")
        (self.root / "state" / "STOP").write_text("stop")
        self.assertEqual(p.wait(timeout=10), 130)
        self.assertEqual(self.state()["attempt"], 1)

    def test_stop_during_cooldown_has_zero_model_calls(self):
        self.cfg["repair"]["cooldown_seconds"] = 10
        self.experiment("sys.exit(1)\n")
        p = self.launch()
        until = time.monotonic() + 5
        while time.monotonic() < until:
            try:
                if self.state()["phase"] == "cooldown":
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.03)
        (self.root / "state" / "STOP").write_text("stop")
        self.assertEqual(p.wait(timeout=10), 130)
        self.assertEqual(self.calls(), 0)

    def test_duplicate_watchdog_cannot_start_experiment(self):
        self.experiment("import time\ntime.sleep(20)\n")
        p = self.launch()
        self.wait_phase("running")
        other = self.run_watch(resume=True)
        self.assertEqual(other.returncode, 2)
        self.assertIn("already holds", other.stderr)
        (self.root / "state" / "STOP").write_text("stop")
        p.wait(timeout=10)
        self.assertEqual(self.state()["attempt"], 1)

    def test_log_limits_and_age_pruning(self):
        log = wd.Logs(self.root, self.cfg)
        log.write("fixture", b"x" * 24000)
        files = list(log.root.glob("wd-*.log"))
        self.assertLessEqual(sum(p.stat().st_size for p in files), self.cfg["log_max_bytes"])
        self.assertTrue(all(p.stat().st_size <= self.cfg["log_segment_bytes"] for p in files))
        old = time.time() - 90000
        for p in files:
            os.utime(p, (old, old))
        unrelated = log.root / "user.log"
        unrelated.write_text("keep")
        log.prune()
        self.assertFalse(list(log.root.glob("wd-*.log")))
        self.assertTrue(unrelated.exists())

    def test_output_flood_is_bounded(self):
        self.experiment("sys.stdout.write('x'*1000000)\n")
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertLessEqual(sum(p.stat().st_size for p in (self.root / "state" / "logs").glob("wd-*.log")), 4096)
        self.assertEqual(self.calls(), 0)

    def test_success_signal_required_when_configured(self):
        self.cfg["require_success_event"] = True
        self.cfg["repair"]["enabled"] = False
        self.experiment("pass\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 0)
        self.experiment("report('succeeded')\n")
        self.assertEqual(self.run_watch(resume=True).returncode, 0)

    def test_regex_opt_in_detects_last_output(self):
        self.cfg["failure_regex"] = [r"^FATAL_WATCHDOG:"]
        self.cfg["repair"]["enabled"] = False
        self.experiment("print('FATAL_WATCHDOG: failure')\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertIn("pattern matched", self.state()["failure"])

    def test_large_repair_prompt_does_not_use_command_line(self):
        self.cfg["repair"]["codex_argv"][-1] = "blocked"
        self.cfg["repair"]["instructions"] = "Korean 한국어 " * 6000
        self.experiment("sys.exit(1)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 1)
        self.assertGreater((self.root / "received_prompt").stat().st_size, 60000)

    def test_korean_failure_evidence_is_readable(self):
        self.cfg["repair"]["codex_argv"][-1] = "blocked"
        self.experiment("print('실험 오류: 입력 데이터 누락')\nsys.exit(1)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        evidence = (self.root / "received_prompt").read_text(encoding="utf-8")
        self.assertIn("실험 오류: 입력 데이터 누락", evidence)

    def test_descendant_is_stopped_when_root_exits(self):
        descendant = self.root / "descendant.py"
        descendant.write_text("import time\nfrom pathlib import Path\nwhile True:\n Path('ticks').write_text(str(time.time())); time.sleep(.05)\n")
        self.experiment("import subprocess,time\nsubprocess.Popen([sys.executable,'descendant.py'])\ntime.sleep(.25)\n")
        self.assertEqual(self.run_watch().returncode, 0)
        before = (self.root / "ticks").read_text()
        time.sleep(.2)
        self.assertEqual((self.root / "ticks").read_text(), before)

    def test_crash_state_cannot_automatically_duplicate_work(self):
        # Config loading resolves directory spelling (including Windows runner
        # short paths/case); synthetic crash state must use that same identity.
        self.write()
        loaded = wd.config_load(self.path)
        identity = wd.hashlib.sha256(json.dumps([loaded["project_dir"], loaded["command"]], ensure_ascii=False).encode()).hexdigest()
        wd.atomic_json(self.root / "state" / "state.json", {"identity": identity, "phase": "repairing", "repair_attempts": 1})
        self.experiment("sys.exit(0)\n")
        p = self.run_watch(resume=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("Interrupted supervisor", p.stderr)
        self.assertEqual(self.calls(), 0)


    def test_multiple_repairs_preserve_strict_cli_argv(self):
        self.fake.write_text(r'''
import sys,json
from pathlib import Path
args=sys.argv[2:]
count=Path('model_calls')
n=int(count.read_text())+1 if count.exists() else 1
count.write_text(str(n))
Path('argv-'+str(n)+'.json').write_text(json.dumps(args))
if args.count('exec') != 1 or args.count('--sandbox') != 1 or args.count('-') != 1:
    print('FAKE STRICT PARSER: unexpected duplicate exec/flags',flush=True)
    sys.exit(2)
sys.stdin.buffer.read()
Path('fixed-'+str(n)).write_text('yes')
Path(args[args.index('-o')+1]).write_text(json.dumps({
 'decision':'restart','summary':'fixed current failure','validation':'targeted check passed'}))
''', encoding="utf-8")
        self.experiment("from pathlib import Path\nif not Path('fixed-1').exists(): sys.exit(11)\nif not Path('fixed-2').exists(): sys.exit(12)\nreport('succeeded')\n")
        self.cfg["require_success_event"] = True
        result = self.run_watch()
        details = {"returncode": result.returncode, "state": self.state(),
                   "argv": [json.loads(p.read_text()) for p in sorted(self.root.glob("argv-*.json"))]}
        self.assertEqual(result.returncode, 0, json.dumps(details, indent=2))
        self.assertEqual(self.calls(), 2)
        self.assertEqual(self.state()["attempt"], 3)

    def test_cancelled_event_wins_when_written_between_event_read_and_nonzero_exit_poll(self):
        self.cfg["repair"]["codex_argv"][-1] = "blocked"
        self.experiment("import time\nfrom pathlib import Path\nwhile not Path('release').exists(): time.sleep(.005)\nreport('cancelled',message='operator stop')\nsys.exit(23)\n")
        sup = wd.Supervisor(self.cfg)
        original_read = wd.read_json
        injected = False
        def read_with_barrier(path, *args):
            nonlocal injected
            if Path(path).name == "progress.json" and not injected:
                injected = True
                # The event snapshot is empty. The child writes its cancellation
                # immediately afterward, before the following poll sees exit 23.
                (self.root / "release").write_text("go")
                sup.child.p.wait(timeout=5)
                return {}
            return original_read(path, *args)
        with patch.object(wd, "read_json", side_effect=read_with_barrier):
            rc = sup.run()
        details = {"returncode": rc, "model_calls": self.calls(), "state": self.state()}
        self.assertEqual(rc, 130, json.dumps(details, indent=2))
        self.assertEqual(self.calls(), 0)

    def test_late_repair_output_write_error_blocks_restart(self):
        self.fake.write_text(self.fake.read_text(encoding="utf-8") + "\nprint('last repair output', flush=True)\n", encoding="utf-8")
        self.experiment("from pathlib import Path\nsys.exit(0 if Path('fixed').exists() else 1)\n")
        sup = wd.Supervisor(self.cfg)
        original_child = wd.Child
        class SlowRepairPump(original_child):
            def _pump(self):
                if self.label == "codex":
                    # Force drain after exit poll, as may happen with a scheduled
                    # output thread or delayed filesystem writes.
                    self.p.wait(timeout=5)
                    time.sleep(.15)
                return super()._pump()
        original_write = sup.logs.write
        def fail_codex_log(source, data):
            if source == "codex":
                raise OSError("simulated disk-full during final output drain")
            return original_write(source, data)
        with patch.object(wd, "Child", SlowRepairPump), patch.object(sup.logs, "write", side_effect=fail_codex_log):
            rc = sup.run()
        details = {"returncode": rc, "model_calls": self.calls(), "state": self.state()}
        self.assertEqual(rc, 2, json.dumps(details, indent=2))
        self.assertEqual(self.state()["attempt"], 1)
        self.assertEqual(self.state()["phase"], "blocked")

    def test_repair_timeout_kills_repair_descendants(self):
        self.cfg["repair"]["timeout_seconds"] = .7
        (self.root / "tick.py").write_text("import time\nfrom pathlib import Path\nwhile True:\n Path('repair-ticks').write_text(str(time.time())); time.sleep(.03)\n")
        self.fake.write_text("import sys,subprocess,time\nsubprocess.Popen([sys.executable,'tick.py'])\ntime.sleep(20)\n")
        self.experiment("sys.exit(1)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        before = (self.root / "repair-ticks").read_text()
        time.sleep(.2)
        self.assertEqual((self.root / "repair-ticks").read_text(), before)
        self.assertEqual(self.state()["attempt"], 1)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object crash containment")
    def test_supervisor_crash_kills_experiment_descendants(self):
        (self.root / "tick.py").write_text("import time\nfrom pathlib import Path\nwhile True:\n Path('crash-ticks').write_text(str(time.time())); time.sleep(.03)\n")
        self.experiment("import subprocess,time\nsubprocess.Popen([sys.executable,'tick.py'])\ntime.sleep(20)\n")
        proc = self.launch()
        self.wait_phase("running")
        until = time.monotonic() + 5
        while not (self.root / "crash-ticks").exists() and time.monotonic() < until:
            time.sleep(.03)
        proc.kill()
        proc.wait(timeout=5)
        time.sleep(.1)
        before = (self.root / "crash-ticks").read_text()
        time.sleep(.2)
        self.assertEqual((self.root / "crash-ticks").read_text(), before)
        blocked = self.run_watch(resume=True)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("Interrupted supervisor", blocked.stderr)
        self.assertEqual(self.calls(), 0)

    def test_allowlisted_transient_exit_retries_without_a_model(self):
        self.cfg["local_retry"].update(exit_codes=[75], max_attempts=2, delay_seconds=0)
        self.experiment("from pathlib import Path\np=Path('attempts')\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\nsys.exit(75 if n<3 else 0)\n")
        result = self.run_watch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.state()["local_retry_attempts"], 2)
        self.assertEqual(self.state()["attempt"], 3)

    def test_unlisted_exit_goes_directly_to_repair(self):
        self.cfg["local_retry"].update(exit_codes=[75], max_attempts=2, delay_seconds=0)
        self.cfg["repair"]["codex_argv"][-1] = "blocked"
        self.experiment("sys.exit(7)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(self.state()["local_retry_attempts"], 0)

    def test_local_retry_budget_persists_after_resume(self):
        self.cfg["local_retry"].update(exit_codes=[75], max_attempts=1, delay_seconds=0)
        self.cfg["repair"]["enabled"] = False
        self.experiment("sys.exit(75)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.state()["attempt"], 2)
        self.assertEqual(self.run_watch(resume=True).returncode, 2)
        self.assertEqual(self.state()["attempt"], 3)
        self.assertEqual(self.state()["local_retry_attempts"], 1)
        self.assertEqual(self.calls(), 0)

    def test_terminal_event_does_not_take_transient_retry_path(self):
        self.cfg["local_retry"].update(exit_codes=[75], max_attempts=2, delay_seconds=0)
        self.cfg["repair"]["enabled"] = False
        self.experiment("report('blocked',message='manual intervention required')\nsys.exit(75)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.state()["local_retry_attempts"], 0)

    def test_fatal_pattern_found_during_final_drain_disallows_local_retry(self):
        class ExitedProcess:
            pid = 12345
            def poll(self):
                return 75

        class LateFatalChild:
            def __init__(self, *args, **kwargs):
                self.p = ExitedProcess()
                self.failure = None
                self.error = None

            def close(self):
                self.failure = "Configured fatal log pattern matched"
                return "FATAL: invalid dataset"

        supervisor = wd.Supervisor(self.cfg)
        supervisor.state = {"attempt": 0}
        with patch.object(wd, "Child", LateFatalChild):
            reason, _ = supervisor.experiment()
        self.assertIsNotNone(reason)
        self.assertFalse(supervisor.state["retryable_exit"])

    def test_local_backoff_is_capped_with_jitter(self):
        policy = dict(self.cfg["local_retry"], delay_seconds=2, backoff=2, max_delay_seconds=9, jitter_fraction=.5)
        with patch.object(wd.random, "uniform", return_value=.5):
            self.assertEqual(wd.local_retry_delay(policy, 0), 3)
            self.assertEqual(wd.local_retry_delay(policy, 1), 6)
            self.assertEqual(wd.local_retry_delay(policy, 999999), 9)

    def test_cancel_during_local_retry_wait_has_zero_model_calls(self):
        self.cfg["local_retry"].update(exit_codes=[75], max_attempts=2, delay_seconds=10, jitter_fraction=0)
        self.experiment("sys.exit(75)\n")
        proc = self.launch()
        until = time.monotonic() + 5
        while time.monotonic() < until:
            try:
                if self.state()["phase"] == "local_retry_wait":
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.03)
        (self.root / "state" / "STOP").write_text("stop")
        self.assertEqual(proc.wait(timeout=10), 130)
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.state()["attempt"], 1)

    def test_preflight_failure_never_launches_experiment_or_model(self):
        self.cfg["validation"]["command"] = [sys.executable, "-c", "raise SystemExit(4)"]
        self.experiment("from pathlib import Path\nPath('launched').touch()\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertFalse((self.root / "launched").exists())
        self.assertEqual(self.state()["attempt"], 0)
        self.assertEqual(self.calls(), 0)

    def test_validation_runs_before_start_and_after_repair(self):
        validator = self.root / "validate.py"
        validator.write_text("from pathlib import Path\np=Path('validations')\np.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n")
        self.cfg["validation"]["command"] = [sys.executable, str(validator)]
        self.experiment("from pathlib import Path\nsys.exit(0 if Path('fixed').exists() else 1)\n")
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertEqual((self.root / "validations").read_text(), "2")
        self.assertEqual(self.calls(), 1)

    def test_failed_post_repair_validation_blocks_restart(self):
        self.cfg["validation"]["command"] = [sys.executable, "-c", "from pathlib import Path; raise SystemExit(5 if Path('model_calls').exists() else 0)"]
        self.experiment("sys.exit(1)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(self.state()["attempt"], 1)
        self.assertIn("Local validation exited", self.state()["reason"])

    def test_validation_timeout_stops_without_a_model(self):
        self.cfg["validation"].update(command=[sys.executable, "-c", "import time; time.sleep(20)"], timeout_seconds=.15)
        self.experiment("sys.exit(0)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.state()["attempt"], 0)
        self.assertIn("timed out", self.state()["reason"])

    def test_stop_during_validation_is_intentional(self):
        self.cfg["validation"]["command"] = [sys.executable, "-c", "import time; time.sleep(20)"]
        self.experiment("sys.exit(0)\n")
        proc = self.launch()
        self.wait_phase("validating")
        (self.root / "state" / "STOP").write_text("stop")
        self.assertEqual(proc.wait(timeout=10), 130)
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.state()["attempt"], 0)

    def test_identical_failure_circuit_breaker_survives_resume(self):
        self.cfg["repair"].update(max_attempts=5, same_failure_limit=2)
        self.experiment("print('same deterministic failure')\nsys.exit(8)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 1)
        self.assertIn("Repeated identical failure", self.state()["reason"])
        self.assertEqual(self.run_watch(resume=True).returncode, 2)
        self.assertEqual(self.calls(), 1)

    def test_changed_failure_evidence_resets_only_failure_streak(self):
        self.cfg["repair"].update(max_attempts=2, same_failure_limit=2)
        self.experiment("from pathlib import Path\np=Path('counter')\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\nprint('failure',n)\nsys.exit(8)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        self.assertEqual(self.calls(), 2)
        self.assertEqual(self.state()["same_failure_count"], 1)
        self.assertEqual(self.state()["repair_attempts"], 2)

    def test_recovery_history_is_bounded_and_included_as_evidence(self):
        self.cfg["repair"]["max_attempts"] = 4
        self.experiment("sys.exit(8)\n")
        self.assertEqual(self.run_watch().returncode, 2)
        history = self.state()["history"]
        self.assertEqual(len(history), 5)
        self.assertTrue(all(len(v) <= 1024 for item in history for v in item.values() if isinstance(v, str)))
        prompt = (self.root / "received_prompt").read_text(encoding="utf-8")
        self.assertIn('"recent_history"', prompt)
        self.assertIn('fixture decision', prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
