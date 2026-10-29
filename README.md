# Defenestrator

Claude (and Codex) subscriptions meter usage in 5-hour windows that start with your first
message. The defenestrator throws a spent window out and starts a fresh one at the moment that
helps you most, so a heavy day is split across as many windows as possible. A window it starts
costs one tiny message (`claude -p hi --model haiku`). Weekly caps are unaffected.

It also records your account-wide usage every 10 minutes and ships a Grafana board.

## What you get

- **Policy.** When no window is running it replays your last 28 days of usage from the current
  time for "ping now", "ping in 10 minutes ... 8 hours" and "no ping" (your own use starts the
  window), and picks the lowest expected blocked demand over the next 24 hours. Until it has 7
  days of data it simply pings when a window expires.
- **Account-wide usage.** The 5-hour and 7-day utilization of the whole account (every device,
  claude.ai included), from the same endpoint Claude Code's status line uses.
- **A decision log.** Every ping, wait, skip and error, with its reason.
- **A Grafana board** (`deploy/grafana/defenestrator.json`): 5-hour and 7-day utilization against
  an even pace, projections at reset, window fill rate, an hour-of-day profile, windows started and
  peak utilization per day, hours capped, estimated usage stacked by model and by project (from the
  Claude Code and pi session logs it can see, so mount `~/.pi/agent/sessions` for pi), ping markers and
  the decision log.

Official CLIs only, with your subscription logins: API keys in the environment are ignored so
nothing is ever billed to the API.

## Run it

You need Docker and a logged-in `claude` (a claude.ai subscription, not an API key) on the host.
Codex is optional (ChatGPT login, on a plan that has a 5-hour window).

```sh
cp .env.example .env        # set the three secrets, TZ, HOST_UID/HOST_GID
docker compose up -d --build
```

Tagged releases are published as `ghcr.io/justmytwospence/defenestrator:<version>` (linux/amd64
and arm64, user id 1000). To use the image instead of building, replace `build:` with `image:`
in `compose.yaml`; if your user id is not 1000, build it yourself so the mounted logins stay writable.

The container mounts `~/.claude` and `~/.codex` read-write, so it uses the
logins you already have and the CLIs can refresh their tokens. To use a separate login instead,
point `CLAUDE_DIR` and `CODEX_DIR` at empty folders and run
`docker compose run --rm defenestrator claude` once (`/login`) and
`docker compose run --rm defenestrator codex login --device-auth`.

Open `http://localhost:3000/d/defenestrator` (user `admin`, your `GRAFANA_PASSWORD`).
Try it first with `DRY_RUN=1` in `.env`: it logs what it would do and sends nothing.

Seeding: with session logs mounted it learns from your recent history on the first run. The
`SEED_HOSTS` option adds other machines over ssh (their session logs).

## Configuration

| Variable | Meaning |
|---|---|
| `QUIET_HOURS=1-7` | Local hours with no pings (sampling continues) |
| `CLAUDE_MODEL` | Model for the ping, default `haiku` |
| `CODEX=off` | Skip Codex |
| `CODEX_MODEL` | Model for the Codex ping (default: Codex's own) |
| `DRY_RUN=1` | Log decisions only |
| `TICK_SECONDS` | Longest wait between runs, default 600 |
| `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_HOST_TAG` | Optional InfluxDB output |
| `DEFENESTRATOR_STATE` | State directory (`/state` in the image) |

State lives in `./state`: `usage.jsonl` (samples, 8 weeks kept), `events.jsonl` (decisions),
`history.jsonl` (seeded history) and a few small files. These are the source of truth; InfluxDB
is only for the board, and `defenestrator backfill` replays them into it.

## Use it without the stack

It is stdlib Python. Install it, set `DEFENESTRATOR_STATE`, and run `defenestrator once` from any
scheduler (cron, a systemd timer) every 10 minutes, or `defenestrator run` as a daemon.
`defenestrator report` shows what it has learned and what it plans.

## Caveats

- Credentials are mounted from the host. If you run Claude Code on the host while the container
  runs, both may refresh the same token file; they share it, which has worked, but it is the
  one thing to watch if a login ever drops.
- The usage endpoint is the one Claude Code uses; it is not a documented API and may change.
- The learned policy is a heuristic. `defenestrator report` shows its reasoning.

## Develop

```sh
python3 -B -m unittest discover -s tests
```

Pinned CLI versions are build args in the `Dockerfile`.
