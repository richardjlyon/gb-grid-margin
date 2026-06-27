# tests/test_capacity_gate.py
"""Independent recompute gate for capacity_curve.json (mirrors test_derived_gate.py).

Recomputes the load-duration curve + stats straight from the committed CSVs with a
separate code path (raw readers, inline arithmetic, no engine.capacity import) and asserts
the shipped JSON agrees. Skips cleanly if the stores or the artefact are absent.
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
CURVE_JSON = REPO / "site" / "data" / "capacity_curve.json"

pytestmark = pytest.mark.skipif(
    not glob.glob(FUELHH_GLOB) or not CURVE_JSON.exists(),
    reason="history store or capacity_curve.json not present in this checkout",
)

from datetime import datetime, timedelta, timezone


def _parse(t):
    return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _recompute():
    ns = NameplateSeries.model_validate_json((REPO / "data" / "nameplate_series.json").read_text())
    fh = read_fuelhh()
    emb = {(r["settlement_date"], r["settlement_period"]): r for r in read_embedded()}
    series = []
    for r in fh:
        e = emb.get((r["settlement_date"], r["settlement_period"]))
        if e is None:
            continue
        cap = ns.capacity_for(int(r["settlement_date"][:4]))
        denom = (cap.wind_gw + cap.solar_gw) * 1000
        if denom <= 0:
            continue
        num = (r.get("WIND") or 0) + (e.get("embedded_wind_mw") or 0) + (e.get("embedded_solar_mw") or 0)
        series.append((r["period_start_utc"], num / denom))
    series.sort()
    cutoff = _parse(series[-1][0]) - timedelta(days=365)
    win = [cf for t, cf in series if _parse(t) >= cutoff]
    return win


def test_capacity_curve_matches_store():
    win = _recompute()
    shipped = json.loads(CURVE_JSON.read_text())
    assert shipped["n_periods"] == len(win)

    # curve: descending sample at i/200 of the time, as % of nameplate
    desc = sorted(win, reverse=True)
    n = len(desc)
    expect = [round(desc[min(n - 1, int((i / 200) * n))] * 100, 2) for i in range(200)]
    assert shipped["curve"] == expect

    # a couple of stats
    asc = sorted(win)
    median = round(asc[min(n - 1, round(0.5 * (n - 1)))] * 100, 2)
    assert shipped["stats"]["median_pct"] == median
    below10 = round(sum(1 for c in win if c < 0.10) / n, 4)
    assert shipped["stats"]["below_10pct_frac"] == below10
