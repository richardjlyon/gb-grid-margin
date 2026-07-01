"""Freeze the settled GB grid state across a window of past half-hours.

One job: turn settled store rows (FUELHH + embedded + system price) into a per-half-hour
frame series, REUSING the live gauge / derived primitives verbatim so a post-mortem frame is
identical, by construction, to the live dial. No new methodology; reads settled stores instead
of live feeds. National basis (transmission + embedded) — matches the live gauge.
"""
from __future__ import annotations

from engine import capacity, import_cost
from engine.grid_engine import compute_verdict
from engine.models import NameplateSeries
from engine.reliability import _MIX_COLUMNS


def extract_frame(fuelhh_row: dict, embedded_row: dict, ns: NameplateSeries,
                  caps: dict[str, int], price: float | None) -> dict:
    """One settled half-hour -> one frame (national basis). See module docstring."""
    mix = {c: (fuelhh_row.get(c) or 0) for c in _MIX_COLUMNS}
    embedded = {
        "solar_mw": embedded_row.get("embedded_solar_mw") or 0,
        "wind_mw": embedded_row.get("embedded_wind_mw") or 0,
        "time": embedded_row.get("period_start_utc"),
    }
    v = compute_verdict(mix, embedded)
    demand = v["national_demand_mw"]
    net = v["net_import_mw"]
    active_cap = import_cost.active_capacity_mw(fuelhh_row, caps)
    wcf = capacity.wind_cf(fuelhh_row, embedded_row, ns)
    scf = capacity.solar_cf(embedded_row)
    pct = lambda x, d: round(x / d * 100, 1) if d else 0.0
    return {
        "t": fuelhh_row["period_start_utc"],
        "sp": int(fuelhh_row["settlement_period"]),
        "firm_pct": v["firm_pct"], "notfirm_pct": v["notfirm_pct"],
        "firm_mw": v["firm_mw"], "notfirm_mw": v["notfirm_mw"], "demand_mw": demand,
        "wind_cf_pct": (round(wcf * 100, 1) if wcf is not None else None), "wind_mw": v["wind_mw"],
        "solar_cf_pct": (round(scf * 100, 1) if scf is not None else None), "solar_mw": v["solar_mw"],
        "import_cf_pct": (round(max(net, 0) / active_cap * 100, 1) if active_cap else None),
        "import_share_pct": pct(net, demand), "net_import_mw": net,
        "price_gbp_mwh": price,
    }


def _price_index(price_rows: list[dict]) -> dict[tuple[str, int], float]:
    return {(r["settlement_date"], int(r["settlement_period"])): r["system_sell_price"]
            for r in price_rows if r.get("system_sell_price") is not None}


def extract_series(date_from: str, date_to: str, *, fuelhh_rows: list[dict],
                   embedded_rows: list[dict], price_rows: list[dict],
                   ns: NameplateSeries, caps: dict[str, int]) -> list[dict]:
    """Frames for every half-hour in BOTH FUELHH and embedded within [date_from, date_to]."""
    emb_by_key = {(r["settlement_date"], int(r["settlement_period"])): r for r in embedded_rows}
    prices = _price_index(price_rows)
    out = []
    for fh in fuelhh_rows:
        d = fh["settlement_date"]
        if d < date_from or d > date_to:
            continue
        k = (d, int(fh["settlement_period"]))
        emb = emb_by_key.get(k)
        if emb is None:
            continue
        out.append(extract_frame(fh, emb, ns, caps, prices.get(k)))
    out.sort(key=lambda f: f["t"])
    return out
