[![Bounty](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/bounty.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch viewers forecast

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each hour of its release day, 2026-11-19 (UTC), from everything recorded up to the end of the first hour, as five quantiles per hour.

## Method

The earlier entries missed the median by about 44% on the practice set, and shrinking the intervals changed nothing, so this entry attacks the median itself. Two facts about the comparable launches drive it:

1. A launch's day shape depends strongly on its hour-1 size: small launches explode 100x later in the day while big launches stay near their hour-1 level (late-hour log-ratio vs log hour-1 slope about -0.9). A single median ratio is far too high for a big anchor like GTA VI.
2. Launches that unlock at rolling local midnight have a different day shape from simultaneous-global launches. GTA VI unlocks at rolling local midnight.

Each hour's forecast blends two legs: a similarity-weighted median of the comparables' log-ratios to hour 1, and a per-hour weighted regression of the log-ratio on log hour-1 plus a rolling-unlock indicator. The median is the geometric mean of the two legs; the spread is the regression's residual spread.

## Run

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Pure Python standard library, deterministic, no network.
