"""Grid Gauge — renewables capacity-factor load-duration series (Entry 02).

Per-half-hour renewables capacity factor on the SAME basis as the live capacity-trap
gauge: (transmission wind + embedded wind + embedded solar) / DUKES wind+solar nameplate.
Because embedded output is in the numerator this is a TRUE load factor, NOT the
transmission-only lower bound the wind stripe (engine.derived) carries — so the §8
cross-year confound does not apply here. Joins the settled FUELHH store to the embedded
store on (settlement_date, settlement_period), takes the rolling last 12 months, and emits
a compact 200-point load-duration curve + summary stats the dashboard renders.

The only seam to the live gauge is live-FORECAST vs settled-OUTTURN for the embedded
component (the same seam the reliability stripe discloses), not a basis difference.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.grid_engine import WIND
from engine.models import NameplateSeries

CURVE_POINTS = 200


def _parse(t: str) -> datetime:
    return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def cf_for_period(fuelhh_row: dict, embedded_row: dict, ns: NameplateSeries) -> float | None:
    """Renewables CF for one half-hour as a fraction of nameplate, or None if no capacity.

    Numerator = transmission wind (FUELHH) + embedded wind + embedded solar (NESO outturn).
    Denominator = DUKES wind+solar nameplate for the period's year (annual-step), in MW.
    Blank (None) cells coerce to 0.
    """
    year = int(fuelhh_row["settlement_date"][:4])
    cap = ns.capacity_for(year)
    denom_mw = (cap.wind_gw + cap.solar_gw) * 1000
    if denom_mw <= 0:
        return None
    wind_t = sum((fuelhh_row.get(f) or 0) for f in WIND)
    emb_wind = embedded_row.get("embedded_wind_mw") or 0
    emb_solar = embedded_row.get("embedded_solar_mw") or 0
    return (wind_t + emb_wind + emb_solar) / denom_mw


def build_cf_series(fuelhh_rows: list[dict], embedded_rows: list[dict],
                    ns: NameplateSeries) -> list[dict]:
    """Per-half-hour CF for every half-hour present in BOTH stores, sorted by time."""
    emb_by_key = {(r["settlement_date"], r["settlement_period"]): r for r in embedded_rows}
    out = []
    for fh in fuelhh_rows:
        emb = emb_by_key.get((fh["settlement_date"], fh["settlement_period"]))
        if emb is None:
            continue
        cf = cf_for_period(fh, emb, ns)
        if cf is None:
            continue
        out.append({"t": fh["period_start_utc"], "cf": cf})
    out.sort(key=lambda x: x["t"])
    return out


def rolling_year(series: list[dict], months: int = 12) -> list[dict]:
    """The sub-series within `months` (≈ 365 days) of the latest half-hour."""
    if not series:
        return []
    cutoff = _parse(series[-1]["t"]) - timedelta(days=round(months / 12 * 365))
    return [s for s in series if _parse(s["t"]) >= cutoff]


def load_duration_curve(series: list[dict], points: int = CURVE_POINTS) -> list[float]:
    """Downsample a CF series to a `points`-length load-duration curve, % of nameplate, descending.

    curve[i] is the CF (as a 0-100 percentage) exceeded i/points of the time, so curve[0]
    is the maximum and the curve is non-increasing.
    """
    vals = sorted((s["cf"] for s in series), reverse=True)
    n = len(vals)
    if n == 0:
        return []
    out = []
    for i in range(points):
        idx = min(n - 1, int((i / points) * n))
        out.append(round(vals[idx] * 100, 2))
    return out


def _percentile(sorted_asc: list[float], q: float) -> float:
    """Nearest-rank percentile on an ascending list, q in [0,1]."""
    n = len(sorted_asc)
    idx = min(n - 1, max(0, round(q * (n - 1))))
    return sorted_asc[idx]


def summary_stats(series: list[dict]) -> dict:
    """Mean/quartiles (% of nameplate) and threshold fractions for the window."""
    cfs = [s["cf"] for s in series]
    n = len(cfs)
    if n == 0:
        return {}
    asc = sorted(cfs)
    pct = lambda x: round(x * 100, 2)                              # noqa: E731
    frac = lambda pred: round(sum(1 for c in cfs if pred(c)) / n, 4)  # noqa: E731
    return {
        "mean_pct": pct(sum(cfs) / n),
        "median_pct": pct(_percentile(asc, 0.5)),
        "p25_pct": pct(_percentile(asc, 0.25)),
        "p75_pct": pct(_percentile(asc, 0.75)),
        "above_50pct_frac": frac(lambda c: c > 0.50),
        "above_25pct_frac": frac(lambda c: c > 0.25),
        "below_10pct_frac": frac(lambda c: c < 0.10),
        "below_5pct_frac": frac(lambda c: c < 0.05),
    }
