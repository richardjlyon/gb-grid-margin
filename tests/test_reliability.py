"""Stage B — national reliable-share half-hourly series."""

from __future__ import annotations

import json

import pytest

from engine import derived, embedded_history
from engine.grid_engine import compute_verdict
from engine.reliability import (
    build_payload,
    build_series,
    pack,
    reliable_share,
    rolling_year,
)


def _fuelhh(**cols):
    base = {"settlement_date": "2024-06-01", "settlement_period": 24,
            "period_start_utc": "2024-06-01T10:30:00Z"}
    base.update(cols)
    return base


def _emb(wind=None, solar=None):
    return {"settlement_date": "2024-06-01", "settlement_period": 24,
            "period_start_utc": "2024-06-01T10:30:00Z",
            "embedded_wind_mw": wind, "embedded_solar_mw": solar}


def test_matches_compute_verdict_firm_share():
    row = _fuelhh(CCGT=12000, NUCLEAR=5000, BIOMASS=2000, NPSHYD=1000,
                  WIND=8000, INTFR=2000)
    emb = _emb(wind=1500, solar=3000)
    r = reliable_share(row, emb)
    # Independently: same mix/embedded through the live formula.
    mix = {"CCGT": 12000, "NUCLEAR": 5000, "BIOMASS": 2000, "NPSHYD": 1000,
           "WIND": 8000, "INTFR": 2000}
    v = compute_verdict(mix, {"solar_mw": 3000, "wind_mw": 1500, "time": "x"})
    assert r == round(v["firm_mw"] / v["national_demand_mw"], 4)


def test_none_columns_treated_as_zero():
    # Blank (None) fuel cells must not crash compute_verdict's `v > 0` checks.
    row = _fuelhh(CCGT=10000, OCGT=None, NUCLEAR=5000, WIND=None, COAL=None)
    r = reliable_share(row, _emb(wind=None, solar=None))
    assert 0.0 <= r <= 1.0


def test_zero_demand_is_none():
    row = _fuelhh()  # all fuel columns absent
    assert reliable_share(row, _emb()) is None


def test_net_export_half_hour_exceeds_one():
    # GB exporting heavily: firm generation > national demand → reliable_share > 1.0.
    # firm = CCGT + NUCLEAR + BIOMASS = 15000 + 5000 + 2000 = 22000
    # notfirm = (WIND_trans + emb_wind) + solar + net_imports
    #         = (3000 + 500) + 0 + (-10000) = -6500
    # demand  = 22000 + (-6500) = 15500  → share = 22000/15500 ≈ 1.419
    row = _fuelhh(CCGT=15000, NUCLEAR=5000, BIOMASS=2000, WIND=3000, INTFR=-10000)
    emb = _emb(wind=500, solar=0)
    r = reliable_share(row, emb)
    # Independent cross-check via compute_verdict.
    mix = {"CCGT": 15000, "NUCLEAR": 5000, "BIOMASS": 2000, "WIND": 3000, "INTFR": -10000}
    v = compute_verdict(mix, {"solar_mw": 0, "wind_mw": 500, "time": "x"})
    assert r == round(v["firm_mw"] / v["national_demand_mw"], 4)
    assert r > 1.0


def _fh(period, ccgt, wind, day="2024-06-01"):
    return {"settlement_date": day, "settlement_period": period,
            "period_start_utc": f"{day}T{(period-1)//2:02d}:{'30' if period % 2 == 0 else '00'}:00Z",
            "CCGT": ccgt, "WIND": wind}


def _eb(period, wind, solar, day="2024-06-01"):
    return {"settlement_date": day, "settlement_period": period,
            "period_start_utc": "x", "embedded_wind_mw": wind, "embedded_solar_mw": solar}


def test_build_series_joins_on_date_period_and_sorts():
    fh = [_fh(2, 9000, 1000), _fh(1, 9000, 1000)]
    eb = [_eb(1, 100, 0), _eb(2, 100, 500)]
    s = build_series(fh, eb)
    assert [x["t"] for x in s] == ["2024-06-01T00:00:00Z", "2024-06-01T00:30:00Z"]
    assert all(0.0 <= x["r"] <= 1.0 for x in s)


def test_build_series_drops_unjoined_and_none_share():
    fh = [_fh(1, 9000, 1000), _fh(2, 9000, 1000)]
    eb = [_eb(1, 100, 0)]  # period 2 has no embedded row -> dropped
    s = build_series(fh, eb)
    assert [x["t"] for x in s] == ["2024-06-01T00:00:00Z"]


def test_build_series_drops_none_share():
    # A half-hour whose demand reconstructs to 0 → reliable_share returns None → dropped.
    zero_fh = {"settlement_date": "2024-06-01", "settlement_period": 1,
                "period_start_utc": "2024-06-01T00:00:00Z"}  # no fuel columns → demand=0
    zero_eb = {"settlement_date": "2024-06-01", "settlement_period": 1,
                "period_start_utc": "x", "embedded_wind_mw": None, "embedded_solar_mw": None}
    valid_fh = _fh(2, 9000, 1000)
    valid_eb = _eb(2, 100, 0)
    s = build_series([zero_fh, valid_fh], [zero_eb, valid_eb])
    assert len(s) == 1
    assert s[0]["t"] == "2024-06-01T00:30:00Z"


def test_pack_regular_grid_with_null_gap():
    # three slots 30 min apart, middle one missing -> null in the packed grid
    series = [{"t": "2024-06-01T00:00:00Z", "r": 0.7},
              {"t": "2024-06-01T01:00:00Z", "r": 0.6}]
    p = pack(series)
    assert p["start_utc"] == "2024-06-01T00:00:00Z"
    assert p["step_minutes"] == 30
    assert p["values"] == [0.7, None, 0.6]
    assert p["gap_count"] == 1
    assert p["range"] == {"from": "2024-06-01T00:00:00Z", "to": "2024-06-01T01:00:00Z"}


def test_pack_empty():
    assert pack([])["values"] == []


def test_rolling_year_keeps_last_365_days():
    series = [{"t": "2023-01-01T00:00:00Z", "r": 0.5},
              {"t": "2024-06-01T00:00:00Z", "r": 0.7},
              {"t": "2024-12-01T00:00:00Z", "r": 0.6}]
    kept = rolling_year(series)
    assert [x["t"] for x in kept] == ["2024-06-01T00:00:00Z", "2024-12-01T00:00:00Z"]


def test_build_payload_carries_provenance():
    packed = pack([{"t": "2024-06-01T00:00:00Z", "r": 0.7}])
    p = build_payload(packed, generated_utc="2026-06-26T00:00:00+00:00")
    assert p["values"] == [0.7]
    assert p["step_minutes"] == 30
    assert p["generated_utc"] == "2026-06-26T00:00:00+00:00"
    for key in ("basis", "source", "metric", "caveats"):
        assert p[key]
    assert any("estimate" in c.lower() for c in p["caveats"])  # not-metered disclosure


def test_derived_build_emits_reliability_when_embedded_present(tmp_path):
    # Uses the committed real stores via engine.history/embedded_history read_store.
    # If embedded store is present, build() must emit both reliability files with values.
    if not embedded_history.read_store():
        pytest.skip("embedded store not built in this checkout")
    rc = derived.build(out_dir=tmp_path)
    assert rc == 0
    for name in ("reliability_year", "reliability_all"):
        payload = json.loads((tmp_path / f"{name}.json").read_text())
        assert payload["step_minutes"] == 30
        assert payload["values"]              # non-empty
        assert payload["source"]
