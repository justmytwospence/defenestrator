# How it works

## The two limits

Claude and Codex subscriptions have two usage limits:

- A **5-hour window**. It opens with your first message after the previous window ended and
  closes five hours later. Its budget does not carry over.
- A **weekly cap**, which rolls over on its own weekly schedule.

The defenestrator only moves the 5-hour windows. It cannot make a window bigger or raise the weekly
cap, and the weekly cap is the thing a very heavy week actually runs into. What it changes is
*when* a window opens, and therefore when the next reset arrives.

## The loop

Every 10 minutes (or earlier, at the exact moment a window is due to reset) it does one pass:

1. **Sample.** It asks `GET https://api.anthropic.com/api/oauth/usage` for your account-wide
   utilization: the 5-hour percent and reset time, the 7-day percent and reset time. This is the
   endpoint Claude Code's own status line uses, with the same OAuth token, and it covers every
   device and claude.ai, not just this machine. The sample is appended to `usage.jsonl` (eight
   weeks kept) and, if InfluxDB is configured, written there.
2. **Decide** (Claude). If a window is running it does nothing and records that. If not, the
   planner (below) chooses between "ping now", "ping at some time in the next 8 hours" and "no
   ping".
3. **Ping.** `claude -p hi --model haiku --max-turns 1`, run from a throwaway directory with API
   key variables removed. The CLI reports the real reset time of the window it just started,
   which is stored so the next pass knows when to wake.
4. **Codex.** Where the plan has a 300-minute window, the same idea: read
   `account/rateLimits/read` from `codex app-server`, and run `codex exec` (cheapest model) only
   when no window is in use. Plans without a 5-hour window are re-checked every 6 hours.
5. **Record.** Every decision goes to `events.jsonl` (and InfluxDB) with a reason. A state that
   repeats, such as "window running", is recorded when it changes, not every pass.

Between passes it sleeps until the earliest of: 10 minutes, a window's reset plus two minutes,
or a planned ping.

## The policy

The question is: *given what I know about how you work, when should the next window start?*

**Demand profile.** The last 28 days of usage are cut into 10-minute bins. Days are grouped as
weekday or weekend (the matching type is used when there are at least three such days) and
weighted with a 14-day half-life, so recent habits count more. Time you spent capped counts as
typical active demand, not zero: you wanted to work then.

**Replay.** For each candidate (ping now, ping in 10 minutes, 20, … up to 8 hours, or no ping so
that your own first message starts the window), it replays every past day from the current clock
time: a window opens, fills with that day's demand, and when it is full the excess demand is
"blocked" until the next window opens five hours later. A candidate's score is the expected
blocked demand over the next 24 hours, plus a very small penalty on peak window use.

**Choice.** The lowest score wins. Scores within half a percentage point are treated as ties;
a tie goes to not pinging, and among tied ping times it takes the middle one, which is most
robust to a day starting or peaking a little early or late.

**Learning period.** With less than 7 days of data it does not trust the profile and simply
pings when a window expires.

`defenestrator report` prints the profile (per-hour demand for weekdays and weekends, capped
hours, the plan and its expected windows) so you can check that it learned something sensible.

### Where the history comes from

On first run it seeds 28 days from the Claude Code and pi session logs it can see (and any hosts
in `SEED_HOSTS`, over ssh), converting API-equivalent cost into percent of the 5-hour budget at a
fixed 0.58% per dollar (measured on a Max plan). That constant is a simplification: it only
bootstraps the profile, and real samples take over as they accumulate. If there are no logs to
read, it does not seed (an all-zero history would teach it that you never work) and runs in the
learning period instead.

## Data flow

```
   Anthropic usage API ─┐
   claude / codex CLIs ─┤        ┌── usage.jsonl   (account-wide samples)
   session logs ────────┴─►  defenestrator ─┼── events.jsonl  (every decision)
                                 │          └── history.jsonl (seeded profile)
                                 ▼
                             InfluxDB ──► Grafana board
                     (defenestrator_usage / _event / _use)
```

The files in `DEFENESTRATOR_STATE` are the source of truth; InfluxDB is a copy for the board, and
`defenestrator backfill` replays them into it.

### InfluxDB measurements

| Measurement | Tags | Fields |
|---|---|---|
| `defenestrator_usage` | `host` | `u5`, `u7` (percent), `reset5`, `reset7` (epoch seconds), `capped` |
| `defenestrator_event` | `host`, `provider`, `kind` | `reason` (string), `reset` |
| `defenestrator_use` | `host`, `model`, `project` | `cost` (API-equivalent $), `pct` (estimated % of the 5-hour budget), one point per 10 minutes |

Event kinds: `ping`, `would-ping` (dry run), `wait`, `no-ping`, `window-running`, `quiet-hours`,
`skip`, `error`.

## What it will never do

- Use an API key, or bill anything to the API.
- Send more than one short message to start a window, or ping while a window is running.
- Ping during `QUIET_HOURS`.
- Write your token anywhere other than the file the CLI already keeps it in.

## Limits

- The usage endpoint is not a documented API.
- The policy assumes your future looks like your recent past. A big change in schedule takes a
  few days to be learned (the half-life is 14 days, so recent days count more).
- It optimizes blocked demand, which it estimates from usage, not what you wanted to do while
  capped.
