"""Synthetic data for trying the board (and for the README screenshots) without a login.

`defenestrator demo` writes two weeks of plausible usage ending now into InfluxDB: 10-minute
usage samples, the decisions the defenestrator would have made, and a model/project breakdown.
It simulates a working pattern (focused mornings and afternoons, lighter evenings and weekends)
against a 5-hour window that fills as you work, pings that start windows at expiry on workdays,
and a weekly window. Deterministic for a given seed; everything is invented.
"""
from __future__ import annotations

import random
import time

from . import plan
from .influx import event_line, usage_line, use_line

PROJECTS = [("api-gateway", 0.30), ("web-app", 0.24), ("data-pipeline", 0.18), ("infra", 0.12),
            ("docs-site", 0.08), ("experiments", 0.08)]
MODELS = [("opus", 0.64), ("sonnet", 0.30), ("haiku", 0.06)]
WEEK = 7 * 86400
BIN = plan.BIN


def _pick(rnd, options):
    x, acc = rnd.random(), 0.0
    for name, w in options:
        acc += w
        if x < acc:
            return name
    return options[-1][0]


def _rate(t, rnd, focus):
    """Demand in percent of the 5-hour budget per 10 minutes at time t."""
    lt = time.localtime(t)
    h = lt.tm_hour + lt.tm_min / 60
    weekend = lt.tm_wday >= 5
    if weekend:
        base = 1.5 if 10 <= h < 16 else 0.0
    elif 9 <= h < 12.5 or 13.5 <= h < 18:
        base = 5.5
    elif 19.5 <= h < 22:
        base = 1.8
    else:
        base = 0.0
    if base == 0.0 or rnd.random() < 0.18:  # thinking, meetings, lunch
        return 0.0
    return max(0.0, rnd.gauss(base * focus, base * 0.55))


def generate(now=None, days=14, seed=7, host="demo"):
    """Return (usage lines, event lines, use lines) as InfluxDB line protocol."""
    now = int(now or time.time())
    rnd = random.Random(seed)
    start = (now - days * 86400) // BIN * BIN
    usage, events, use = [], [], []
    reset5 = None  # end of the running 5-hour window
    used5 = 0.0
    used7 = 0.0
    reset7 = start + WEEK - (start % WEEK) + 4 * 86400 + 7 * 3600  # a weekly boundary
    announced = False
    day_focus = {}
    t = start
    erred = False

    def ev(at, provider, kind, reason, reset=None):
        events.append(event_line({"t": at, "provider": provider, "kind": kind, "reason": reason, "reset": reset}, host))

    while t <= now:
        lt = time.localtime(t)
        focus = day_focus.setdefault((lt.tm_yday, lt.tm_year), rnd.choice([0.55, 0.8, 1.0, 1.0, 1.25, 1.5]))
        if t >= reset7:
            used7, reset7 = 0.0, reset7 + WEEK
        if reset5 is not None and t >= reset5:
            reset5, used5, announced = None, 0.0, False
        demand = _rate(t, rnd, focus)
        weekday = lt.tm_wday < 5
        # The defenestrator pings when a window has expired, on workdays, before 18:00.
        if reset5 is None and weekday and 7 <= lt.tm_hour < 18 and (lt.tm_hour, lt.tm_min // 10) >= (7, 4):
            reset5 = t + plan.WINDOW
            ev(t, "claude", "ping", "ping at expiry: expected blocked 3% vs 11% if later", reset5)
        elif reset5 is None and demand > 0:
            reset5 = t + plan.WINDOW  # your own first message starts it
        if reset5 is not None and not announced:
            ev(t, "claude", "window-running", f"window runs until {plan.fmt(reset5)}", reset5)
            announced = True
        capped = used5 >= 100.0
        if reset5 is not None and demand > 0 and not capped:
            take = min(demand, 100.0 - used5)
            used5 += take
            used7 += take * 0.07
            capped = used5 >= 100.0
            share = take / plan.PCT_PER_DOLLAR
            for model, project in {(_pick(rnd, MODELS), _pick(rnd, PROJECTS)) for _ in range(2)}:
                use.append(use_line(t, model, project, share / 2, plan.PCT_PER_DOLLAR, host))
        sample = {"t": t, "u5": round(used5, 1), "u7": round(min(used7, 100.0), 1), "reset7": float(reset7),
                  "capped": capped and reset5 is not None}
        if reset5 is not None:
            sample["reset5"] = float(reset5)
        usage.append(usage_line(sample, host))
        if not weekday and reset5 is None and lt.tm_hour == 8 and lt.tm_min < 10:
            ev(t, "claude", "no-ping", "no ping helps (expected blocked 2% either way)")
        if not erred and t > now - 9 * 86400 and lt.tm_hour == 3:
            ev(t, "sampler", "error", "no usage sample: access token expired (refreshed on next claude use)")
            erred = True
        t += BIN
    return usage, events, use


def run(influx, now=None, days=14):
    usage, events, use = generate(now, days, host=influx.host)
    err = influx.write(usage) or influx.write(events) or influx.write(use)
    return len(usage), len(events), len(use), err
