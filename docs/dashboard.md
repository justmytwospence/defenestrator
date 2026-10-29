# The board

`deploy/grafana/defenestrator.json` is a single Grafana dashboard (uid `defenestrator`). It uses
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

## Customizing

The file is provisioned read-only (`allowUiUpdates: false`) so it stays in sync with the repo. To
change it, edit the JSON (or save a copy from the UI) and re-provision. Wait a few seconds between
edits: Grafana's database can briefly lock while it reloads provisioned dashboards.
