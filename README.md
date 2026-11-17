# GTA VI launch-day Twitch viewers — forecast entry (v1)

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ikball53/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts Grand Theft Auto VI's Twitch concurrent viewers for hours 2–24
of release day 2026-11-19 (UTC), five quantiles each, from hour 1's print
plus the 42 comparable past game launches shipped in each case.

## Approach

1. **Anchor on hour 1.** Every forecast is hour 1's print multiplied by a
   ratio. The level comes from the case itself, never from a guessed
   absolute audience size.
2. **Comparable launch curves.** For each past launch, take the log-ratio
   of each later hour to that launch's own hour 1. This removes the huge
   scale differences between launches (hour-1 prints in the data run from
   ~150 to ~875,000) and leaves the intraday *shape*.
3. **Hour-1-similarity weighting.** Launches are weighted by how close
   their hour-1 print is to ours (Gaussian in log space, sigma = 1.0).
   This is the key step: launches whose hour 1 was already unlocked
   (rolling midnight, big hour-1 print) stay within roughly 0.3–3× of
   hour 1 all day, while simultaneous-global launches with a tiny hour-1
   print explode 100–2000× later. An unweighted average would mix the two
   regimes and produce absurd upper quantiles. GTA VI unlocks at midnight
   local time, so hour 1 (00:00–01:00 UTC) already holds the UK, New
   Zealand, Australian and Asian audiences — the big-hour-1 regime is the
   relevant one, and the weighting finds it automatically from the print.
4. **Tier weighting.** Console-only single-player AAA launches count
   1.5×; early-access-contaminated launches 0.5×; free-to-play and
   multiplayer-heavy launches 0.5–0.7×. The GTA VI category's own
   pre-release history (a comparable with no launch day) is excluded from
   the curves; its pre-release level is orders of magnitude below launch
   level and adds no signal once hour 1 is known.
5. **Weighted quantiles + light smoothing.** Per hour, the weighted
   empirical quantiles of the log-ratios at 0.05/0.25/0.5/0.75/0.95, then
   a 3-hour moving average of the log-quantiles so the curve cannot jitter
   hour to hour. If the anchor is so extreme that almost no launch
   resembles it (effective sample size under 2), the forecast blends back
   toward the plain tier-weighted quantiles. A degenerate fallback (flat
   median, widening spread) covers a case with no usable comparables.
6. **Honest spread.** Quantiles are the quantiles the model believes —
   pinball loss is a proper scoring rule, so narrowing them to look
   confident would only pay off if the model were actually that sure.

The typical shape the model produces for a large hour-1 print: a dip to
~0.7× in hours 2–10 (overnight in Europe, before the US unlocks), then a
rise to ~1.5–1.7× in hours 19–23 as the US evening peak arrives — the
rolling-midnight signature visible across the comparable launches.

## Local validation (not a server grade)

There is no server practice grade for this competition, so validation was
done locally with *pseudo-practice* cases: each of the 37 comparable
launches with a full release day was turned into a case (its own hour 1 as
`known`, its pre-checkpoint points as history, the other comparables as
its comparables) and scored against its actual hours 2–24 with the exact
pinball formula from RULES.txt. Full per-case table: `VALIDATION.md`.

- All 37 pseudo-cases: this entry **0.4186** vs house baseline **0.9296**,
  wins 30/37.
- Big hour-1 launches (hour 1 ≥ 20,000 — the regime GTA VI is expected
  to be in): **0.2569** vs baseline **0.3214**.
- Small hour-1 launches: **0.8549** vs baseline **2.5719**.

Practice cases p00–p03 run clean: valid output shape (23 rows, strictly
non-decreasing quantiles, all in (0, 1e9], files ~1.5 KB), byte-identical
across two runs, ~0.05 s per case.

## Caveats

- Pseudo-practice is not the final: the practice launches' real answers
  are server-side and were not available, and the final is a single case
  (GTA VI itself), the biggest launch in the set — possibly bigger than
  every comparable. If its hour-1 print lands far above 875,000, the
  weights concentrate on the two or three largest launches and the
  forecast leans on them heavily.
- Worst pseudo-cases were launches with an idiosyncratic surge (Resident
  Evil Requiem, loss 1.04; Black Myth: Wukong, simultaneous global unlock
  at 02:00Z, loss 2.03). A GTA VI surprise of that kind (e.g. a
  much-larger-than-expected US unlock surge) would hurt the same way; the
  wide upper quantiles are the mitigation.
- The model does not use the `streams` or `categories_hourly` fields
  (null in practice cases) and does not try to model minute-level
  dynamics inside hour 1.

## Running

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network, deterministic.
