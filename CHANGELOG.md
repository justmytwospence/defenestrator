# Changelog

## [0.7.4]
Projections are plain numbers again; only current utilization is a gauge.

## [0.7.3]
Window starters name the session: pi's session name, else the start of the first prompt (Claude Code). Utilization and projection numbers are gauges.

## [0.7.2]
The windows-per-week chart is a stacked bar per week: each 5-hour window is a segment as tall as the share of it used, coloured to match, so a bar's height is full windows' worth used.

## [0.7.1]
Fix: pings logged in the first event format (no `kind`) are scored and counted when telling what started a window.

## [0.7.0]
What the defenestrator is worth: a day after each ping it replays the following 24 hours with and without the ping and records the estimated time capped each way (`value.jsonl`, `defenestrator_value`), charted per ping. New overlaid histograms of how full windows got (started by the defenestrator, the window right after one, others). The windows-per-week chart is a heatmap on a continuous colour scale. The 7-day charts label days by weekday.

## [0.6.1]
Fix: on a weekly-only Codex plan the defenestrator treated a weekly window at 0% used as not started and pinged every tick (0.5.0 to 0.6.0). A window is running whenever its reset is ahead, and no provider is pinged twice within an hour.

## [0.6.0]
Window starts say what started them: new `started` and `started-elsewhere` events carry the tool, session, project, model and machine of the first message (from the session logs), orange/blue/purple lines mark every start, and a table lists them. `backfill` describes past windows (run it once after upgrading).
The 7-day charts start at the beginning of the previous 7-day window. The hour-of-day chart overlays weekdays and weekends. The safe-rate line is solid.

## [0.5.3]
What started each 5-hour window is now visible: orange (defenestrator) and blue (you) lines mark every window start on the 5-hour, model and project charts. New chart "How full each 5-hour window got" (one bar per window, peak utilization, coloured by starter), and the per-week window chart is split by how full the windows were.

## [0.5.2]
Both boards are laid out so charts that share an x axis are stacked full-width with matching plot areas: the 2-day charts together, the 7-day time charts together, the per-day bars together (Claude, Codex weekly and per-day charts too).

## [0.5.1]
New Claude panel: 5-hour windows per 7-day window (last 8 weeks).

## [0.5.0]
Codex gets what it actually has: a weekly-first board of its own (`defenestrator-codex.json`,
linked from the Claude board, which no longer shows the provider switch or any Codex data) and a
policy for the weekly window. A weekly-only plan (like `prolite`) has its next weekly window started
as soon as the last one ends; plans that also have a 5-hour window still get the 5-hour policy.
The Decision log on each board shows only that provider (sampler errors on both). The demo's Codex
series is now weekly-only.

## [0.4.0]
Codex is a first-class provider. Every pass samples its rate limits (`usage.codex.jsonl`); a plan
with a 5-hour window gets the same learned policy and pings as Claude, seeded from Codex's own
session logs; a weekly-only plan is sampled and charted and never pinged. The board has a provider
selector, `demo` seeds both providers, and the 7-day chart shades red above the even-pace line.
The Codex 5-hour path is built from the documented schema and tests; it has not run against a real
5-hour Codex plan.

**Migration:** `defenestrator_usage` now has a `provider` tag. Delete the old points, then backfill:
`influx delete --predicate '_measurement="defenestrator_usage"' ...` and `defenestrator backfill`.

## [0.3.0]
New README and docs (how it works, the board panel by panel, operating it) with screenshots.
`compose.demo.yaml` and `defenestrator demo` try the board on invented data with nothing to log in
to. Board fixes found while taking the screenshots: projections show "no window" instead of an
error when no window is running, the fill-rate series are smoothed and cleanly labelled, the
hour-of-day axis shows plain hours, idle periods draw as zero in the stacked usage panels, and the
usage panels and the 5-hour chart now share axis width and legend placement so they line up.

## [0.2.1]
The usage-by-model and by-project panels are per 10 minutes (was hourly) over the last 2 days,
so they line up with the 5-hour utilization chart (same range, same axis width). `defenestrator_use`
points are now 10-minute bins: delete the old hourly ones before upgrading
(`influx delete --predicate '_measurement="defenestrator_use"'`) and run `backfill`. The Capped
timeline now colors by threshold and has a plain label.

## [0.2.0]
Board: stacked usage by model and by project (estimated from the session logs on the machine
running it, written hourly as `defenestrator_use`); the fill-rate chart gains a dashed safe-rate
line; the hour-of-day chart's x axis is labelled by hour instead of percent. `backfill` also
replays 28 days of the usage breakdown.

## [0.1.0]
First release: the scheduler and planner as a Python package, an events log of every decision,
optional InfluxDB output with `backfill`, a Docker image (`ghcr.io/justmytwospence/defenestrator`),
a Docker Compose stack with InfluxDB and Grafana, and the Grafana board.
