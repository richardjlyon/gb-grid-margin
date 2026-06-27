from __future__ import annotations

from engine import capacity
from engine.models import NameplateSeries


def _ns() -> NameplateSeries:
    return NameplateSeries.model_validate({
        "source": "test", "source_url": "x", "interpolation": "annual-step",
        "series": [{"year": 2025, "wind_onshore_gw": 16.0,
                    "wind_offshore_gw": 16.0, "solar_gw": 18.0}],
    })  # wind_gw 32 → 32_000 MW wind denominator


def _fh(period, wind, date="2025-06-01"):
    return {"settlement_date": date, "settlement_period": period, "WIND": wind}


def _emb(period, ew, es, scap, date="2025-06-01"):
    return {"settlement_date": date, "settlement_period": period,
            "embedded_wind_mw": ew, "embedded_solar_mw": es,
            "embedded_solar_capacity_mw": scap}


def test_wind_cf_full_basis():
    # (4000 transmission + 4000 embedded) / 32_000 = 0.25
    cf = capacity.wind_cf(_fh(1, 4000), _emb(1, 4000, 0, 12000), _ns())
    assert abs(cf - 0.25) < 1e-9


def test_wind_cf_blanks_coerce_zero():
    cf = capacity.wind_cf({"settlement_date": "2025-06-01", "settlement_period": 1, "WIND": None},
                          {"embedded_wind_mw": None}, _ns())
    assert cf == 0.0


def test_solar_cf_daytime_and_night():
    assert abs(capacity.solar_cf(_emb(20, 0, 6000, 12000)) - 0.5) < 1e-9   # midday
    assert capacity.solar_cf(_emb(1, 0, 0, 12000)) == 0.0                    # night = 0, NOT None
    assert capacity.solar_cf(_emb(1, 0, 100, 0)) is None                     # no capacity → None


def test_build_carpet_days_wind_grid_shape():
    fh = [_fh(1, 4000), _fh(2, 8000)]
    emb = [_emb(1, 4000, 0, 12000), _emb(2, 0, 0, 12000)]
    days = capacity.build_carpet_days(fh, emb, _ns(), "wind")
    assert len(days) == 1 and days[0]["date"] == "2025-06-01"
    assert len(days[0]["cf"]) == 48
    assert days[0]["cf"][0] == 0.25      # SP1
    assert days[0]["cf"][1] == 0.25      # SP2: 8000/32000
    assert days[0]["cf"][2] is None      # unfilled period


def test_build_carpet_days_solar_uses_embedded_capacity():
    fh = [_fh(20, 0)]
    emb = [_emb(20, 0, 6000, 12000)]
    days = capacity.build_carpet_days(fh, emb, _ns(), "solar")
    assert days[0]["cf"][19] == 0.5      # SP20 → slot 19


def test_build_carpet_days_omits_unjoined():
    assert capacity.build_carpet_days([_fh(1, 4000)], [], _ns(), "wind") == []


def test_rolling_days_keeps_last_365():
    days = [{"date": f"2025-{m:02d}-01", "cf": [None]*48} for m in range(1, 13)]
    days += [{"date": "2026-05-15", "cf": [None]*48}]
    kept = capacity.rolling_days(days, span_days=365)
    assert kept[-1]["date"] == "2026-05-15"
    assert all(d["date"] >= "2025-05-15" for d in kept)
