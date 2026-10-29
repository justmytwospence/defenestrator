# Changelog

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
