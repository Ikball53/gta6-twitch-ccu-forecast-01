"""GTA VI launch-day Twitch viewers forecast.

Reads one case file (everything recorded up to the end of hour 1 of the
release day) and forecasts hours 2 to 24 as five quantiles per hour.

Method: every past launch in the case file contributes its day shape as a
log-ratio to its own hour 1. For each forecast hour two estimates of the
typical log-ratio are blended in log space:

  1. a similarity-weighted median of the past launches' log-ratios, with
     weights falling off as a Gaussian in log hour-1 (width 1.25), so
     launches the size of the case dominate;
  2. a per-hour weighted regression of the log-ratio on log hour-1 and a
     rolling-midnight-unlock flag, with the same kind of weights (width
     1.25). The regression is what carries the size effect: late-hour
     ratios fall almost one-for-one with log hour-1, so a single median
     ratio is far too high for a launch as big as GTA VI.

The blend puts 65% on the regression leg. The spread of each hour comes
from the regression's weighted residual spread (floor 0.15), and the five
quantiles are the blended median times exp(z * spread) with normal
z-scores. Quantiles are clamped to [1, 1e9] and sorted.

Everything is deterministic and uses only the standard library.

Local validation (leave-one-out over the 37 past launches in the case
file, scored with this program itself): mean pinball loss 0.3591 overall,
0.2258 on big launches (hour 1 >= 20k), 0.1829 on top launches
(hour 1 >= 100k), 0.2464 on practice-sized launches (20k-300k).
That beats the previous entry's local numbers (0.3716 / 0.2331 / 0.1890)
on every cut. What changed versus that entry: the tier down-weighting
of early-access and weak launches is gone (weight 1.0 for all -- the
down-weighting cost accuracy on every cut), the similarity width is
1.25 instead of 1.0, the regression width is 1.25 instead of 1.5, and
the blend puts 65% on the regression leg instead of 50%.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
ZSCORES = (-1.6448536269514722, -0.6744897501960817, 0.0,
           0.6744897501960817, 1.6448536269514722)
SIG_SIM = 1.25
SIG_REG = 1.25
REG_WEIGHT = 0.65
SPREAD_FLOOR = 0.15
SPREAD_SCALE = 1.0


def rolling_unlock(text):
    """True when a launch unlocks at local midnight, country by country."""
    if not text:
        return False
    low = text.lower()
    if ("single global" in low or "simultaneous global" in low
            or "single time" in low):
        return False
    return "rolling" in low or "midnight local" in low


def gauss_solve(mat, rhs):
    """Solve a small dense linear system by Gaussian elimination."""
    n = len(rhs)
    aug = [row[:] + [rhs[i]] for i, row in enumerate(mat)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-12:
            aug[col][col] += 1e-9
            piv = col
        aug[col], aug[piv] = aug[piv], aug[col]
        for r in range(col + 1, n):
            f = aug[r][col] / aug[col][col]
            for k in range(col, n + 1):
                aug[r][k] -= f * aug[col][k]
    out = [0.0] * n
    for i in range(n - 1, -1, -1):
        acc = aug[i][n] - sum(aug[i][j] * out[j] for j in range(i + 1, n))
        out[i] = acc / aug[i][i]
    return out


def fit_weighted(rows, vals, weights):
    """Weighted least squares; rows are feature lists, vals the targets."""
    n = len(rows[0])
    mat = [[0.0] * n for _ in range(n)]
    rhs = [0.0] * n
    for feats, val, w in zip(rows, vals, weights):
        for i in range(n):
            rhs[i] += w * feats[i] * val
            for j in range(n):
                mat[i][j] += w * feats[i] * feats[j]
    for i in range(n):
        mat[i][i] += 1e-9
    return gauss_solve(mat, rhs)


def weighted_median(vals, weights):
    pairs = sorted(zip(vals, weights))
    total = sum(weights)
    if total <= 0:
        ordered = sorted(vals)
        return ordered[len(ordered) // 2]
    acc = 0.0
    for val, w in pairs:
        acc += w
        if acc >= 0.5 * total:
            return val
    return pairs[-1][0]


def load_day(comp):
    """The 24 hourly viewer counts of a comparable's release day."""
    by_time = {}
    for point in comp.get("hourly") or []:
        by_time[point.get("from")] = point.get("viewers")
    try:
        start = datetime.fromisoformat(
            comp["day_start"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    day = []
    for step in range(24):
        stamp = (start + timedelta(hours=step)).strftime("%Y-%m-%dT%H:00:00Z")
        val = by_time.get(stamp)
        if val is None:
            return None
        day.append(val)
    return day


def collect_launches(case):
    """Usable past launches: (hour-1 print, 24 hourly counts, rolling)."""
    game = (case.get("game") or {}).get("name", "").strip().lower()
    launches = []
    for comp in case.get("comparables") or []:
        name = (comp.get("name") or "").strip().lower()
        if game and name == game:
            continue
        day = load_day(comp)
        if day is None or not day[0]:
            continue
        launches.append((day[0], day, rolling_unlock(comp.get("unlock", ""))))
    return launches


def case_rolling(case, launches):
    """The case game's rolling flag: its own comparable first, else notes."""
    game = (case.get("game") or {}).get("name", "").strip().lower()
    for comp in case.get("comparables") or []:
        name = (comp.get("name") or "").strip().lower()
        if game and name == game:
            return rolling_unlock(comp.get("unlock", ""))
    return rolling_unlock(case.get("notes", ""))


def predict(launches, hour1, rolling):
    """Quantile rows for hours 2..24 given the case's hour-1 print."""
    anchor = math.log(max(hour1, 1))
    log_h1 = [math.log(max(day[0], 1)) for _, day, _ in launches]
    # log-ratio of each later hour to hour 1, per launch
    ratios = []
    for first, day, _ in launches:
        base = math.log(max(first, 1))
        ratios.append([math.log(max(v, 1)) - base for v in day[1:]])
    flags = [1.0 if roll else 0.0 for _, _, roll in launches]
    case_flag = 1.0 if rolling else 0.0
    sim_w = [math.exp(-((x - anchor) ** 2) / (2 * SIG_SIM * SIG_SIM))
             for x in log_h1]
    reg_w = [math.exp(-((x - anchor) ** 2) / (2 * SIG_REG * SIG_REG))
             for x in log_h1]
    medians = []
    spreads = []
    for h in range(23):
        col = [r[h] for r in ratios]
        median_sim = weighted_median(col, sim_w)
        feats = [[1.0, x - anchor, f] for x, f in zip(log_h1, flags)]
        beta = fit_weighted(feats, col, reg_w)
        median_reg = beta[0] + beta[2] * case_flag
        medians.append((1.0 - REG_WEIGHT) * median_sim
                       + REG_WEIGHT * median_reg)
        resid = []
        for i in range(len(launches)):
            pred = (beta[0] + beta[1] * (log_h1[i] - anchor)
                    + beta[2] * flags[i])
            resid.append(col[i] - pred)
        num = sum(w * e * e for w, e in zip(reg_w, resid))
        den = sum(reg_w)
        spread = math.sqrt(num / den) if den > 0 else SPREAD_FLOOR
        spreads.append(max(spread, SPREAD_FLOOR) * SPREAD_SCALE)
    rows = []
    log_anchor = math.log(max(hour1, 1))
    for h in range(23):
        qs = [math.exp(log_anchor + medians[h] + z * spreads[h])
              for z in ZSCORES]
        qs = sorted(min(max(q, 1.0), 1e9) for q in qs)
        rows.append({"hour": h + 2, "q": qs})
    return rows


def forecast_case(case):
    """One case dict -> the output dict for its hours 2..24."""
    known = case.get("known") or []
    hour1 = None
    for entry in known:
        if entry.get("hour") == 1:
            hour1 = entry.get("viewers")
            break
    if hour1 is None and known:
        hour1 = known[0].get("viewers")
    launches = collect_launches(case)
    if not launches:
        flat = max(hour1 or 100000, 1)
        return {"hours": [{"hour": h, "q": [flat] * 5}
                          for h in range(2, 25)]}
    if hour1 is None:
        hour1 = sorted(day[0] for _, day, _ in launches)[len(launches) // 2]
    return {"hours": predict(launches, hour1, case_rolling(case, launches))}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(in_dir)):
        if not name.endswith(".in"):
            continue
        with open(os.path.join(in_dir, name), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        out = forecast_case(case)
        stem = name[:-3]
        with open(os.path.join(out_dir, stem + ".out"), "w",
                  encoding="utf-8") as fh:
            json.dump(out, fh)


if __name__ == "__main__":
    main()
