"""Live wind-lull run series for the Grid Conditions panel.

A small, near-real-time daily series: mean transmission wind MW per day (Elexon FUELHH, settled to
yesterday) over DUKES total UK wind nameplate. This is the site's transmission-only LOWER-BOUND basis
(as used by the stripe/counters) — chosen here over Entry 03's combined basis because the combined
basis needs NESO embedded wind, which lags ~3 weeks and so cannot drive a *live* run counter. The
< 20% line reproduces the combined-basis < 25% day-count (both light ~43% of days). The panel's wind
lamp lights while we are in a run of consecutive sub-20% days; the run length is the story.
"""
from __future__ import annotations

from datetime import date
from itertools import groupby

from engine.grid_engine import WIND

WIND_LIVE_LULL_PCT = 20
RECENT_DAYS = 40

_BASIS = ("Daily wind capacity factor = mean transmission wind power (Elexon FUELHH, settled) over the "
          "day / DUKES total UK wind nameplate. Transmission-only lower bound, fresh to the last settled "
          "day; comparable to Entry 03's combined-basis carpet. Lull = run of consecutive days below "
          f"{WIND_LIVE_LULL_PCT}% CF.")


def daily_transmission_cf_series(rows: list[dict], wind_nameplate_mw: float) -> list[dict]:
    out: list[dict] = []
    for date, day_rows in groupby(rows, key=lambda r: r["settlement_date"]):
        vals = [r[c] for r in day_rows for c in WIND if r.get(c) is not None]
        if not vals:
            continue
        mean_mw = sum(vals) / len(vals)
        out.append({"date": date, "cf_pct": round(mean_mw / wind_nameplate_mw * 100, 1)})
    out.sort(key=lambda s: s["date"])
    return out


def _adjacent(a: str, b: str) -> bool:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    return (db - da).days == 1


def current_run(series: list[dict], threshold_pct: float = WIND_LIVE_LULL_PCT) -> dict:
    if not series:
        return {"as_of": None, "current_run_days": 0, "current_cf_pct": None}
    as_of = series[-1]["date"]
    cf = series[-1]["cf_pct"]
    days = 0
    prev_date = None
    for s in reversed(series):
        if s["cf_pct"] >= threshold_pct:
            break
        if prev_date is not None and not _adjacent(s["date"], prev_date):
            break
        days += 1
        prev_date = s["date"]
    return {"as_of": as_of, "current_run_days": days, "current_cf_pct": cf}


def build_payload(rows: list[dict], wind_nameplate_mw: float, generated_utc: str) -> dict:
    series = daily_transmission_cf_series(rows, wind_nameplate_mw)
    run = current_run(series)
    return {
        "basis": _BASIS,
        "threshold_pct": WIND_LIVE_LULL_PCT,
        "generated_utc": generated_utc,
        "as_of": run["as_of"],
        "current_run_days": run["current_run_days"],
        "current_cf_pct": run["current_cf_pct"],
        "recent": series[-RECENT_DAYS:],
    }
