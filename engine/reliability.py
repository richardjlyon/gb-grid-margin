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
