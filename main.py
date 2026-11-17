"""Forecast GTA VI launch-day Twitch concurrent viewers, hours 2-24.

Method (see README.md): anchor on hour 1's print; for every past big
launch, take the log-ratio of each later hour to that launch's hour 1;
combine the ratios with hour-1-similarity weights (a launch whose hour 1
looked like ours tells us most about our day) and a small tier weight
(console-only single-player AAA up, early-access-contaminated and
multiplayer / free-to-play down); read off weighted quantiles per hour
and smooth the log-quantile curve over neighbouring hours. Pure standard
library, deterministic, no network, no randomness.
"""

import bisect
import json
import math
import os
from datetime import datetime

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
HOURS = range(2, 25)
SIGMA_SIM = 1.0
MULTIPLAYER_NAMES = (
    "Call of Duty",
    "Battlefield",
    "Marvel Rivals",
    "HELLDIVERS",
    "ARC Raiders",
    "Halo Infinite",
)
FALLBACK_SD = 0.15
Z_NORM = (-1.6448536269514722, -0.6744897501960817, 0.0,
          0.6744897501960817, 1.6448536269514722)


def _moment(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _hour_index(day_start, stamp):
    delta = (_moment(stamp) - _moment(day_start)).total_seconds()
    return int(delta // 3600) + 1


def _tier_weight(comp):
    weight = 1.0
    unlock = str(comp.get("unlock") or "")
    if "early-access-contaminated" in unlock:
        weight *= 0.5
    platforms = str(comp.get("platforms") or "")
    if "free-to-play" in platforms:
        weight *= 0.7
    if platforms.strip().endswith("only"):
        weight *= 1.5
    name = str(comp.get("name") or "")
    for token in MULTIPLAYER_NAMES:
        if token in name:
            weight *= 0.5
            break
    return weight


def _launch_curves(case):
    """Return list of (hour1_viewers, {hour: viewers}, tier_weight)."""
    curves = []
    for comp in case.get("comparables") or []:
        if "before release" in str(comp.get("name") or ""):
            continue
        day_start = comp.get("day_start")
        if not day_start:
            continue
        by_hour = {}
        for point in comp.get("hourly") or []:
            viewers = point.get("viewers")
            if not viewers or viewers <= 0:
                continue
            hour = _hour_index(day_start, point["from"])
            if 1 <= hour <= 24:
                by_hour[hour] = float(viewers)
        if 1 not in by_hour or len(by_hour) < 12:
            continue
        curves.append((by_hour[1], by_hour, _tier_weight(comp)))
    return curves


def _weighted_quantiles(pairs, levels):
    """Weighted empirical quantiles with linear interpolation."""
    ordered = sorted(pairs)
    values = [v for v, _ in ordered]
    running = []
    total = 0.0
    for _, w in ordered:
        total += w
        running.append(total)
    out = []
    for level in levels:
        target = level * total
        pos = bisect.bisect_left(running, target)
        if pos <= 0:
            out.append(values[0])
        elif pos >= len(values):
            out.append(values[-1])
        else:
            span = running[pos] - running[pos - 1]
            frac = (target - running[pos - 1]) / span if span > 0 else 0.0
            out.append(values[pos - 1] + frac * (values[pos] - values[pos - 1]))
    return out


def _fallback_row(anchor, hour):
    spread = FALLBACK_SD * math.sqrt(hour - 1)
    return [anchor * math.exp(z * spread) for z in Z_NORM]


def forecast_case(case):
    known = case.get("known") or []
    anchor = 1.0
    if known:
        first = known[0].get("viewers")
        if first and first > 0:
            anchor = float(first)
    log_anchor = math.log(anchor)
    curves = _launch_curves(case)
    log_rows = {}
    for hour in HOURS:
        if not curves:
            log_rows[hour] = [math.log(v) for v in _fallback_row(anchor, hour)]
            continue
        pairs = []
        plain = []
        for hour1, by_hour, tier in curves:
            if hour not in by_hour:
                continue
            similarity = math.exp(
                -0.5 * ((math.log(hour1) - log_anchor) / SIGMA_SIM) ** 2
            )
            pairs.append((math.log(by_hour[hour] / hour1), tier * similarity))
            plain.append((math.log(by_hour[hour] / hour1), tier))
        if not pairs:
            log_rows[hour] = [math.log(v) for v in _fallback_row(anchor, hour)]
            continue
        fitted = _weighted_quantiles(pairs, LEVELS)
        weights = [w for _, w in pairs]
        total_w = sum(weights)
        ess = total_w * total_w / sum(w * w for w in weights)
        # If almost no launch resembles the anchor (effective sample size
        # under 2, only possible for an hour-1 print far outside every
        # comparable), blend back toward the plain tier-weighted quantiles
        # so a single launch cannot dictate the whole day.
        blend = min(1.0, ess / 2.0)
        if blend >= 1.0:
            log_rows[hour] = fitted
        else:
            unweighted = _weighted_quantiles(plain, LEVELS)
            log_rows[hour] = [
                blend * a + (1.0 - blend) * b
                for a, b in zip(fitted, unweighted)
            ]
    smoothed = {}
    for hour in HOURS:
        window = [h for h in range(hour - 1, hour + 2) if h in log_rows]
        smoothed[hour] = [
            sum(log_rows[h][j] for h in window) / len(window)
            for j in range(len(LEVELS))
        ]
    rows = []
    for hour in HOURS:
        quantiles = []
        floor = 0.0
        for log_q in smoothed[hour]:
            value = anchor * math.exp(log_q)
            value = min(max(value, 1.0), 1e9)
            value = max(value, floor)
            floor = value
            quantiles.append(round(value, 2))
        rows.append({"hour": hour, "q": quantiles})
    return {"hours": rows}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(input_dir) if n.endswith(".in"))
    for name in names:
        with open(os.path.join(input_dir, name), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        result = forecast_case(case)
        stem = name[:-3]
        with open(os.path.join(output_dir, stem + ".out"), "w",
                  encoding="utf-8") as fh:
            json.dump(result, fh, separators=(",", ":"))


if __name__ == "__main__":
    main()
