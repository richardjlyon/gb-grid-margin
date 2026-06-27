"""Grid Gauge — whole-record wind unreliability (Entry 03).

Combined-basis daily wind capacity factor over the whole settled store, the lull (drought)
episodes derived from it, and a per-year day-of-year carpet matrix. Combined basis =
(transmission FUELHH WIND + NESO embedded wind) / DUKES total wind nameplate (annual-step) —
a true load factor, artifact-free across years (unlike the lower-bound transmission-only basis
in engine/derived.py). Daily CF is mean-power over the day's joined half-hours. Supersedes the
deleted Entry 03 stripe and Entry 04 tally/records.
"""

from __future__ import annotations

from datetime import date, timedelta

from engine.grid_engine import WIND
from engine.models import NameplateSeries

BELOW_10PCT = 0.10
BELOW_5PCT = 0.05


def combined_daily_cf_series(fuelhh_rows: list[dict], embedded_rows: list[dict],
                             ns: NameplateSeries) -> list[dict]:
    """Per-day combined wind CF over the whole store, date-ascending.

    Daily CF = mean-power: mean of (transmission WIND + embedded wind) over the day's half-hours
    that join the embedded store, / (annual nameplate × 1000). Days with no joined half-hour are
    omitted (keeps the series on the honest combined edge rather than dropping to transmission-only).
    """
    emb_by_key = {(r["settlement_date"], r["settlement_period"]): r for r in embedded_rows}
    by_day: dict[str, list[float]] = {}
    for fh in fuelhh_rows:
        emb = emb_by_key.get((fh["settlement_date"], fh["settlement_period"]))
        if emb is None:
            continue
        trans = sum((fh.get(f) or 0) for f in WIND) if "WIND" not in fh else (fh.get("WIND") or 0)
        combined = trans + (emb.get("embedded_wind_mw") or 0)
        by_day.setdefault(fh["settlement_date"], []).append(combined)
    out = []
    for day in sorted(by_day):
        cap = ns.capacity_for(int(day[:4])).wind_gw
        if cap <= 0:
            continue
        mean_mw = sum(by_day[day]) / len(by_day[day])
        out.append({
            "date": day,
            "cf": round(mean_mw / (cap * 1000), 4),
            "mean_mw": round(mean_mw, 1),
            "capacity_gw": cap,
        })
    return out
