"""Stage B — national reliable-share half-hourly series."""

from __future__ import annotations

from engine.reliability import reliable_share
from engine.grid_engine import compute_verdict


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


from engine.reliability import build_series


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
