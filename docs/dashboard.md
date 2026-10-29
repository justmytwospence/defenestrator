# The board

There are two boards, linked to each other: `deploy/grafana/defenestrator.json` (Claude, uid `defenestrator`) and `deploy/grafana/defenestrator-codex.json` (Codex, uid `defenestrator-codex`; see [the Codex board](#the-codex-board)). The rest of this page describes the Claude board.

Both use a hidden `datasource` variable and are provisioned together. It uses
a hidden `datasource` variable, so it works with whatever InfluxDB (Flux) data source you have
connected to the data: the compose stack provisions one, and in an existing Grafana it picks the
first InfluxDB data source.

Time zones: charts follow your **browser** time zone. The hour-of-day chart and the daily bars use
the time zone set in their queries (`America/Denver` in the shipped file; change it at the top of
those queries).

## Top: right now

| Panel | What it shows |
|---|---|
| 5-hour window used | Account-wide 5-hour utilization at the last sample |
| 7-day window used | Weekly utilization at the last sample |
| 5-hour / 7-day window resets | When each window ends. A time in the past means no window is running |
| 5-hour: projected at reset | Where this window ends up at the rate of the last 90 minutes. 100 or more: you will hit the cap early. Shows "no window" when none is running |
| 7-day: projected at reset | Where the week ends up at the rate of the last 48 hours of this week |
| Last sample age | Age of the newest sample. Yellow after 25 minutes, red after an hour: the sampler is failing (see [operations](operations.md#troubleshooting)) |

## Utilization

![5-hour utilization](images/five-hour.png)

**5-hour utilization (last 2 days).** Account-wide 5-hour usage from the 10-minute samples. The
dashed line is an *even pace*: 0% at the start of the window (its reset minus five hours) rising
in a straight line to 100% at its reset. The red band is where your usage is above that line. Orange
vertical markers are windows the defenestrator started (`defenestrator_event` with kind `ping`).
It shows two days on purpose: seven days of five-hour sawteeth is unreadable.

![7-day utilization](images/seven-day.png)

**7-day utilization vs even pace.** The same idea for the week: a straight line from 0% at the
last weekly reset to 100% at the next.

## Estimated usage

![Usage by model](images/usage-by-model.png)
![Usage by project](images/usage-by-project.png)

**Estimated usage by model / by project (last 2 days).** Percent of the 5-hour budget used in
each 10 minutes, stacked, over the same range and axis width as the 5-hour chart above so the two
line up.

This is an **estimate** and only a **subset** of the account total:

- It is computed from the Claude Code and pi session logs on the machine running the defenestrator
  (mount `~/.claude`, and `~/.pi/agent/sessions` for pi). Other devices and claude.ai are not in
  those logs.
- Cost is API-equivalent (tokens times list prices), converted at 0.58% of the 5-hour budget per
  dollar. The real exchange rate depends on your plan and changes over time.
- The project is the session directory, with worktrees counted toward their project. Only the eight
  biggest projects in the range are shown.

## Rate and safety

![Fill rate](images/fill-rate.png)

**Window fill rate vs safe rate.** The orange series is how fast the 5-hour window fills, in
percentage points per hour (smoothed over 30 minutes, resets excluded). The dashed **safe rate** is
`(100 - used) / hours left`: the steady rate you could keep up from now and land on exactly 100%
at the reset. When orange is above dashed, you will hit the cap before the reset. The safe rate is
not drawn in the last hour of a window, where it shoots towards infinity.

**Average utilization by hour of day.** Mean 5-hour utilization at each local hour over the last
28 days (ignores the time range): when you usually work.

## Is it working?

![Windows per day](images/windows-per-day.png)

**Windows started per day.** A new window appears as a jump of about five hours in the reset time
between consecutive samples, however it started (a ping or your own first message). More windows
in a day is the point.

**Peak 5-hour utilization per day.** The highest utilization sampled each day. Days near 100 are
days a window ran out.

![Capped](images/capped.png)

**Hours capped per day / Capped.** Time spent rate limited, counted as 10 minutes per capped
sample, and a timeline of when.

## Decision log

![Decision log](images/decision-log.png)

Every decision, newest first, from `defenestrator_event`. Kinds: **ping** (started a window),
**would-ping** (dry run), **wait** (planned a ping for later), **no-ping** (decided not to),
**window-running**, **quiet-hours**, **skip** (not installed, not logged in, plan without a
5-hour window) and **error** (for example an expired token).

## The Codex board

![Codex board](images/codex-board.png)

Weekly-first, for the window Codex plans actually have (default range 30 days):

| Panel | What it shows |
|---|---|
| Weekly window used / resets / projected at reset / last sample age | the weekly window right now; the projection uses the last 72 hours of the week |
| Weekly utilization vs even pace | usage against a straight line from 0% to 100% across the window; red above it; orange markers are weekly windows the defenestrator started |
| Weekly fill rate vs safe rate | percentage points per day against `(100 - used) / days left`, the steady rate that lands on exactly 100% at the reset |
| Usage per day | percentage points of the weekly window used each day |
| Hours capped per day | time rate limited |
| How full each 5-hour window got | one bar per window, as tall as its peak utilization, coloured by what started it: orange the defenestrator, blue you, grey unknown (before events were logged). Shares the 7-day chart's time axis |
| 5-hour windows per 7-day window, by how full they got | windows per week (8 weeks), stacked by peak: full (90%+), mostly, partial, barely used (the ceiling is about 33 a week) |
| Decision log | Codex decisions (plus sampler errors) |
| 5-hour window (collapsed row) | for plans that have a 5-hour window: utilization against pace and windows started per day |

The usage-by-model/project panels are Claude only: Codex's logs are not priced.

## Customizing

The file is provisioned read-only (`allowUiUpdates: false`) so it stays in sync with the repo. To
change it, edit the JSON (or save a copy from the UI) and re-provision. Wait a few seconds between
edits: Grafana's database can briefly lock while it reloads provisioned dashboards.

## What started a window

Every window start gets a dashed vertical line on the 5-hour, model, project and fullness charts, and each one carries what we can actually know:

- **Orange: the defenestrator.** Its ping and why it chose that moment.
- **Blue: you.** The first message of the window found in the session logs on the machine the defenestrator runs on: the tool (pi or Claude Code), the session id, the project, the model and the machine. That is the finest level the logs give; they do not record which login or token sent a message.
- **Purple: elsewhere.** No message in this machine's logs: another machine, the Claude app or claude.ai started it. (An API token would not start a subscription window at all.)
- **Grey (on the fullness chart): unknown.** The window is from before events were logged.

The "What started each 5-hour window" table lists the same, newest first, with how full each window got. After upgrading, `defenestrator backfill` describes the windows from your history. Before the first logged event, windows the old primer started cannot be told apart from yours and stay unknown.

## Time ranges

The 7-day charts (7-day utilization, how full each window got, fill rate, capped) start at the beginning of the previous 7-day window, so they always show the previous window and the current one, and their length changes as the week goes on. Grafana cannot extend a time axis into the future from data, so the 5-hour chart ends at now.
