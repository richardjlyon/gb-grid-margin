"""Source-trace gate: reliability_carpet.json must match an independent raw-CSV recompute."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from engine.grid_engine import compute_verdict
from engine.history import FUELS, INTERCONNECTORS

DATA = Path("data/history")
CARPET = Path("site/data/reliability_carpet.json")
_MIX = FUELS + INTERCONNECTORS

pytestmark = pytest.mark.skipif(
    not CARPET.exists()
    or not list(DATA.glob("embedded_*.csv"))
    or not list(DATA.glob("fuelhh_*.csv")),
    reason="reliability_carpet.json or embedded/fuelhh store not present in this checkout",
)


def _rows(pattern):
    out = {}
    for p in sorted(DATA.glob(pattern)):
        with p.open(newline="") as f:
            for r in csv.DictReader(f):
                out[(r["settlement_date"], int(r["settlement_period"]))] = r
    return out


def _num(v):
    return None if v in ("", None) else int(v)


def _recompute(fh, eb):
    mix = {c: (_num(fh.get(c)) or 0) for c in _MIX}
    v = compute_verdict(mix, {"solar_mw": _num(eb["embedded_solar_mw"]) or 0,
                              "wind_mw": _num(eb["embedded_wind_mw"]) or 0, "time": "x"})
    demand = v["national_demand_mw"]
    if demand <= 0:
        return None
    r = round(v["firm_mw"] / demand, 4)
    return round(max(0.0, min(1.0, 1 - r)), 4)


def test_carpet_matches_independent_recompute():
    payload = json.loads(CARPET.read_text())
    fuel, emb = _rows("fuelhh_*.csv"), _rows("embedded_*.csv")
    by_date = {d["date"]: d["cf"] for d in payload["days"]}
    # Check a spread of days fully (first, middle, last present in the store).
    dates = sorted(by_date)
    checked = 0
    for date in (dates[0], dates[len(dates) // 2], dates[-1]):
        for sp in range(1, 49):
            fh, eb = fuel.get((date, sp)), emb.get((date, sp))
            if fh is None or eb is None:
                continue
            assert by_date[date][sp - 1] == _recompute(fh, eb), f"{date} SP{sp}"
            checked += 1
    assert checked > 50, f"too few cells checked ({checked})"
