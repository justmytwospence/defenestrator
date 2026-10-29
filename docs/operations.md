# Operating it

## Using the published image

Tagged releases are published to `ghcr.io/justmytwospence/defenestrator` for linux/amd64 and
linux/arm64 (tags `X.Y.Z`, `X.Y`, `X`). The image runs as uid/gid 1000 so that it can write the
mounted `~/.claude` and `~/.codex`. In `compose.yaml`, replace the `build:` block with
`image: ghcr.io/justmytwospence/defenestrator:<version>`. If your user id is not 1000, build the
image yourself (`HOST_UID` and `HOST_GID` in `.env`), or the mounted token files will not be
writable.

If the repository is private you need a `docker login ghcr.io` with a token that can read packages.

## A separate login

By default the container reuses the CLIs' logins on your machine. To keep them separate, point
`CLAUDE_DIR` and `CODEX_DIR` in `.env` at empty folders, then log in once inside the container:

```sh
docker compose run --rm defenestrator claude          # then /login
docker compose run --rm defenestrator codex login --device-auth
```

It needs a **claude.ai subscription login**. An API-key login is detected and skipped.

## What to mount

| Mount | Why | Mode |
|---|---|---|
| `./state:/state` | samples, events, learned history | rw |
| `~/.claude:/home/app/.claude` | the login, and Claude Code's session logs (for the model/project panels and seeding) | rw (tokens refresh) |
| `~/.codex:/home/app/.codex` | the Codex login | rw |
| `~/.pi/agent/sessions:/home/app/.pi/agent/sessions` | pi's session logs, if you use pi | ro |

## Without Docker

It is standard-library Python 3.9+, plus the `claude` (and optionally `codex`) CLI on `PATH`.

```sh
pip install .                       # or: PYTHONPATH=src python3 -m defenestrator
export DEFENESTRATOR_STATE=$HOME/.local/state/defenestrator
defenestrator once --dry-run        # one pass, logs only
defenestrator run                   # or run it as a daemon
```

To run it from systemd instead of as a daemon, a user timer every 10 minutes is enough
(`once` does one pass, and an expired window is picked up on the next one):

```ini
# ~/.config/systemd/user/defenestrator.service
[Service]
Type=oneshot
Environment=DEFENESTRATOR_STATE=%h/.local/state/defenestrator
ExecStart=%h/.local/bin/defenestrator once

# ~/.config/systemd/user/defenestrator.timer
[Timer]
OnBootSec=2min
OnCalendar=*:0/10
[Install]
WantedBy=timers.target
```

Then `systemctl --user enable --now defenestrator.timer`. (`run` wakes at the exact reset, `once`
on the timer tick can be up to 10 minutes after it.)

## Commands

| Command | |
|---|---|
| `defenestrator run` | The loop; what the container runs. `--dry-run` logs only |
| `defenestrator once` | One pass |
| `defenestrator report` | The learned profile, capped hours, and the current plan |
| `defenestrator decide` | The Claude decision as JSON |
| `defenestrator sample` | Record one usage sample |
| `defenestrator seed [host…]` | Rebuild `history.jsonl` from session logs (and ssh hosts) |
| `defenestrator backfill` | Replay `usage.jsonl`, `events.jsonl` and 28 days of the usage breakdown into InfluxDB |
| `defenestrator demo` | Write two weeks of invented data into InfluxDB |
| `defenestrator health` | Exit 0 if the loop ran in the last 25 minutes (the container health check) |

In Docker: `docker compose exec defenestrator python3 -m defenestrator report`.

## State

Everything is in `DEFENESTRATOR_STATE` (`./state` in the compose stack):

| File | |
|---|---|
| `usage.jsonl` | account-wide samples, 8 weeks kept |
| `events.jsonl` | every decision (append-only) |
| `history.jsonl` | seeded history from before sampling began; delete it to reseed |
| `claude`, `codex`, `claude.plan`, `codex.nowindow` | next reset / planned ping / re-check times |
| `heartbeat` | last completed pass (health check) |

The board's data is a copy; losing InfluxDB loses nothing you cannot replay with `backfill`.

## Upgrading

```sh
git pull && docker compose up -d --build        # or bump the image tag
docker compose exec defenestrator python3 -m defenestrator backfill     # if the release says so
```

Read [CHANGELOG.md](../CHANGELOG.md): releases that change a measurement say how to migrate.

## Troubleshooting

**"Last sample age" is red, or the log says `no usage sample`.**
`docker compose logs defenestrator`. The reason is in the line and in the Decision log:
- `access token expired`: the token is refreshed only by the `claude` CLI. The sampler asks it to
  with `claude auth status` first; if that does not help, the next ping or any Claude Code use will.
- `no credentials` / `no access token`: `~/.claude/.credentials.json` is not mounted or not
  readable by uid 1000.
- `usage request failed`: network, or Anthropic's endpoint changed.

**It never pings.** That can be right: `defenestrator report` shows the plan. While a window is
running it waits, and for the first 7 days it only pings at expiry. Check `QUIET_HOURS` and
`DRY_RUN`, and the Decision log.

**`no claude.ai subscription login, skipping`.** `docker compose run --rm defenestrator claude auth
status` should show `"authMethod": "claude.ai"`.

**A login keeps dropping.** The host's CLIs and the container share the same token file. If you
run Claude Code on the host constantly, prefer a [separate login](#a-separate-login) for the
container.

**Grafana says "database is locked" while provisioning.** Grafana's SQLite briefly locks on
startup and when you rewrite a provisioned dashboard repeatedly. It clears on its own; if
provisioning stays stuck after several minutes, restart the Grafana container.

**The charts are empty.** `docker compose exec defenestrator python3 -m defenestrator backfill`,
and check the InfluxDB variables in `.env`. The board needs the `defenestrator_usage` measurement.

## Uninstalling

`docker compose down -v` (add `-v` to also drop the InfluxDB and Grafana volumes). Delete `./state`
to forget what it learned. It leaves no changes in `~/.claude` or `~/.codex`.
