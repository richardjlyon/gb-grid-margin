from engine import wind_live_run as wlr


def _rows(daily_mw):
    """daily_mw: {date: mean_MW}. Emit 2 half-hours/day at that MW so mean == mean_MW."""
    out = []
    for date, mw in daily_mw.items():
        for sp in (1, 2):
            out.append({"settlement_date": date, "settlement_period": sp, "WIND": mw})
    return out


def test_daily_cf_series_uses_dukes_denominator():
    # 6416.4 MW mean / 32082 MW nameplate * 100 = 20.0%
    s = wlr.daily_transmission_cf_series(_rows({"2026-06-20": 6416.4}), 32082.0)
    assert s == [{"date": "2026-06-20", "cf_pct": 20.0}]


def test_daily_cf_skips_blank_halfhours():
    rows = [{"settlement_date": "2026-06-20", "settlement_period": 1, "WIND": 3208.2},
            {"settlement_date": "2026-06-20", "settlement_period": 2, "WIND": None}]
    s = wlr.daily_transmission_cf_series(rows, 32082.0)
    assert s == [{"date": "2026-06-20", "cf_pct": 10.0}]  # mean of the one populated half-hour


def test_current_run_counts_trailing_low_days():
    series = [{"date": "2026-06-18", "cf_pct": 30.0},   # windy — breaks any earlier run
              {"date": "2026-06-19", "cf_pct": 15.0},
              {"date": "2026-06-20", "cf_pct": 12.0},
              {"date": "2026-06-21", "cf_pct": 18.0}]   # last day, < 20 → run of 3
    r = wlr.current_run(series, 20)
    assert r == {"as_of": "2026-06-21", "current_run_days": 3, "current_cf_pct": 18.0}


def test_current_run_zero_when_last_day_windy():
    series = [{"date": "2026-06-20", "cf_pct": 12.0},
              {"date": "2026-06-21", "cf_pct": 22.0}]   # last day ≥ 20 → run 0
    assert wlr.current_run(series, 20)["current_run_days"] == 0


def test_current_run_breaks_on_calendar_gap():
    # a missing 06-20 means 06-19 and 06-21 are not adjacent → run is only the last day
    series = [{"date": "2026-06-19", "cf_pct": 10.0},
              {"date": "2026-06-21", "cf_pct": 10.0}]
    assert wlr.current_run(series, 20)["current_run_days"] == 1


def test_build_payload_shape():
    p = wlr.build_payload(_rows({"2026-06-20": 4810.0, "2026-06-21": 3208.2}),
                          32082.0, "2026-06-24T06:00:00+00:00")
    assert p["threshold_pct"] == 20
    assert p["as_of"] == "2026-06-21"
    assert p["current_run_days"] == 2           # 20.0% then 10.0%, both < 20, adjacent
    assert p["current_cf_pct"] == 10.0
    assert p["recent"][-1] == {"date": "2026-06-21", "cf_pct": 10.0}
    assert "transmission" in p["basis"].lower()
    assert p["generated_utc"] == "2026-06-24T06:00:00+00:00"
