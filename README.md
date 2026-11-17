[![make.fun bounty](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![make.fun rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![make.fun reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch forecast

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day (2026-11-19 UTC), hours 2 to 24, as five quantiles
per hour — from the first hour's viewer count alone.

## How it works

The first hour's count is the anchor. Thirty-seven past blockbuster launches
each lend the shape of their own day, written as the log of each later hour
divided by that launch's first hour. A launch whose first hour looked like
ours counts more (a Gaussian weight on the log gap), and a launch that
resembles GTA VI's profile — console-only, single-player, no early-access
mess — counts more again. For every hour we read off the weighted 5/25/50/
75/95 percentiles of those shapes, nudge them when our first hour sits above
every launch on record (a log-linear tilt fitted on the big launches only,
so the forecast keeps growing with the anchor instead of falling back to an
average shape), smooth the result across neighbouring hours, and then tighten
the band toward the median so the 90% band really covers about nine hours in
ten. Standard library only, deterministic, no network.

## Run it

```sh
python3 main.py
```

Reads every `*.in` case from `$MAKEFUN_INPUT_DIR` (or `/input`) and writes
one `*.out` forecast per case to `$MAKEFUN_OUTPUT_DIR` (or `/output`).

## Local validation

See `VALIDATION.md`. Leave-one-out over the 37 launch curves in the kit:
mean pinball loss 0.4207 (house baseline 0.9296), 30/37 cases beaten,
90% coverage 0.832 overall and 0.866 on big launches.
