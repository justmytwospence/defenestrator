"""Command line: `defenestrator run | once | sample | decide | report | seed | costs | backfill | health`."""
from __future__ import annotations

import json
import sys
import time

from . import plan, run
from .influx import Influx

USAGE = """usage: defenestrator <command>

  run        sample and ping forever (what the container runs); --dry-run to only log
  once       one sample-and-decide pass, then exit; --dry-run to only log
  sample     record one usage sample
  decide     print the Claude policy decision as JSON
  report     show the learned profile and the plan
  seed [host...]  rebuild history.jsonl from local session logs (and ssh hosts)
  costs      print this machine's logged use per 10 minutes (what seed runs over ssh)
  backfill   replay usage.jsonl and events.jsonl into InfluxDB (INFLUX_URL, INFLUX_TOKEN, ...)
  health     exit 0 if the loop ran in the last 25 minutes

Environment: see README (QUIET_HOURS, CLAUDE_MODEL, CODEX_MODEL, CODEX=off, DRY_RUN,
INFLUX_*, DEFENESTRATOR_STATE).
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv else "report"
    now = time.time()
    cfg = run.Config()
    if "--dry-run" in argv:
        argv.remove("--dry-run")
        cfg.dry = True
    if cmd in ("run", "once"):
        runner = run.Runner(cfg, influx=Influx.from_env())
        if cmd == "once":
            runner.run_once()
        else:
            runner.loop()
        return 0
    if cmd == "sample":
        return plan.cmd_sample(now)
    if cmd == "decide":
        samples = plan.load_samples()
        print(json.dumps(plan.decide(samples, now, None, plan.load_history(samples[0]["t"] if samples else now))))
        return 0
    if cmd == "report":
        return plan.cmd_report(now)
    if cmd == "seed":
        plan.seed(argv, now)
        return 0
    if cmd == "costs":
        print(json.dumps(plan.log_costs()))
        return 0
    if cmd == "backfill":
        influx = Influx.from_env()
        if not influx:
            print("backfill: set INFLUX_URL and INFLUX_TOKEN", file=sys.stderr)
            return 2
        n, e, err = run.backfill(influx, cfg.state)
        print(f"backfill: {n} samples, {e} events" + (f"; {err}" if err else ""))
        return 1 if err else 0
    if cmd == "health":
        return 0 if run.health(cfg.state) else 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
