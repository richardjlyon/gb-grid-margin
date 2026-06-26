"""Source-trace gate: reliability_all.json must match an independent raw-CSV recompute."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.grid_engine import compute_verdict
from engine.history import FUELS, INTERCONNECTORS

DATA = Path("data/history")
SERIES = Path("site/data/reliability_all.json")
_MIX = FUELS + INTERCONNECTORS

pytestmark = pytest.mark.skipif(
    not SERIES.exists() or not list(DATA.glob("embedded_*.csv")),
    reason="reliability_all.json or embedded store not present in this checkout",
)


def _rows(pattern):
    out = {}
    for p in sorted(DATA.glob(pattern)):
        with p.open(newline="") as f:
            for r in csv.DictReader(f):
                out[(r["settlement_date"], r["settlement_period"])] = r
    return out


def _num(v):
    return None if v in ("", None) else int(v)


def _slot_index(start_utc: str, t: str) -> int:
    f = "%Y-%m-%dT%H:%M:%SZ"
    a = datetime.strptime(start_utc, f).replace(tzinfo=timezone.utc)
    b = datetime.strptime(t, f).replace(tzinfo=timezone.utc)
    return int((b - a).total_seconds() // 1800)


def test_series_matches_independent_recompute():
    series = json.loads(SERIES.read_text())
    fuel = _rows("fuelhh_*.csv")
    emb = _rows("embedded_*.csv")
    start = series["start_utc"]
    values = series["values"]

    # Sample across the decade: every ~2000th joined half-hour.
    keys = sorted(set(fuel) & set(emb))
    checked = 0
    for k in keys[::2000]:
        fh, eb = fuel[k], emb[k]
        mix = {c: (_num(fh.get(c)) or 0) for c in _MIX}
        v = compute_verdict(mix, {"solar_mw": _num(eb["embedded_solar_mw"]) or 0,
                                  "wind_mw": _num(eb["embedded_wind_mw"]) or 0, "time": "x"})
        demand = v["national_demand_mw"]
        expected = None if demand <= 0 else round(v["firm_mw"] / demand, 4)
        if expected is None:
            continue
        i = _slot_index(start, fh["period_start_utc"])
        assert values[i] == expected, f"{k}: series {values[i]} != recompute {expected}"
        checked += 1
    assert checked > 50, f"too few sample points checked ({checked})"
