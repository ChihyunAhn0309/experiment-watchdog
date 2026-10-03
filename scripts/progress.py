"""Call report('progress', step) after real work; no third-party dependencies."""
import argparse
import json
import math
import os
from pathlib import Path
import time
import uuid


def report(status="progress", progress=None, message=""):
    if status not in {"progress", "failed", "blocked", "stopped", "cancelled", "succeeded"}:
        raise ValueError("Unknown status")
    if status == "progress" and (isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress)):
        raise ValueError("Progress must be a finite numeric, increasing counter")
    filename = os.environ.get("EXPERIMENT_WATCHDOG_STATUS")
    run_id = os.environ.get("EXPERIMENT_WATCHDOG_RUN_ID")
    if not filename or not run_id:
        return False  # The experiment also works without a watchdog.
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    event = {"run_id": run_id, "status": status, "progress": progress, "message": str(message)[:2000], "time": time.time()}
    try:
        tmp.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("status", choices=["progress", "failed", "blocked", "stopped", "cancelled", "succeeded"])
    p.add_argument("--step", type=float)
    p.add_argument("--message", default="")
    args = p.parse_args()
    if not report(args.status, args.step, args.message):
        p.error("Run this helper as part of the supervised experiment so it inherits the watchdog environment")
