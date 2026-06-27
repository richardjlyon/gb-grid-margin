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


import pytest
from engine.guards import GuardError


def _good_payload():
    series = [{"t": "2025-06-01T00:00:00Z", "cf": c}
              for c in [0.6, 0.3, 0.2, 0.1, 0.05]]
    curve = capacity.load_duration_curve(series, points=capacity.CURVE_POINTS)
    stats = capacity.summary_stats(series)
    return capacity.build_payload(curve, stats, series, "2026-06-26T00:00:00+00:00", _ns())


def test_build_payload_shape():
    p = _good_payload()
    assert p["window"] == "rolling_365d"
    assert len(p["curve"]) == capacity.CURVE_POINTS
    assert p["n_periods"] == 5
    assert p["nameplate_gw"]["total"] == 50.0
    assert "forecast" in p["seam_note"].lower()
    capacity.guard_payload(p)                       # the good payload passes its guard


def test_guard_rejects_increasing_curve():
    p = _good_payload()
    p["curve"] = list(reversed(p["curve"]))         # now ascending → not a valid LDC
    with pytest.raises(GuardError, match="non-increasing"):
        capacity.guard_payload(p)


def test_guard_rejects_stat_out_of_order():
    p = _good_payload()
    p["stats"]["median_pct"] = p["stats"]["p75_pct"] + 5
    with pytest.raises(GuardError, match="order"):
        capacity.guard_payload(p)


def test_guard_rejects_frac_above_one():
    p = _good_payload()
    p["stats"]["below_10pct_frac"] = 1.5
    with pytest.raises(GuardError, match="below_10pct_frac"):
        capacity.guard_payload(p)
