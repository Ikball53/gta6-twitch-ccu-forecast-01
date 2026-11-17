[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch viewers forecast

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each hour of its release day, 2026-11-19 (UTC), from everything recorded up to the end of the first hour, as five quantiles per hour.

## Method

The previous entry fixed the median with a regression on log hour-1 plus a rolling-unlock flag, blended with a similarity-weighted median of past launches' day shapes. This entry keeps that shape and fixes the calibration around it: the tier down-weighting of early-access and weak launches is gone (it cost accuracy on every cut in leave-one-out testing), the similarity and regression widths are both 1.25, and the blend puts 65% on the regression leg. The spread still comes from the regression's residual spread, so the intervals stay honest instead of padded.

## Run

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Pure Python standard library, deterministic, no network.
