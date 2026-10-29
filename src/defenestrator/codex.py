"""Codex (OpenAI) support: rate-limit samples, and history seeded from its session logs.

`codex app-server` answers `account/rateLimits/read` with up to two windows, each
`{usedPercent, windowDurationMins, resetsAt}`. They are mapped by duration so Codex fits the
same sample shape as Claude: a 300-minute window is the 5-hour one (u5/reset5), a 10080-minute
window the weekly one (u7/reset7). A weekly-only plan (for example `prolite`) has no u5 at all.

Codex's session logs record the same windows (`token_count` events carry a `rate_limits`
snapshot), which is real utilization history for the policy.
"""
from __future__ import annotations

import json
import os
from glob import glob

from . import plan

FIVE_H_MINS = 300
WEEK_MINS = 10080


def window(limits, minutes):
    """The window of that duration in a rate-limits object (app-server or log shape), or None."""
    for key in ("primary", "secondary"):
        w = (limits or {}).get(key)
        if not w:
            continue
        mins = w.get("windowDurationMins", w.get("window_minutes"))
        if mins == minutes:
            return w
    return None


def _num(w, camel, snake):
    v = w.get(camel, w.get(snake))
    return float(v) if v is not None else None


def sample_from_limits(limits, now):
    """One sample from a rate-limits object, or None when it has neither window."""
    five, week = window(limits, FIVE_H_MINS), window(limits, WEEK_MINS)
    if not five and not week:
        return None
    s = {"t": int(now)}
    capped = False
    if five:
        s["u5"] = _num(five, "usedPercent", "used_percent")
        s["reset5"] = _num(five, "resetsAt", "resets_at")
        capped = capped or (s["u5"] is not None and s["u5"] >= 100 and bool(s["reset5"]) and s["reset5"] > now)
    if week:
        s["u7"] = _num(week, "usedPercent", "used_percent")
        s["reset7"] = _num(week, "resetsAt", "resets_at")
        if not five:
            capped = s["u7"] is not None and s["u7"] >= 100 and bool(s["reset7"]) and s["reset7"] > now
    s["capped"] = capped
    return s


def log_snapshots(home=plan.HOME, since=0):
    """Yield (epoch, rate_limits) for each token_count snapshot in the Codex session logs."""
    for path in sorted(glob(os.path.join(home, ".codex/sessions/**/*.jsonl"), recursive=True)):
        try:
            if os.path.getmtime(path) < since:
                continue
        except OSError:
            continue
        with open(path, errors="ignore") as fh:
            for line in fh:
                if '"rate_limits"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                rl = (o.get("payload") or {}).get("rate_limits")
                ts = plan.iso_epoch(o.get("timestamp")) if isinstance(o.get("timestamp"), str) else None
                if rl and ts is not None and ts >= since:
                    yield ts, rl


def seed_history(now, path, home=plan.HOME, days=28):
    """Write the history file for the profile from the logged 5-hour snapshots: demand per
    10-minute bin (the rise in used percent), zero where the logs show no use. Returns the
    number of snapshots used (0 writes nothing: a weekly-only plan has nothing to learn)."""
    snaps = sorted((ts, window(rl, FIVE_H_MINS)) for ts, rl in log_snapshots(home, now - days * 86400))
    snaps = [(ts, w) for ts, w in snaps if w]
    if not snaps:
        return 0
    bins = {}
    prev = None
    for ts, w in snaps:
        u, reset = _num(w, "usedPercent", "used_percent") or 0.0, _num(w, "resetsAt", "resets_at") or 0.0
        if prev and abs(prev[1] - reset) < 120:
            d = max(0.0, u - prev[0])
        elif prev and prev[1] > ts + 120:
            d = max(0.0, u - prev[0])
        else:
            d = u  # a new window started since the last snapshot
        b = int(ts // plan.BIN * plan.BIN)
        v = bins.setdefault(b, [0.0, False])
        v[0] += d
        v[1] = v[1] or u >= 100
        prev = (u, reset)
    b, capped_until = int((now - days * 86400) // plan.BIN * plan.BIN), 0
    with open(path, "w") as f:
        while b < now:
            d, capped = bins.get(b, (0.0, False))
            capped_until = b + plan.WINDOW if capped else (0 if d > 0 else capped_until)
            f.write(json.dumps({"t": b + plan.BIN / 2, "d": round(d, 3), "capped": b < capped_until}) + "\n")
            b += plan.BIN
    return len(snaps)
