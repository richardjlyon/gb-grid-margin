from __future__ import annotations

from engine import capacity
from engine.models import NameplateSeries


def _ns() -> NameplateSeries:
    return NameplateSeries.model_validate({
        "source": "test", "source_url": "x", "interpolation": "annual-step",
        "series": [{"year": 2025, "wind_onshore_gw": 16.0,
                    "wind_offshore_gw": 16.0, "solar_gw": 18.0}],
    })  # wind_gw 32 + solar 18 = 50 GW = 50_000 MW denominator


def _fh(period, wind, date="2025-06-01"):
    return {"settlement_date": date, "settlement_period": period,
            "period_start_utc": f"{date}T{(period-1)//2:02d}:{'30' if period%2==0 else '00'}:00Z",
            "WIND": wind}


def _emb(period, ew, es, date="2025-06-01"):
    return {"settlement_date": date, "settlement_period": period,
            "embedded_wind_mw": ew, "embedded_solar_mw": es}


def test_cf_for_period_full_basis():
    # 5000 transmission wind + 3000 embedded wind + 2000 embedded solar = 10_000 / 50_000 = 0.2
    cf = capacity.cf_for_period(_fh(1, 5000), _emb(1, 3000, 2000), _ns())
    assert abs(cf - 0.2) < 1e-9


def test_cf_for_period_blanks_coerce_to_zero():
    cf = capacity.cf_for_period(
        {"settlement_date": "2025-06-01", "settlement_period": 1, "WIND": None},
        {"settlement_date": "2025-06-01", "settlement_period": 1,
         "embedded_wind_mw": None, "embedded_solar_mw": None}, _ns())
    assert cf == 0.0


def test_build_cf_series_joins_and_sorts():
    fh = [_fh(2, 4000), _fh(1, 5000)]
    emb = [_emb(1, 0, 0), _emb(2, 0, 0)]
    s = capacity.build_cf_series(fh, emb, _ns())
    assert [r["cf"] for r in s] == [0.1, 0.08]   # period 1 then 2, time-sorted
    assert s[0]["t"] < s[1]["t"]


def test_build_cf_series_omits_unjoined_halfhours():
    s = capacity.build_cf_series([_fh(1, 5000)], [], _ns())  # no embedded match
    assert s == []


def test_load_duration_curve_descending_and_lengthed():
    series = [{"t": f"2025-06-01T00:00:00Z", "cf": c} for c in
              [0.4, 0.1, 0.3, 0.05, 0.2]]
    curve = capacity.load_duration_curve(series, points=5)
    assert len(curve) == 5
    assert curve == sorted(curve, reverse=True)      # non-increasing
    assert curve[0] == 40.0                            # max, as % of nameplate


def test_summary_stats_ordering_and_fracs():
    series = [{"t": "2025-06-01T00:00:00Z", "cf": c} for c in
              [0.05, 0.10, 0.20, 0.30, 0.60]]
    st = capacity.summary_stats(series)
    assert st["p25_pct"] <= st["median_pct"] <= st["p75_pct"]
    assert st["above_50pct_frac"] == 0.2             # only 0.60
    assert st["below_10pct_frac"] == 0.2             # only 0.05
    assert 0.0 <= st["below_5pct_frac"] <= 1.0
