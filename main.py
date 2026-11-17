#!/usr/bin/env python3
"""Forecast GTA VI's launch-day Twitch viewers, hours 2-24, as five quantiles.

Why this entry looks different from a plain ratio-to-hour-1 model: the
earlier entries missed the median by about 44% on the practice set, and
shrinking the intervals did nothing, so the median itself was wrong. Two
facts about the comparable launches explain the miss:

1. A launch's day shape depends strongly on its hour-1 size. Small
   launches explode 100x later in the day (their first hour is nearly
   empty) while big launches stay near their hour-1 level. Across the
   comparables the late-hour log-ratio falls almost one-for-one with
   log hour-1 (slope about -0.9, correlation about -0.94 at hour 20).
   A single median ratio therefore sits far too high for a big anchor
   like GTA VI and far too low for a small one.

2. Launches that unlock at rolling local midnight have a different day
   shape from simultaneous-global launches: a quiet first hour that
   rises as each region unlocks, instead of starting near the peak.
   GTA VI unlocks at rolling local midnight, so the model must know
   which shape family the case belongs to.

The forecast blends two legs per hour. Leg A is a similarity-weighted
median of the comparables' log-ratios to hour 1 (Gaussian kernel on
log hour-1, plus tier and genre weights). Leg B is a per-hour weighted
regression of the log-ratio on log hour-1 plus a rolling-unlock
indicator. The median is the geometric mean of the two legs' medians;
the spread is the regression's residual spread. Pure standard library,
deterministic, no network.
"""

import glob
import json
import math
import os
import sys
from datetime import datetime, timedelta

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

# Similarity kernel width (in log hour-1) for each leg.
SIGMA_MEDIAN = 1.0
SIGMA_REGRESS = 1.5
# Blend weight on the regression leg's median (0.5 = geometric mean).
BLEND_REGRESS = 0.5
# Floor on the residual log-spread so a lucky tight fit cannot go razor thin.
SD_FLOOR = 0.15

# Multiplayer / free-to-play launches behave differently from a paid
# single-player console launch; down-weight them.
MULTIPLAYER_NAMES = ("Call of Duty", "Battlefield", "Marvel Rivals",
                     "HELLDIVERS", "ARC Raiders", "Halo Infinite")
# Console-only single-player tentpoles are the closest GTA analogues.
CONSOLE_TENTPOLES = ("The Last of Us Part II", "Ghost of Tsushima",
                     "Ghost of Y\u014dtei", "Death Stranding 2: On the Beach",
                     "Stellar Blade",
                     "The Legend of Zelda: Tears of the Kingdom")


def parse_iso(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def weighted_quantile(values, weights, tau):
    """Smallest value whose cumulative weight reaches tau of the total."""
    pairs = sorted(zip(values, weights))
    total = sum(weights)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if acc >= tau * total:
            return value
    return pairs[-1][0]


def solve_linear(matrix, vector):
    """Gaussian elimination with partial pivoting; None if singular."""
    n = len(vector)
    rows = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[piv][col]) < 1e-12:
            return None
        rows[col], rows[piv] = rows[piv], rows[col]
        for r in range(col + 1, n):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, n + 1):
                rows[r][c] -= factor * rows[col][c]
    out = [0.0] * n
    for i in range(n - 1, -1, -1):
        out[i] = (rows[i][n] - sum(rows[i][j] * out[j]
                                    for j in range(i + 1, n))) / rows[i][i]
    return out


def weighted_least_squares(rows, ys, ws):
    """Fit ys ~ rows (first column is the intercept). Returns (beta, sd)."""
    k = len(rows[0])
    normal = [[0.0] * k for _ in range(k)]
    rhs = [0.0] * k
    for row, y, w in zip(rows, ys, ws):
        for i in range(k):
            rhs[i] += w * row[i] * y
            for j in range(k):
                normal[i][j] += w * row[i] * row[j]
    beta = solve_linear(normal, rhs)
    if beta is None:
        return None
    resid = [y - sum(b * x for b, x in zip(beta, row))
             for row, y in zip(rows, ys)]
    var = sum(w * r * r for r, w in zip(resid, ws)) / sum(ws)
    return beta, math.sqrt(max(var, 1e-12))


def tier_of(unlock_text):
    """Tier tag the kit writes into each comparable's unlock note."""
    text = (unlock_text or "").lower()
    if "tier:" not in text:
        return "comparable"
    return text.split("tier:", 1)[1].split(".")[0].split(",")[0].strip()


def comparable_weight(name, unlock_text, h1_case, h1_other, sigma):
    """Tier/genre weight times a Gaussian kernel on log hour-1 distance."""
    weight = 1.0
    tier = tier_of(unlock_text)
    if tier.startswith("early-access") or tier.startswith("weak"):
        weight *= 0.5
    if any(tag in name for tag in MULTIPLAYER_NAMES):
        weight *= 0.5
    if "Marvel Rivals" in name:
        weight *= 0.7
    if name in CONSOLE_TENTPOLES:
        weight *= 1.5
    gap = math.log(max(h1_other, 1.0)) - math.log(max(h1_case, 1.0))
    weight *= math.exp(-(gap * gap) / (2.0 * sigma * sigma))
    return weight


def release_curve(comp):
    """The comparable's 24 release-day hourly viewer counts, None if missing."""
    try:
        start = parse_iso(comp["day_start"])
    except (KeyError, ValueError):
        return None
    by_time = {}
    for point in comp.get("hourly", []):
        try:
            by_time[parse_iso(point["from"])] = point["viewers"]
        except (KeyError, ValueError):
            continue
    return [by_time.get(start + timedelta(hours=h)) for h in range(24)]


def is_target_history(comp):
    """The case game's own pre-release category history: not a launch."""
    name = (comp.get("name") or "").lower()
    unlock = (comp.get("unlock") or "").lower()
    return ("grand theft auto vi" in name or "target-history" in unlock
            or "not a launch" in unlock)


def rolling_unlock(text):
    """True when the unlock rolls at local midnight instead of one global time."""
    low = (text or "").lower()
    return "rolling" in low or "midnight local" in low


def case_rolling_flag(case, comparables):
    """Rolling-midnight flag for the case's own game.

    Prefer the game's own category-history comparable when the case
    carries one (the final case does); otherwise read the case notes,
    which name the real unlock; default to rolling, the norm for the
    console launches in this competition.
    """
    game_name = (case.get("game") or {}).get("name", "").lower()
    for comp in comparables:
        # Only the game's own pre-release history comparable speaks for
        # the case game: a plain substring match would confuse e.g.
        # "Elden Ring" with "Elden Ring Nightreign", a different launch.
        if (game_name and is_target_history(comp)
                and game_name in (comp.get("name") or "").lower()):
            return rolling_unlock(comp.get("unlock", ""))
    notes = case.get("notes", "")
    if not isinstance(notes, str):
        notes = json.dumps(notes)
    if "rolling" in notes.lower() or "midnight local" in notes.lower():
        return True
    if "simultaneous" in notes.lower() or "single global" in notes.lower():
        return False
    # Unknown unlock: treat as not rolling. The comparables show most
    # launches without a documented rolling unlock do not behave like
    # one, and defaulting to rolling here measurably worsened the
    # leave-one-out score (overall 0.398 vs 0.372).
    return False


def forecast_case(case):
    """Return the 23 forecast rows for one case dict."""
    known = case.get("known") or [{}]
    hour1 = known[0].get("viewers") or 1
    hour1 = max(float(hour1), 1.0)

    comparables = case.get("comparables") or []
    is_rolling = case_rolling_flag(case, comparables)

    # Training set: every comparable with a usable release-day curve.
    train = []
    for comp in comparables:
        if is_target_history(comp):
            continue
        curve = release_curve(comp)
        if not curve or not curve[0] or curve[0] <= 0:
            continue
        train.append({
            "name": comp.get("name", ""),
            "unlock": comp.get("unlock", ""),
            "curve": curve,
            "rolling": rolling_unlock(comp.get("unlock", "")),
        })

    log_h1 = math.log(hour1)
    rows = []
    for hour in range(2, 25):
        idx = hour - 1
        # --- Leg A: similarity-weighted quantiles of the log-ratio. ---
        vals_a, weights_a = [], []
        for comp in train:
            value = comp["curve"][idx]
            if value is None or value <= 0:
                continue
            vals_a.append(math.log(value / comp["curve"][0]))
            weights_a.append(comparable_weight(
                comp["name"], comp["unlock"], hour1, comp["curve"][0],
                SIGMA_MEDIAN))
        # --- Leg B: weighted regression on log hour-1 + rolling flag. ---
        reg = None
        if len(vals_a) >= 4:
            rows_b, ys_b, ws_b = [], [], []
            for comp in train:
                value = comp["curve"][idx]
                if value is None or value <= 0:
                    continue
                rows_b.append([1.0, math.log(comp["curve"][0]),
                               1.0 if comp["rolling"] else 0.0])
                ys_b.append(math.log(value / comp["curve"][0]))
                ws_b.append(comparable_weight(
                    comp["name"], comp["unlock"], hour1,
                    comp["curve"][0], SIGMA_REGRESS))
            reg = weighted_least_squares(rows_b, ys_b, ws_b)

        if not vals_a:
            # No training data at all: fall back to the house persistence
            # baseline shape (flat median, spread widening over the day).
            spread = 0.15 * math.sqrt(hour - 1)
            rows.append({"hour": hour,
                         "q": [round(hour1 * math.exp(z * spread), 2)
                               for z in Z]})
            continue

        quantiles_a = [hour1 * math.exp(weighted_quantile(vals_a, weights_a, t))
                       for t in LEVELS]
        if reg is None:
            rows.append({"hour": hour,
                         "q": [round(q, 2) for q in quantiles_a]})
            continue
        beta, resid_sd = reg
        pred = beta[0] + beta[1] * log_h1 + beta[2] * (1.0 if is_rolling else 0.0)
        spread = max(resid_sd, SD_FLOOR)
        quantiles_b = [hour1 * math.exp(pred + z * spread) for z in Z]

        # Blend the medians in log space; take the spread from leg B.
        median = math.exp(BLEND_REGRESS * math.log(quantiles_b[2])
                          + (1.0 - BLEND_REGRESS) * math.log(quantiles_a[2]))
        blend_sd = (math.log(quantiles_b[4]) - math.log(quantiles_b[0])
                    ) / (2.0 * 1.6448536269514722)
        quantiles = [median * math.exp(z * blend_sd) for z in Z]
        quantiles = [min(max(q, 1.0), 1e9) for q in quantiles]
        quantiles.sort()
        rows.append({"hour": hour, "q": [round(q, 2) for q in quantiles]})
    return {"hours": rows}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(input_dir, "*.in")))
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            case = json.load(handle)
        case_id = case.get("id") or os.path.splitext(
            os.path.basename(path))[0]
        result = forecast_case(case)
        out_path = os.path.join(output_dir, case_id + ".out")
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
