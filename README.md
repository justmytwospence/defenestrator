# Defenestrator

**Your Claude and Codex 5-hour limits reset on a schedule you never chose. Defenestrator makes
them reset when you need them to.**

<p align="center">
  <img src="docs/images/dashboard.png" alt="The Defenestrator Grafana board: account-wide 5-hour and 7-day utilization, projections, usage by model and project, windows started per day, hours capped and a decision log" width="900">
</p>
<p align="center"><sub>The board, running on invented demo data (<code>docker compose -f compose.demo.yaml up</code>).</sub></p>

## The problem

Claude and Codex subscriptions meter you in **5-hour windows**. A window opens with your first
message and closes five hours later. Spend the window's budget early and you wait for the reset,
however much you still have to do.

Whoever is first at your desk decides when the windows fall. Start at 9:00 and a heavy morning
caps out at 11:30 with the reset at 14:00: two and a half hours of nothing, in the middle of
your best working time.

## What Defenestrator does

It throws a spent window out and starts a fresh one **at the moment that helps you most**, by
sending one tiny message (`claude -p hi --model haiku`) with the official CLI before you sit down.

```
Without it    window 1: 09:00 ─────────────────────── 14:00   window 2: 14:00 ──── …
              you cap out at 11:30  ░░░░░ stuck until 14:00 ░░░░░

With it       window 1: 07:40 ───────────── 12:40   window 2: 12:42 ───────────── 17:42   window 3: 17:44 ─ …
              you cap out at 11:30  ░ stuck until 12:40 ░    a fresh budget at lunch    one more for the evening
```

Same plan, same weekly cap, but the resets now land in the middle of your day instead of after
it. On a heavy day that is the difference between two windows and three.

It learns **when** to do this. A ping that starts a window at the wrong hour wastes the budget,
so it replays your last 28 days of real usage against each candidate ping time and picks the one
with the least expected blocked work. Some days the right answer is "do nothing, your own first
message will start it".

## Why you'd want to run it

- **Fewer dead hours.** Heavy days get split across as many fresh windows as possible.
- **It tunes itself.** The policy comes from your own usage history (seeded from your Claude Code and
  pi session logs, then from account-wide samples every 10 minutes), not a fixed schedule.
- **You can see everything.** A ready-made Grafana board shows how fast you are burning each
  window, whether you are on course to hit a cap, which model and project is eating the budget,
  and a log of every decision it made and why. Codex has its own board.
- **It is boring to run.** One container, official CLIs only, no API keys, no scraping. A ping
  costs a one-word message to the smallest model.
- **Claude and Codex.** Each provider is sampled, and gets the windows it really has
  managed (5-hour for Claude, weekly for Codex), with its own board. See [Claude and Codex](#claude-and-codex).

## Try it in 60 seconds, with nothing to log in to

```sh
git clone https://github.com/justmytwospence/defenestrator && cd defenestrator
docker compose -f compose.demo.yaml up --build
```

Open <http://localhost:3000/d/defenestrator>. It seeds two weeks of invented usage into a
throwaway InfluxDB and shows the real board. It never touches your logins and sends no pings.

## Run it for real

You need Docker, and `claude` logged in on the host with a claude.ai subscription (not an API
key). Codex is optional (a ChatGPT login; see [Claude and Codex](#claude-and-codex) for what each plan gets).

```sh
cp .env.example .env     # three secrets, your TZ, and your uid/gid (see the comments in it)
docker compose up -d --build
```

Start with `DRY_RUN=1` in `.env` if you want to watch its decisions in the board's **Decision
log** for a day before it sends anything. Then remove it and `docker compose up -d`.

The container mounts `~/.claude` and `~/.codex` read-write so the CLIs can refresh their own
tokens, and uses the logins you already have. Prefer a separate login? See
[docs/operations.md](docs/operations.md#a-separate-login). Published images
(`ghcr.io/justmytwospence/defenestrator`, amd64 and arm64) are listed in
[docs/operations.md](docs/operations.md#using-the-published-image). Not using Docker? It is
standard-library Python: [run it from cron or systemd](docs/operations.md#without-docker).

## A tour of the board

Everything below is the demo data. The board lives in
[`deploy/grafana/defenestrator.json`](deploy/grafana/defenestrator.json) and every panel is
explained in [docs/dashboard.md](docs/dashboard.md).

### Are you burning the window too fast?

<img src="docs/images/five-hour.png" alt="5-hour utilization with a dashed even-pace line, red where usage is above it, and lines where windows started" width="900">

Account-wide 5-hour usage (every device, claude.ai included). The dashed line is an even pace
from 0% at the start of the window to 100% at its reset; the red band is where you are ahead of
it. Dashed lines mark every window start, coloured by what started it: orange the defenestrator,
blue you (with the session, project and model), purple another machine or claude.ai.

### Will you hit the weekly cap?

<img src="docs/images/seven-day.png" alt="7-day utilization against an even-pace line" width="900">

Weekly usage against a straight line to the next reset, over the previous and current week, plus a projection of where the week ends
up at your current rate ("7-day: projected at reset" on the board).

### What is eating the budget?

<img src="docs/images/usage-by-model.png" alt="Stacked area chart of estimated usage by model" width="900">
<img src="docs/images/usage-by-project.png" alt="Stacked area chart of estimated usage by project" width="900">

Estimated usage every 10 minutes, stacked by model and by project (the biggest eight), read from
your Claude Code and pi session logs. These line up with the 5-hour chart above, so you can see
which project filled which window.

### How fast, and is it safe?

<img src="docs/images/fill-rate.png" alt="Window fill rate against the safe rate" width="900">

The rate you are filling the window, against the **safe rate**: the steady pace that would land
you on exactly 100% at the reset. Above the grey line, you are going to hit the cap early.

### What started each window?

<img src="docs/images/started-by.png" alt="Table of 5-hour windows with who started each, the session detail and how full it got" width="900">

Every window with what started it: the defenestrator's ping, or your first message (pi's session
name or your first prompt, the project, the model and the machine), or something outside this
machine's logs.

### Is it earning its keep?

<img src="docs/images/value.png" alt="Estimated minutes capped in the 24 hours after each ping, with and without it" width="900">

A day after each ping, the 24 hours that followed are replayed with and without it: the estimated
time capped each way. The legend totals the difference.

<img src="docs/images/per-week.png" alt="Stacked bars per week, one segment per 5-hour window sized and coloured by how full it got" width="440"> <img src="docs/images/histogram.png" alt="Overlaid histograms of how full windows got, by who started them" width="440">

How many windows each week held and how full each got, and how full the defenestrator's windows
(and the ones right after them) got compared with the rest.

### Why did it do that?

<img src="docs/images/decision-log.png" alt="Decision log table" width="900">

Every ping, wait, skip and error with its reason, newest first. Nothing it does is a black box.

## Claude and Codex

Each provider gets a board and a policy for the windows it actually has.

| | Claude (Anthropic) | Codex (OpenAI) |
|---|---|---|
| Windows | 5-hour, plus weekly | weekly on most plans (e.g. `prolite`); 5-hour as well on plans that have one |
| Samples every 10 minutes | account-wide, from the usage endpoint | from `codex app-server` (`account/rateLimits/read`) |
| What it starts | a fresh 5-hour window, timed by the learned policy | the next **weekly** window as soon as the last one ends (a 5-hour window too, on plans that have one, with the same policy as Claude) |
| History seeded from | Claude Code and pi session logs | Codex session logs (they record the real windows) |
| Board | [Defenestrator](docs/dashboard.md) | [Defenestrator: Codex](docs/dashboard.md#the-codex-board), weekly-first |
| Usage by model and project | yes | not yet (Codex's logs are not priced) |

<img src="docs/images/codex-board.png" alt="The Codex board: weekly utilization against an even pace, weekly fill rate, usage per day, hours capped and a decision log" width="900">

**Why start a weekly window early?** A weekly window opens with your first message after the last
one ended, so the idle gap between a reset and your first message is time the next reset is pushed
back. Starting the next window at the reset closes that gap. It changes nothing in a week you
don't hit the cap, and in a week you do, the reset you are waiting for arrives sooner by the
length of the gap. It never makes a window bigger.

**What has been verified.** Codex weekly sampling and the board run live against a real `prolite`
account. The weekly ping (and the 5-hour path for Codex plans that have one) is covered by tests
built from Codex's rate-limit schema; neither has fired for real yet (the weekly one will at the
next reset). `DRY_RUN=1` shows exactly what it would do in the Decision log.

## How it decides

Every 10 minutes it samples your account-wide usage. When no window is running, it replays each
of your last 28 days (same weekday type when there are enough, recent days weighted more) from
the current time for "ping now", "ping in 10 minutes … 8 hours" and "no ping", and picks the
lowest expected blocked demand over the next 24 hours. Ties go to not pinging. For its first
week it simply pings when a window expires while it learns. The full model, with its constants
and its limits, is in [docs/how-it-works.md](docs/how-it-works.md).

## Configuration

| Variable | Meaning |
|---|---|
| `DRY_RUN=1` | Log decisions only, send nothing |
| `QUIET_HOURS=1-7` | Local hours with no pings (sampling continues) |
| `CLAUDE_MODEL` | Model for the ping, default `haiku` |
| `CODEX=off` | Skip Codex (no sampling, no pings) |
| `CODEX_MODEL` | Model for the Codex ping (default: Codex's own) |
| `TICK_SECONDS` | Longest wait between runs, default 600 |
| `SEED_HOSTS` | ssh hosts whose session logs also seed the profile |
| `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_HOST_TAG` | InfluxDB output (optional) |
| `DEFENESTRATOR_STATE` | State directory (`/state` in the image) |

## FAQ

**Does it give me more usage?** No. Your weekly cap is unchanged and a window is never larger.
It changes **when** the 5-hour windows fall, so a heavy stretch of work spans more of them.

**What does a ping cost?** One word to the smallest model, against a window budget that real work
fills in a few hours. It is lost in the noise, and it only fires when it expects to gain.

**Is this allowed?** It uses the official CLIs, with your own subscription login, sending one
short message at a time, the same thing you could do by hand. Providers' terms change, so read
yours; you are responsible for how you use your account.

**Does it use an API key?** Never. Subscription logins only, and `ANTHROPIC_API_KEY` and friends
are removed from the CLIs' environment so nothing can be billed to the API by accident.

**What does it do with my credentials?** The OAuth token is read from `~/.claude/.credentials.json`
to ask the usage endpoint how full your window is, and is never printed, logged or written
anywhere else. The scheduler itself only talks to Anthropic (and OpenAI, for Codex) through their own CLIs and endpoints, and to your own InfluxDB.

**Do I need Grafana and InfluxDB?** No. They are only for the board. The scheduler works from its
own files; set no `INFLUX_*` variables and it runs standalone.

**What if I also use Claude on my phone or another machine?** That is the point of sampling
account-wide usage: a window you started elsewhere is seen and respected.

## Caveats

- The usage endpoint is the one Claude Code's own status line calls. It is not a documented API
  and may change; the sampler degrades to "no sample" rather than guessing.
- Credentials are shared with the host's CLIs. If you run Claude Code on the host while the
  container runs, both may refresh the same token file. This has been fine; it is the one place
  to look if a login ever drops.
- The usage-by-model/project panels are an estimate from the session logs on the machine running
  the defenestrator (see [docs/dashboard.md](docs/dashboard.md#estimated-usage)).
- The learned policy is a heuristic. `defenestrator report` shows its reasoning.

## More

- [docs/how-it-works.md](docs/how-it-works.md): the windows, the policy, the data flow and the files
- [docs/dashboard.md](docs/dashboard.md): every panel, and how its numbers are made
- [docs/operations.md](docs/operations.md): install variants, upgrades, troubleshooting

## Develop

```sh
python3 -B -m unittest discover -s tests      # standard library only
```

CLI versions in the image are build args in the [`Dockerfile`](Dockerfile). Releases are tags
(`vX.Y.Z`) that publish the image; the changelog is in [CHANGELOG.md](CHANGELOG.md).

MIT licensed.
