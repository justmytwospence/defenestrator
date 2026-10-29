"""Tests for the scheduler and the InfluxDB line protocol; fake CLIs, temp state, no network."""
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from defenestrator import codex, influx, plan, run  # noqa: E402


class FakeCli:
    def __init__(self, status=None, codex=False, limits=None, reset=None):
        self.status = {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"} if status is None else status
        self.codex, self.limits, self.reset = codex, limits, reset
        self.pings = 0
        self.codex_pings = 0

    def have(self, name):
        return name == "claude" or self.codex

    def claude_status(self):
        return self.status

    def claude_ping(self):
        self.pings += 1
        return self.reset

    def codex_logged_in(self):
        return True

    def codex_limits(self):
        if isinstance(self.limits, list):
            return self.limits.pop(0) if len(self.limits) > 1 else self.limits[0]
        return self.limits

    def codex_ping(self):
        self.pings += 1
        self.codex_pings += 1
        return True


# `account/rateLimits/read` rateLimits on a weekly-only plan, as captured from codex-cli 0.157.
WEEKLY_ONLY = {"limitId": "codex", "planType": "prolite", "secondary": None,
               "primary": {"usedPercent": 1, "windowDurationMins": 10080, "resetsAt": 1793809971}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = self.tmp.name
        patches = [unittest.mock.patch.object(plan, "STATE", self.state),
                   unittest.mock.patch.object(plan, "SAMPLES", os.path.join(self.state, "usage.jsonl")),
                   unittest.mock.patch.object(plan, "HISTORY", os.path.join(self.state, "history.jsonl")),
                   unittest.mock.patch.object(plan, "take_sample", return_value=(None, "no credentials")),
                   unittest.mock.patch.object(plan, "log_costs", return_value={})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self.logs = []

    def runner(self, cli, dry=False, **env):
        cfg = run.Config({"DRY_RUN": "1" if dry else "", **env})
        cfg.state = self.state
        return run.Runner(cfg, cli, None, self.logs.append)

    def events(self):
        try:
            return [json.loads(line) for line in open(os.path.join(self.state, "events.jsonl"))]
        except OSError:
            return []


class RunnerTests(Base):
    NOW = 1_800_000_000

    def test_learning_ping_is_sent_and_recorded(self):
        cli = FakeCli(reset=self.NOW + 18000)
        self.runner(cli).run_once(self.NOW)
        self.assertEqual(cli.pings, 1)
        kinds = [e["kind"] for e in self.events()]
        self.assertIn("ping", kinds)
        ping = [e for e in self.events() if e["kind"] == "ping"][0]
        self.assertEqual((ping["provider"], ping["reset"]), ("claude", self.NOW + 18000))
        self.assertEqual(int(open(os.path.join(self.state, "claude")).read()), self.NOW + 18000)

    def test_running_window_does_not_ping_and_logs_once(self):
        cli = FakeCli()
        Path(self.state, "claude").write_text(str(self.NOW + 3600))
        r = self.runner(cli)
        r.run_once(self.NOW)
        r.run_once(self.NOW + 600)
        self.assertEqual(cli.pings, 0)
        self.assertEqual([e["kind"] for e in self.events() if e["provider"] == "claude"].count("window-running"), 1)

    def test_dry_run_logs_would_ping_and_writes_no_state(self):
        cli = FakeCli()
        self.runner(cli, dry=True).run_once(self.NOW)
        self.assertEqual(cli.pings, 0)
        self.assertIn("would-ping", [e["kind"] for e in self.events()])
        self.assertFalse(os.path.exists(os.path.join(self.state, "claude")))

    def test_not_logged_in_is_a_skip_event(self):
        self.runner(FakeCli(status={"loggedIn": False})).run_once(self.NOW)
        self.assertEqual([(e["provider"], e["kind"]) for e in self.events()], [("sampler", "error"), ("claude", "skip")])

    def test_quiet_hours_skip_pings(self):
        cli = FakeCli(reset=self.NOW)
        hour = time.localtime(self.NOW).tm_hour
        self.runner(cli, QUIET_HOURS=f"{hour}-{(hour + 1) % 24}").run_once(self.NOW)
        self.assertEqual(cli.pings, 0)
        self.assertIn("quiet-hours", [e["kind"] for e in self.events()])

    def test_codex_weekly_only_plan_is_sampled_but_never_pinged(self):
        cli = FakeCli(codex=True, limits=WEEKLY_ONLY, reset=self.NOW + 100)
        self.runner(cli).run_once(self.NOW)
        self.assertEqual(cli.codex_pings, 0)
        samples = plan.load_samples(os.path.join(self.state, "usage.codex.jsonl"))
        self.assertEqual(len(samples), 1)
        self.assertEqual((samples[0].get("u5"), samples[0]["u7"]), (None, 1.0))
        self.assertIn(("codex", "skip"), [(e["provider"], e["kind"]) for e in self.events()])

    def test_codex_five_hour_window_running_is_left_alone(self):
        limits = {"planType": "plus", "primary": {"usedPercent": 30, "windowDurationMins": 300, "resetsAt": self.NOW + 3600},
                  "secondary": {"usedPercent": 10, "windowDurationMins": 10080, "resetsAt": self.NOW + 86400}}
        cli = FakeCli(codex=True, limits=limits)
        self.runner(cli).run_once(self.NOW)
        self.assertEqual(cli.codex_pings, 0)
        self.assertIn(("codex", "window-running"), [(e["provider"], e["kind"]) for e in self.events()])
        self.assertEqual(int(open(os.path.join(self.state, "codex")).read()), self.NOW + 3600)

    def test_codex_idle_five_hour_window_is_pinged_and_its_reset_recorded(self):
        idle = {"planType": "plus", "primary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": self.NOW - 600}}
        after = {"planType": "plus", "primary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": self.NOW + 18000}}
        cli = FakeCli(codex=True, limits=[idle, after])
        self.runner(cli).run_once(self.NOW)
        self.assertEqual(cli.codex_pings, 1)
        pings = [e for e in self.events() if e["kind"] == "ping" and e["provider"] == "codex"]
        self.assertEqual([p["reset"] for p in pings], [self.NOW + 18000])
        self.assertEqual(int(open(os.path.join(self.state, "codex")).read()), self.NOW + 18000)

    def test_codex_dry_run_does_not_ping(self):
        idle = {"planType": "plus", "primary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": 0}}
        cli = FakeCli(codex=True, limits=idle)
        self.runner(cli, dry=True).run_once(self.NOW)
        self.assertEqual(cli.codex_pings, 0)
        self.assertIn(("codex", "would-ping"), [(e["provider"], e["kind"]) for e in self.events()])

    def test_next_wake_is_the_earliest_reset_plus_buffer(self):
        r = self.runner(FakeCli())
        self.assertEqual(r.next_wake(self.NOW), self.NOW + 600)
        Path(self.state, "claude").write_text(str(self.NOW + 100))
        self.assertEqual(r.next_wake(self.NOW), self.NOW + 100 + run.BUFFER)
        Path(self.state, "claude.plan").write_text(str(self.NOW + 2))
        self.assertEqual(r.next_wake(self.NOW), self.NOW + 5)  # never sooner than 5 s

    def test_health_follows_the_heartbeat(self):
        self.assertFalse(run.health(self.state))
        self.runner(FakeCli()).run_once()
        self.assertTrue(run.health(self.state))


class InfluxTests(unittest.TestCase):
    def test_usage_line_omits_missing_fields(self):
        line = influx.usage_line({"t": 5, "u5": 3.0, "u7": None, "reset5": 9.5, "capped": False}, "NUC")
        self.assertEqual(line, "defenestrator_usage,host=NUC,provider=claude u5=3.0,reset5=9.5,capped=false 5")

    def test_event_line_escapes(self):
        line = influx.event_line({"t": 7, "provider": "claude", "kind": "ping", "reason": 'say "hi"', "reset": 8}, "my host")
        self.assertEqual(line, 'defenestrator_event,host=my\\ host,provider=claude,kind=ping reason="say \\"hi\\"",reset=8.0 7')

    def test_from_env_needs_url_and_token(self):
        self.assertIsNone(influx.Influx.from_env({}))
        self.assertEqual(influx.Influx.from_env({"INFLUX_URL": "http://i:8086/", "INFLUX_TOKEN": "t"}).url, "http://i:8086")

    def test_backfill_replays_both_files_and_defaults_old_events_to_ping(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "usage.jsonl").write_text('{"t":1,"u5":1.0,"reset5":2.0,"u7":3.0,"reset7":4.0,"capped":false}\n')
            Path(d, "events.jsonl").write_text('{"t":2,"provider":"claude","reset":9}\n')
            fake = unittest.mock.Mock()
            fake.write_usage.return_value = None
            fake.write_events.return_value = None
            fake.write_use.return_value = None
            with unittest.mock.patch.object(plan, "use_by_bin", return_value={}):
                n, e, err = run.backfill(fake, d)
            self.assertEqual((n, e, err), (1, 1, None))
            self.assertEqual(fake.write_events.call_args[0][0][0]["kind"], "ping")


if __name__ == "__main__":
    unittest.main()


class UseTests(unittest.TestCase):
    def test_use_line(self):
        line = influx.use_line(3600, "opus", "my project", 2.0, 0.5, "NUC")
        self.assertEqual(line, "defenestrator_use,host=NUC,model=opus,project=my\\ project cost=2.0,pct=1.0 3600")

    def test_project_names(self):
        self.assertEqual(plan.project_name("-home-spencer-Projects-dotfiles"), "dotfiles")
        self.assertEqual(plan.project_name("--home-spencer-homelab--"), "homelab")
        self.assertEqual(plan.project_name("-home-spencer-Projects-fieldgoal-forecasting--worktrees-feat-x"), "fieldgoal-forecasting")

    def test_use_by_bin_groups_by_hour_model_and_project(self):
        with tempfile.TemporaryDirectory() as home:
            d = Path(home, ".claude/projects/-home-u-Projects-app")
            d.mkdir(parents=True)
            msg = {"type": "assistant", "timestamp": "2026-09-01T10:05:00Z", "requestId": "r1",
                   "message": {"id": "m1", "model": "claude-opus-5", "usage": {"input_tokens": 1_000_000}}}
            (d / "s.jsonl").write_text(json.dumps(msg) + "\n")
            use = plan.use_by_bin(home)
            (hour,), = [k[0:1] for k in use]  # the 10-minute bin
            self.assertEqual(list(use.values()), [5.0])  # 1M input tokens at $5/M
            self.assertEqual(list(use)[0][1:], ("opus", "app"))
            self.assertEqual(hour % 600, 0)


class DemoTests(unittest.TestCase):
    def test_demo_data_is_plausible_and_deterministic(self):
        from defenestrator import demo
        now = 1_800_000_000
        usage, events, use = demo.generate(now, days=7)
        self.assertEqual((usage, events, use), demo.generate(now, days=7))
        self.assertGreater(len(usage), 900)
        self.assertTrue(any("kind=ping" in e for e in events))
        self.assertTrue(any(",capped=true" in u or "capped=true" in u for u in usage))
        self.assertTrue(all(float(u.split("u5=")[1].split(",")[0]) <= 100.0 for u in usage))
        self.assertTrue(use)


class CodexTests(unittest.TestCase):
    def test_weekly_only_sample_has_no_five_hour_fields(self):
        s = codex.sample_from_limits(WEEKLY_ONLY, 1_793_000_000)
        self.assertEqual(s, {"t": 1_793_000_000, "u7": 1.0, "reset7": 1793809971.0, "capped": False})

    def test_five_hour_and_weekly_windows_map_by_duration(self):
        rl = {"primary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": 2000},
              "secondary": {"usedPercent": 40, "windowDurationMins": 10080, "resetsAt": 9000}}
        s = codex.sample_from_limits(rl, 1000)
        self.assertEqual((s["u5"], s["reset5"], s["u7"], s["reset7"], s["capped"]), (100.0, 2000.0, 40.0, 9000.0, True))

    def test_the_log_snapshot_shape_works_too(self):
        rl = {"primary": {"used_percent": 46.0, "window_minutes": 10080, "resets_at": 1792328422}, "secondary": None}
        self.assertEqual(codex.sample_from_limits(rl, 5)["u7"], 46.0)

    def test_no_known_window_is_no_sample(self):
        self.assertIsNone(codex.sample_from_limits({"primary": {"usedPercent": 1, "windowDurationMins": 60, "resetsAt": 9}}, 1))
        self.assertIsNone(codex.sample_from_limits(None, 1))

    def test_history_seeded_from_logged_five_hour_snapshots(self):
        now = int(time.time())  # the log files' mtime is "now", which seed_history compares against
        with tempfile.TemporaryDirectory() as home:
            d = Path(home, ".codex/sessions/2027/01")
            d.mkdir(parents=True)
            lines = []
            for t, used in ((now - 7200, 10.0), (now - 6900, 25.0), (now - 6600, 40.0)):
                iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
                lines.append(json.dumps({"timestamp": iso, "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
                    "primary": {"used_percent": used, "window_minutes": 300, "resets_at": now + 10000}}}}))
            (d / "rollout.jsonl").write_text("\n".join(lines) + "\n")
            out = os.path.join(home, "history.codex.jsonl")
            self.assertEqual(codex.seed_history(now, out, home), 3)
            rows = [json.loads(line) for line in open(out)]
            self.assertEqual(round(sum(r["d"] for r in rows), 1), 40.0)  # 10 + 15 + 15
            self.assertIn(len(rows), (28 * 144, 28 * 144 + 1))

    def test_a_weekly_only_log_seeds_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(codex.seed_history(1_800_000_000, os.path.join(home, "h.jsonl"), home), 0)
