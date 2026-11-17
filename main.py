"""Hour-by-hour Twitch forecast for the GTA VI launch day.

The idea in one paragraph: on launch morning the only number we know is
the first hour's viewer count, so everything is anchored on it. Thirty-seven
past blockbuster launches each lend the shape of their own day, written as
the log of each later hour divided by that launch's first hour. A launch
whose first hour looked like ours counts more (a Gaussian weight on the log
gap), and a launch that resembles GTA VI's profile -- console-only,
single-player, no early-access mess -- counts more again. For every hour we
read off the weighted 5/25/50/75/95 percentiles of those shapes, nudge them
when our first hour sits above every launch on record (a log-linear tilt
fitted across the launches, so the forecast keeps growing with the anchor
instead of falling back to an average shape), smooth the result across
neighbouring hours, and then tighten the band toward the median so the 90%
band really covers about nine hours in ten. Standard library only,
deterministic, no network.
"""

import json
import math
import os
from datetime import datetime

QUANTILE_LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z_SCORES = (-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722)
TARGET_HOURS = range(2, 25)
SIMILARITY_SCALE = 1.0
TAIL_SHRINK = 0.9
MID_SHRINK = 0.85
TILT_SHRINK = 0.5
TILT_CAP = 0.35
TILT_MIN_PEAK = 20000.0
SMOOTH_RADIUS = 1
FALLBACK_SPREAD = 0.15
MULTIPLAYER_TOKENS = (
    "Call of Duty",
    "Battlefield",
    "Marvel Rivals",
    "HELLDIVERS",
    "ARC Raiders",
    "Halo Infinite",
)


def stamp_to_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def hour_within_day(day_start, stamp):
    delta = (stamp_to_time(stamp) - stamp_to_time(day_start)).total_seconds()
    return int(delta // 3600) + 1


def tier_multiplier(comp):
    """How much this comparable should count, from what kind of launch it was."""
    weight = 1.0
    unlock = str(comp.get("unlock") or "").lower()
    if "early-access" in unlock:
        weight *= 0.5
    platforms = str(comp.get("platforms") or "")
    if "free-to-play" in platforms.lower():
        weight *= 0.7
    if platforms.strip().endswith("only"):
        weight *= 1.5
    name = str(comp.get("name") or "")
    for token in MULTIPLAYER_TOKENS:
        if token in name:
            weight *= 0.5
            break
    return weight


def collect_day_curves(case):
    """Turn the comparables into launch-day shapes.

    Each shape is a dict with the launch's first-hour count ("peak"), the
    log ratio of every later hour to that first hour ("shape"), and its tier
    weight. Launches with no first-hour print, fewer than 12 usable hours,
    or a "before release" note are left out: they are not launch days.
    """
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
            hour = hour_within_day(day_start, point["from"])
            if 1 <= hour <= 24:
                by_hour[hour] = float(viewers)
        if 1 not in by_hour or len(by_hour) < 12:
            continue
        peak = by_hour[1]
        shape = {h: math.log(v / peak) for h, v in by_hour.items() if h >= 2}
        curves.append({"peak": peak, "shape": shape,
                       "tier": tier_multiplier(comp)})
    return curves


def weighted_level(samples, level):
    """Weighted empirical quantile with linear interpolation.

    samples is a list of (value, weight). The level is a share of total
    weight; the answer is the value where the running weight first reaches
    that share, interpolated inside the step that crosses it.
    """
    ordered = sorted(samples)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[0][0]
    target = level * total
    running = 0.0
    previous_value, previous_running = ordered[0][0], 0.0
    for value, weight in ordered:
        running += weight
        if running >= target:
            span = running - previous_running
            if span <= 0:
                return value
            frac = (target - previous_running) / span
            return previous_value + frac * (value - previous_value)
        previous_value, previous_running = value, running
    return ordered[-1][0]


def line_fit(xs, ys, ws):
    """Tier-weighted least-squares line; returns (intercept, slope)."""
    total = sum(ws)
    if total <= 0 or len(xs) < 3:
        return 0.0, 0.0
    mean_x = sum(w * x for x, w in zip(xs, ws)) / total
    mean_y = sum(w * y for y, w in zip(ys, ws)) / total
    num = sum(w * (x - mean_x) * (y - mean_y)
              for x, y, w in zip(xs, ys, ws))
    den = sum(w * (x - mean_x) ** 2 for x, w in zip(xs, ws))
    if den <= 1e-12:
        return mean_y, 0.0
    slope = num / den
    return mean_y - slope * mean_x, slope


def fallback_shape(hour):
    """House-baseline style log-ratios, used when no launch covers an hour."""
    spread = FALLBACK_SPREAD * math.sqrt(hour - 1)
    return [z * spread for z in Z_SCORES]


def forecast_case(case):
    known = case.get("known") or []
    anchor = 1.0
    if known:
        first = known[0].get("viewers")
        if first and first > 0:
            anchor = float(first)
    log_anchor = math.log(anchor)
    curves = collect_day_curves(case)
    top_peak = max((c["peak"] for c in curves), default=0.0)
    log_bands = {}
    for hour in TARGET_HOURS:
        pairs = []
        for curve in curves:
            if hour not in curve["shape"]:
                continue
            gap = (math.log(curve["peak"]) - log_anchor) / SIMILARITY_SCALE
            similarity = math.exp(-0.5 * gap * gap)
            pairs.append((curve["shape"][hour], curve["tier"] * similarity))
        if not pairs:
            log_bands[hour] = fallback_shape(hour)
            continue
        band = [weighted_level(pairs, lvl) for lvl in QUANTILE_LEVELS]
        if top_peak > 0 and anchor > top_peak:
            # The anchor sits above every launch on record. Extrapolate the
            # shape log-linearly: fit how this hour's log ratio moves with
            # launch size, then shift the band by the fitted slope times the
            # log gap past the biggest launch. The fit uses only launches of
            # at least TILT_MIN_PEAK first-hour viewers: the smallest
            # launches start near zero and explode later (hour-24 ratios in
            # the hundreds), and letting them set the slope would drag a
            # huge launch's late hours down by a third for no good reason.
            xs, ys, ws = [], [], []
            for curve in curves:
                if curve["peak"] >= TILT_MIN_PEAK and hour in curve["shape"]:
                    xs.append(math.log(curve["peak"]))
                    ys.append(curve["shape"][hour])
                    ws.append(curve["tier"])
            _, slope = line_fit(xs, ys, ws)
            shift = TILT_SHRINK * slope * (log_anchor - math.log(top_peak))
            shift = max(-TILT_CAP, min(TILT_CAP, shift))
            band = [b + shift for b in band]
        log_bands[hour] = band
    smoothed = {}
    for hour in TARGET_HOURS:
        window = [h for h in range(hour - SMOOTH_RADIUS, hour + SMOOTH_RADIUS + 1)
                  if h in log_bands]
        smoothed[hour] = [
            sum(log_bands[h][j] for h in window) / len(window)
            for j in range(len(QUANTILE_LEVELS))
        ]
    rows = []
    for hour in TARGET_HOURS:
        band = smoothed[hour]
        mid = band[2]
        tight = [
            mid + TAIL_SHRINK * (band[0] - mid),
            mid + MID_SHRINK * (band[1] - mid),
            mid,
            mid + MID_SHRINK * (band[3] - mid),
            mid + TAIL_SHRINK * (band[4] - mid),
        ]
        quantiles = []
        floor = 0.0
        for log_q in tight:
            value = anchor * math.exp(log_q)
            value = min(max(value, 1.0), 1e9)
            value = max(value, floor)
            floor = value
            quantiles.append(round(value, 2))
        rows.append({"hour": hour, "q": quantiles})
    return {"hours": rows}


def run():
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
    run()
