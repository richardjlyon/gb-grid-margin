"""Independent recompute gate for capacity_carpets.json (mirrors test_derived_gate.py).

Recomputes a sample of wind + solar carpet cells straight from the committed CSVs with a separate
code path (no engine.capacity import) and asserts the shipped JSON agrees. Skips cleanly if stores
or the artefact are absent.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

from engine.history import read_store as read_fuelhh
from engine.embedded_history import read_store as read_embedded
from engine.models import NameplateSeries

REPO = Path(__file__).resolve().parent.parent
FUELHH_GLOB = str(REPO / "data" / "history" / "fuelhh_*.csv")
EMB_GLOB = str(REPO / "data" / "history" / "embedded_*.csv")
NS_PATH = REPO / "data" / "nameplate_series.json"
CARPETS = REPO / "site" / "data" / "capacity_carpets.json"

pytestmark = pytest.mark.skipif(
    not glob.glob(FUELHH_GLOB) or not glob.glob(EMB_GLOB) or not NS_PATH.exists()
    or not CARPETS.exists(),
    reason="stores or capacity_carpets.json not present in this checkout",
)


def _cell(days, the_date, sp):
    for d in days:
        if d["date"] == the_date:
            return d["cf"][sp - 1]
    return "MISSING-DAY"


def test_carpet_cells_match_store():
    ns = NameplateSeries.model_validate_json(NS_PATH.read_text())
    emb = {(r["settlement_date"], r["settlement_period"]): r for r in read_embedded()}
    shipped = json.loads(CARPETS.read_text())

    # Recompute every joined cell independently; spot-check a sample against the shipped grids.
    wind_grid, solar_grid = {}, {}
    for fh in read_fuelhh():
        sp = fh["settlement_period"]
        if not (1 <= sp <= 48):
            continue
        e = emb.get((fh["settlement_date"], sp))
        if e is None:
            continue
        wcap = ns.capacity_for(int(fh["settlement_date"][:4])).wind_gw * 1000
        if wcap > 0:
            wnum = (fh.get("WIND") or 0) + (e.get("embedded_wind_mw") or 0)
            wind_grid[(fh["settlement_date"], sp)] = round(wnum / wcap, 4)
        scap = e.get("embedded_solar_capacity_mw")
        if scap and scap > 0:
            solar_grid[(fh["settlement_date"], sp)] = round((e.get("embedded_solar_mw") or 0) / scap, 4)

    # sample cells that exist in the shipped (rolling-window) grids
    for kind, recomputed in (("wind", wind_grid), ("solar", solar_grid)):
        days = shipped[kind]["days"]
        assert 360 <= len(days) <= 367
        assert [d["date"] for d in days] == sorted(d["date"] for d in days)
        checked = 0
        for d in days[:: max(1, len(days) // 20)]:        # ~20 days spread across the window
            for sp in (1, 20, 24, 40):                     # night, morning, midday-ish, evening
                key = (d["date"], sp)
                if key in recomputed:
                    assert _cell(days, d["date"], sp) == recomputed[key], f"{kind} {key}"
                    checked += 1
        assert checked > 0, f"{kind}: no overlapping cells sampled"
