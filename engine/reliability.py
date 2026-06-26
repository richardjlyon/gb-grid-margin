"""Grid Gauge — national reliable-share half-hourly series (Reliability Stripe, Stage B).

The reliable (firm) share of demand for each settled half-hour, computed by REUSING the
live gauge's `compute_verdict` so the historical series is identical, by construction, to
the dial (the formula is parity-locked Python<->JS and fuzz-tested). Joins the settled
FUELHH store to the embedded store (Stage A) on (settlement_date, settlement_period);
emits a compact packed series the dashboard stripe renders.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.grid_engine import compute_verdict
from engine.history import FUELS, INTERCONNECTORS

# The fuel + interconnector columns compute_verdict consumes as its `mix`.
_MIX_COLUMNS = FUELS + INTERCONNECTORS


def reliable_share(fuelhh_row: dict, embedded_row: dict) -> float | None:
    """Reliable (firm) share of national demand for one half-hour, in [0,1], or None.

    Reuses `compute_verdict` (the gauge's parity-locked formula); `national_demand` there
    is the supply reconstruction firm+notfirm, so firm_mw/demand is the reliable share.
    Blank (None) cells coerce to 0 so the `v > 0` checks never see None. Returns None when
    demand reconstructs to <= 0 (an all-blank/missing half-hour) — the series carries a gap.
    """
    mix = {c: (fuelhh_row.get(c) or 0) for c in _MIX_COLUMNS}
    embedded = {
        "solar_mw": embedded_row.get("embedded_solar_mw") or 0,
        "wind_mw": embedded_row.get("embedded_wind_mw") or 0,
        "time": embedded_row.get("period_start_utc"),
    }
    v = compute_verdict(mix, embedded)
    demand = v["national_demand_mw"]
    if not demand or demand <= 0:
        return None
    return round(v["firm_mw"] / demand, 4)


def build_series(fuelhh_rows: list[dict], embedded_rows: list[dict]) -> list[dict]:
    """Reliable-share series for every half-hour present in BOTH stores, sorted by time.

    Omits half-hours missing from either store or whose share is None; those surface as
    `null` gaps once packed onto the regular grid (Task 3).
    """
    emb_by_key = {(r["settlement_date"], r["settlement_period"]): r for r in embedded_rows}
    out = []
    for fh in fuelhh_rows:
        emb = emb_by_key.get((fh["settlement_date"], fh["settlement_period"]))
        if emb is None:
            continue
        r = reliable_share(fh, emb)
        if r is None:
            continue
        out.append({"t": fh["period_start_utc"], "r": r})
    out.sort(key=lambda x: x["t"])
    return out


def _parse(t: str) -> datetime:
    return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def pack(series: list[dict]) -> dict:
    """Pack a sorted reliable-share series onto a regular 30-min UTC grid.

    `values[i]` is the share at start_utc + i*30min, None where the half-hour is absent.
    """
    if not series:
        return {"start_utc": None, "step_minutes": 30, "values": [],
                "range": {"from": None, "to": None}, "gap_count": 0}
    start = _parse(series[0]["t"])
    end = _parse(series[-1]["t"])
    n = int((end - start).total_seconds() // 1800) + 1
    values: list[float | None] = [None] * n
    for s in series:
        i = int((_parse(s["t"]) - start).total_seconds() // 1800)
        values[i] = s["r"]
    return {
        "start_utc": series[0]["t"],
        "step_minutes": 30,
        "values": values,
        "range": {"from": series[0]["t"], "to": series[-1]["t"]},
        "gap_count": sum(1 for v in values if v is None),
    }


def rolling_year(series: list[dict], months: int = 12) -> list[dict]:
    """The sub-series within `months` (≈ 365 days) of the latest half-hour."""
    if not series:
        return []
    cutoff = _parse(series[-1]["t"]) - timedelta(days=round(months / 12 * 365))
    return [s for s in series if _parse(s["t"]) >= cutoff]
