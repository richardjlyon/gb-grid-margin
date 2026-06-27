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

_ONE_DAY = timedelta(days=1)


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


def lull_episodes(daily_series: list[dict], threshold: float = BELOW_10PCT,
                  severe: float = BELOW_5PCT) -> list[dict]:
    """Maximal runs of consecutive calendar days with cf < threshold, start-ascending.

    A calendar gap (a missing/omitted day) breaks the run. min_cf is the deepest day in the run;
    severe is True when the run touched cf < `severe`.
    """
    out: list[dict] = []
    run: list[dict] = []

    def flush():
        if not run:
            return
        deepest = min(run, key=lambda s: s["cf"])
        out.append({
            "start": run[0]["date"], "end": run[-1]["date"], "days": len(run),
            "min_cf": deepest["cf"], "min_cf_date": deepest["date"],
            "severe": deepest["cf"] < severe,
        })

    prev = None
    for s in sorted(daily_series, key=lambda s: s["date"]):
        adjacent = prev is not None and (
            date.fromisoformat(s["date"]) - date.fromisoformat(prev) == _ONE_DAY)
        if s["cf"] < threshold:
            if run and adjacent:
                run.append(s)
            else:
                flush()
                run = [s]
        else:
            flush()
            run = []
        prev = s["date"]
    flush()
    return out
