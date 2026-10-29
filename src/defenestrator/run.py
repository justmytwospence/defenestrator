"""The scheduler: sample usage, decide, ping, and record every decision.

One `run_once` does what the old systemd timer did on every tick: sample account-wide usage,
then for Claude (and Codex, where the plan has a 5-hour window) start a fresh window when
the policy says so. `loop` repeats it every TICK seconds or at the next known reset or
planned ping, whichever is first. Every decision goes to events.jsonl (and InfluxDB).
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import tempfile
import time

from . import codex, plan
from .influx import Influx

FIVE_H = plan.WINDOW
BUFFER = plan.BUFFER
TICK = 600
# Kinds that repeat every tick while nothing changes; recorded when they change, not every run.
QUIET_KINDS = {"window-running", "quiet-hours", "skip", "error", "no-ping", "learning"}


class Config:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.state = plan.STATE
        self.quiet_hours = env.get("QUIET_HOURS", "")
        self.claude_model = env.get("CLAUDE_MODEL", "haiku")
        self.codex_model = env.get("CODEX_MODEL", "")
        self.seed_hosts = env.get("SEED_HOSTS", "").split()
        self.dry = env.get("DRY_RUN", "") in ("1", "true", "yes")
        self.codex = env.get("CODEX", "auto") != "off"
        self.tick = int(env.get("TICK_SECONDS", TICK))


class Cli:
    """The official CLIs. Subscription logins only: an exported API key would bill the API."""

    def __init__(self, claude_model, codex_model):
        self.claude_model, self.codex_model = claude_model, codex_model
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY")}

    def _run(self, args, timeout, input=None):
        with tempfile.TemporaryDirectory() as tmp:  # keep the CLIs' project dirs out of anywhere real
            return subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=tmp,
                                  env=self.env, input=input)

    def have(self, name):
        from shutil import which
        return which(name) is not None

    def claude_status(self):
        try:
            return json.loads(self._run(["claude", "auth", "status"], 60).stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            return {}

    def claude_ping(self):
        """Send one cheap message; returns the real five_hour reset (epoch) or None."""
        try:
            out = self._run(["claude", "-p", "hi", "--model", self.claude_model, "--max-turns", "1",
                             "--output-format", "stream-json", "--verbose"], 180).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        reset = None
        for line in out.splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") == "rate_limit_event":
                r = (((o.get("rate_limit_info") or {}).get("unifiedWindows") or {}).get("five_hour") or {}).get("resetsAt")
                if isinstance(r, (int, float)):
                    reset = int(r)
        return reset

    def codex_logged_in(self):
        try:
            r = self._run(["codex", "login", "status"], 30)
            return "ChatGPT" in (r.stdout + r.stderr)
        except (OSError, subprocess.SubprocessError):
            return False

    def codex_limits(self):
        """account/rateLimits/read over the app-server protocol, or None."""
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"clientInfo": {"name": "defenestrator", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"}]
        try:
            p = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, env=self.env)
        except OSError:
            return None
        try:
            p.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
            p.stdin.flush()
            deadline = time.time() + 15
            while time.time() < deadline:
                if not select.select([p.stdout], [], [], 1)[0]:
                    continue
                line = p.stdout.readline()
                if not line:
                    break
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("id") == 2:
                    return (o.get("result") or {}).get("rateLimits")
        except OSError:
            pass
        finally:
            p.kill()
            p.wait()
        return None

    def codex_ping(self):
        try:
            model = ["-m", self.codex_model] if self.codex_model else []
            return self._run(["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
                              *model, "hi"], 180).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


def window_300(limits):
    for w in (limits.get("primary"), limits.get("secondary")):
        if w and w.get("windowDurationMins") == 300:
            return w
    return None


class Runner:
    def __init__(self, cfg, cli=None, influx=None, log=print):
        self.cfg, self.cli = cfg, cli or Cli(cfg.claude_model, cfg.codex_model)
        self.influx = influx
        self.log = log
        self.state = cfg.state
        os.makedirs(self.state, exist_ok=True)

    # --- state ---
    def _path(self, name):
        return os.path.join(self.state, name)

    def _num(self, name, default=0):
        try:
            return float(open(self._path(name)).read().strip())
        except (OSError, ValueError):
            return default

    def _put(self, name, value):
        if not self.cfg.dry:
            with open(self._path(name), "w") as f:
                f.write(str(int(value)))

    def _rm(self, name):
        if not self.cfg.dry:
            try:
                os.remove(self._path(name))
            except OSError:
                pass

    def due(self, name, now):
        return now >= self._num(name) + BUFFER

    # --- events ---
    def event(self, now, provider, kind, reason, reset=None, force=False):
        """Append one decision to events.jsonl (and InfluxDB). Repeating states are recorded
        when they change, not on every tick."""
        last = {}
        try:
            last = json.load(open(self._path("events.last.json")))
        except (OSError, ValueError):
            pass
        key = provider
        if not force and kind in QUIET_KINDS and last.get(key, {}).get("kind") == kind and (
                kind in ("window-running", "quiet-hours") or last[key].get("reason") == reason):
            return
        e = {"t": int(now), "provider": provider, "kind": kind, "reason": reason}
        if reset is not None:
            e["reset"] = int(reset)
        with open(self._path("events.jsonl"), "a") as f:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
        last[key] = {"kind": kind, "reason": reason}
        with open(self._path("events.last.json"), "w") as f:
            json.dump(last, f)
        if self.influx:
            err = self.influx.write_events([e])
            if err:
                self.log(f"events: {err}")

    # --- one tick ---
    def run_once(self, now=None):
        now = int(now or time.time())
        self.sample(now)
        self.write_use(now)
        self.seed_once(now)
        if self.in_quiet_hours(now):
            self.log(f"quiet hours ({self.cfg.quiet_hours}), skipping")
            self.event(now, "all", "quiet-hours", f"quiet hours {self.cfg.quiet_hours}: no pings")
        else:
            self.prime_claude(now)
            if self.cfg.codex:
                self.prime_codex(now)
        with open(self._path("heartbeat"), "w") as f:
            f.write(str(now))

    def sample(self, now):
        s, src = plan.take_sample(now)
        self.log("claude: " + plan.describe_sample(s, src, now))
        if s:
            self.push_usage([s], "claude")
        else:
            self.event(now, "sampler", "error", f"no usage sample: {src}")
        self.rl = None
        if self.cfg.codex and self.cli.have("codex") and self.cli.codex_logged_in():
            self.rl = self.cli.codex_limits()
            cs = codex.sample_from_limits(self.rl, now) if self.rl else None
            if cs:
                plan.store(cs, now, self._path("usage.codex.jsonl"))
                self.log("codex: " + self.describe_codex(cs, self.rl, now))
                self.push_usage([cs], "codex")
            else:
                self.log("codex: no usage sample")
                self.event(now, "codex", "error", "could not read rate limits")

    def push_usage(self, samples, provider):
        if self.influx:
            err = self.influx.write_usage(samples, provider)
            if err:
                self.log(f"usage: {err}")

    def describe_codex(self, s, rl, now):
        parts = [f"plan {rl.get('planType') or 'unknown'}"]
        if s.get("u5") is not None:
            parts.append(f"5h {s['u5']:.0f}%")
        if s.get("u7") is not None:
            parts.append(f"7d {s['u7']:.0f}%")
        return ", ".join(parts)

    def write_use(self, now, days=1):
        """Usage per 10 minutes by model and project from the session logs on this machine, for
        the stacked panels. Starts on an hour boundary; a rewrite repeats the same timestamps."""
        if not self.influx:
            return
        since = int(now - days * 86400) // 3600 * 3600
        try:
            err = self.influx.write_use(plan.use_by_bin(since=since), plan.PCT_PER_DOLLAR)
        except Exception as e:  # logs are best effort
            err = f"usage breakdown failed ({type(e).__name__})"
        if err:
            self.log(f"use: {err}")

    def seed_codex_once(self, now):
        path = self._path("history.codex.jsonl")
        if os.path.exists(path) or self.cfg.dry or not self.cfg.codex:
            return
        try:
            if not codex.seed_history(now, path):
                open(path, "w").close()  # nothing to learn from (weekly-only plan, or no logs): do not rescan
        except Exception as e:
            self.log(f"codex seed failed ({type(e).__name__})")

    def seed_once(self, now):
        self.seed_codex_once(now)
        if os.path.exists(self._path("history.jsonl")) or self.cfg.dry:
            return
        if not self.cfg.seed_hosts and not plan.log_costs():
            return  # nothing to learn from yet: an all-zero history would teach "never any use"
        try:
            plan.seed(self.cfg.seed_hosts, now)
        except Exception as e:  # logs are best effort; the planner learns from samples anyway
            self.log(f"seed failed ({type(e).__name__})")

    def in_quiet_hours(self, now):
        import re
        m = re.match(r"^(\d+)-(\d+)$", self.cfg.quiet_hours or "")
        if not m:
            return False
        h = time.localtime(now).tm_hour
        s, e = int(m.group(1)), int(m.group(2))
        return (s <= e and s <= h < e) or (s > e and (h >= s or h < e))

    def prime_claude(self, now):
        if not self.cli.have("claude"):
            self.log("claude: not installed")
            return self.event(now, "claude", "skip", "claude CLI not installed")
        st = self.cli.claude_status()
        if st.get("loggedIn") is not True or st.get("authMethod") != "claude.ai":
            self.log("claude: no claude.ai subscription login, skipping")
            return self.event(now, "claude", "skip", "no claude.ai subscription login")
        sub = st.get("subscriptionType") or "unknown"
        samples = plan.load_samples()
        d = plan.decide(samples, now, None, plan.load_history(samples[0]["t"] if samples else now))
        r = d.get("reset")
        if isinstance(r, (int, float)):
            self._put("claude", round(r))
        if not self.due("claude", now):
            self._rm("claude.plan")  # a window started (on any device) since a ping was booked
            self.log(f"claude: {sub}: window runs until {plan.fmt(self._num('claude'))}")
            return self.event(now, "claude", "window-running",
                              f"window runs until {plan.fmt(self._num('claude'))}", self._num("claude"))
        self.act("claude", d, sub, lambda: self.cli.claude_ping(), now)

    def act(self, provider, d, sub, ping, now):
        """Carry out a wait/ping decision for a provider whose window is not running."""
        if d.get("action") == "wait":
            at = d.get("at")
            if at:
                self._put(f"{provider}.plan", int(at))
            else:
                self._rm(f"{provider}.plan")
            self.log(f"{provider}: {sub}: {d['reason']}")
            return self.event(now, provider, "no-ping" if not at else "wait", d["reason"])
        if self.cfg.dry:
            self.log(f"{provider}: {sub}: would ping ({d['reason']})")
            return self.event(now, provider, "would-ping", d["reason"], force=True)
        self._rm(f"{provider}.plan")
        reset = ping()
        if reset is None:
            reset = now + FIVE_H
        self._put(provider, reset)
        self.log(f"{provider}: {sub}: pinged ({d['reason']}), window resets {plan.fmt(reset)}")
        self.event(time.time(), provider, "ping", d["reason"], reset, force=True)

    def prime_codex(self, now):
        if not self.cli.have("codex"):
            return
        if not self.cli.codex_logged_in():
            self.log("codex: no ChatGPT login, skipping")
            return self.event(now, "codex", "skip", "no ChatGPT login")
        rl = self.rl
        if not rl:
            return  # the sample step already recorded why
        sub = rl.get("planType") or "unknown"
        five = codex.window(rl, codex.FIVE_H_MINS)
        if not five:
            self.log(f"codex: {sub}: no 5-hour window (weekly usage is sampled), nothing to start")
            return self.event(now, "codex", "skip", f"{sub}: no 5-hour window, only the weekly one is sampled")
        used = five.get("usedPercent") or 0
        reset = five.get("resetsAt") or 0
        if used != 0 and reset > now:
            self._put("codex", reset)
            self._rm("codex.plan")
            self.log(f"codex: {sub}: window runs until {plan.fmt(reset)}")
            return self.event(now, "codex", "window-running", f"window runs until {plan.fmt(reset)}", reset)
        if reset and reset <= now:
            self._put("codex", reset)
        path = self._path("usage.codex.jsonl")
        samples = plan.load_samples(path)
        d = plan.decide(samples, now, None, plan.load_history(samples[0]["t"] if samples else now,
                                                              self._path("history.codex.jsonl")))
        self.act("codex", d, sub, self.codex_ping_reset, now)

    def codex_ping_reset(self):
        """Ping Codex and return the real 5-hour reset (epoch), or None."""
        if not self.cli.codex_ping():
            return None
        win = codex.window(self.cli.codex_limits() or {}, codex.FIVE_H_MINS) or {}
        return win.get("resetsAt")

    # --- scheduling ---
    def next_wake(self, now):
        """Earliest known reset + BUFFER or planned ping, capped at one tick from now."""
        nxt = 0
        for name in ("claude", "codex", "claude.plan", "codex.plan"):
            r = self._num(name, None)
            if r is None:
                continue
            if not name.endswith(".plan"):
                r += BUFFER
            if r > now and (nxt == 0 or r < nxt):
                nxt = r
        wake = now + self.cfg.tick
        return max(now + 5, min(wake, nxt) if nxt else wake)

    def loop(self):
        while True:
            now = time.time()
            try:
                self.run_once(now)
            except Exception as e:  # one bad tick must not stop the loop
                self.log(f"run failed ({type(e).__name__}: {e})")
            wake = self.next_wake(time.time())
            self.log(f"next run {plan.fmt(wake)}")
            time.sleep(max(1, wake - time.time()))


def health(state, max_age=1500):
    """True when the loop ran recently (the container healthcheck)."""
    try:
        return time.time() - float(open(os.path.join(state, "heartbeat")).read()) < max_age
    except (OSError, ValueError):
        return False


def backfill(influx, state):
    """Replay usage.jsonl and events.jsonl into InfluxDB (same timestamps, so repeatable)."""
    usage = plan.load_samples(os.path.join(state, "usage.jsonl"))
    codex_usage = plan.load_samples(os.path.join(state, "usage.codex.jsonl"))
    events = []
    try:
        with open(os.path.join(state, "events.jsonl")) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                e.setdefault("kind", "ping")  # the first format logged pings only
                e.setdefault("reason", "")
                events.append(e)
    except OSError:
        pass
    since = int(time.time() - 28 * 86400) // 3600 * 3600
    err = (influx.write_usage(usage, "claude") or influx.write_usage(codex_usage, "codex")
           or influx.write_events(events)
           or influx.write_use(plan.use_by_bin(since=since), plan.PCT_PER_DOLLAR))
    return len(usage) + len(codex_usage), len(events), err
