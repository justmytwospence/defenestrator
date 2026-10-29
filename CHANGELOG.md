# Changelog

## [0.2.0]
Board: stacked usage by model and by project (estimated from the session logs on the machine
running it, written hourly as `defenestrator_use`); the fill-rate chart gains a dashed safe-rate
line; the hour-of-day chart's x axis is labelled by hour instead of percent. `backfill` also
replays 28 days of the usage breakdown.

## [0.1.0]
First release: the scheduler and planner as a Python package, an events log of every decision,
optional InfluxDB output with `backfill`, a Docker image (`ghcr.io/justmytwospence/defenestrator`),
a Docker Compose stack with InfluxDB and Grafana, and the Grafana board.
