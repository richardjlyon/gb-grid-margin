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


def _doy_labels() -> list[str]:
    """The 366 'MM-DD' column keys, using a leap year (2020) so 29 Feb has a slot."""
    d, end = date(2020, 1, 1), date(2020, 12, 31)
    out = []
    while d <= end:
        out.append(d.strftime("%m-%d"))
        d += _ONE_DAY
    return out


def carpet_matrix(daily_series: list[dict]) -> dict:
    """Years × day-of-year CF grid. Columns keyed by month-day (29 Feb aligned); gaps -> None."""
    labels = _doy_labels()
    col = {lab: i for i, lab in enumerate(labels)}
    years = sorted({int(s["date"][:4]) for s in daily_series})
    rows = {str(y): [None] * len(labels) for y in years}
    for s in daily_series:
        rows[s["date"][:4]][col[s["date"][5:]]] = s["cf"]
    return {"years": years, "doy": labels, "rows": rows}


from engine.guards import require  # noqa: E402

_BASIS = (
    "Daily wind capacity factor = mean-power of (transmission WIND [Elexon FUELHH, settled] + "
    "embedded wind [NESO outturn]) over the day's joined half-hours / DUKES total UK wind nameplate "
    "(annual-step). Combined basis: a true load factor, artifact-free across years (unlike the "
    "transmission-only lower bound). A lull is a run of consecutive days with CF below 10%; severity "
    "is the lowest CF reached (below 5% = severe). Supersedes the former stripe/tally figures."
)
_SOURCE = "Elexon FUELHH (settled) + NESO embedded wind / DUKES 6.2 wind nameplate (annual-step)"
_THRESHOLDS = [("ge_1d", 1), ("ge_3d", 3), ("ge_7d", 7), ("ge_14d", 14)]


def summary(daily_series: list[dict], lulls: list[dict]) -> dict:
    counts = {key: sum(1 for l in lulls if l["days"] >= n) for key, n in _THRESHOLDS}
    record = max(lulls, key=lambda l: l["days"]) if lulls else None
    lowest = min(daily_series, key=lambda s: s["cf"]) if daily_series else None
    worst: dict[str, int] = {}
    for l in lulls:
        y = l["start"][:4]
        worst[y] = max(worst.get(y, 0), l["days"])
    lowest_day = None
    if lowest:
        lowest_day = {k: lowest[k] for k in ("date", "cf") if k in lowest}
        for k in ("mean_mw", "capacity_gw"):
            if k in lowest:
                lowest_day[k] = lowest[k]
    mean_cf = round(sum(s["cf"] for s in daily_series) / len(daily_series), 4) if daily_series else 0.0
    below_10 = sum(1 for s in daily_series if s["cf"] < BELOW_10PCT)
    below_5 = sum(1 for s in daily_series if s["cf"] < BELOW_5PCT)
    return {
        "counts": counts,
        "record_lull": record,
        "lowest_day": lowest_day,
        "worst_lull_by_year": worst,
        "mean_cf": mean_cf,
        "below_10pct_days": below_10,
        "below_5pct_days": below_5,
    }


def build_payload(daily_series: list[dict], generated_utc: str) -> dict:
    from engine.derived import partial_years  # deferred to break circular import
    lulls = lull_episodes(daily_series)
    dates = [s["date"] for s in daily_series]
    return {
        "basis": _BASIS, "source": _SOURCE, "generated_utc": generated_utc,
        "range": {"from": (dates[0] if dates else None), "to": (dates[-1] if dates else None)},
        "partial_years": partial_years(dates),
        "thresholds": {"below_10pct": BELOW_10PCT, "below_5pct": BELOW_5PCT},
        "windy_anchor_cf": 0.45,
        "carpet": carpet_matrix(daily_series),
        "lulls": lulls,
        "summary": summary(daily_series, lulls),
    }


def guard_payload(payload: dict) -> None:
    """Build-time gate: fail loudly before wind_unreliability.json is written."""
    carpet = payload["carpet"]
    require(len(carpet["doy"]) == 366, f"carpet doy length {len(carpet['doy'])}, expected 366")
    require(len(carpet["years"]) > 0, "carpet has no years")
    for y, cells in carpet["rows"].items():
        require(len(cells) == 366, f"carpet row {y}: {len(cells)} cells, expected 366")
        for v in cells:
            require(v is None or 0.0 <= v <= 1.0 + 1e-6, f"carpet {y}: cf {v} out of [0,1]")
    for l in payload["lulls"]:
        require(l["days"] >= 1, f"lull {l['start']}: non-positive length {l['days']}")
        require(l["start"] <= l["end"], f"lull {l['start']}: start after end")
        require(0.0 <= l["min_cf"] < BELOW_10PCT, f"lull {l['start']}: min_cf {l['min_cf']} not sub-10%")
