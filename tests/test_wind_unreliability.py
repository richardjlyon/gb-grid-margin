from engine.guards import GuardError
from engine.models import NameplateSeries
from engine import wind_unreliability as wu


def _ns():
    # 10 GW wind in every year used by these tests (annual-step series).
    return NameplateSeries.model_validate({
        "source": "test", "source_url": "test", "interpolation": "annual-step",
        "series": [
            {"year": y, "wind_onshore_gw": 5.0, "wind_offshore_gw": 5.0, "solar_gw": 1.0}
            for y in range(2016, 2027)
        ],
    })


def test_combined_daily_cf_means_transmission_plus_embedded_over_nameplate():
    # Two half-hours on one day: transmission WIND 500 & 700, embedded wind 100 & 300.
    # combined MW = 600, 1000 -> mean 800 MW; cap 10 GW -> cf 0.08.
    fuelhh = [
        {"settlement_date": "2020-06-01", "settlement_period": 1, "WIND": 500},
        {"settlement_date": "2020-06-01", "settlement_period": 2, "WIND": 700},
    ]
    embedded = [
        {"settlement_date": "2020-06-01", "settlement_period": 1, "embedded_wind_mw": 100},
        {"settlement_date": "2020-06-01", "settlement_period": 2, "embedded_wind_mw": 300},
    ]
    out = wu.combined_daily_cf_series(fuelhh, embedded, _ns())
    assert out == [{"date": "2020-06-01", "cf": 0.08, "mean_mw": 800.0, "capacity_gw": 10.0}]


def test_combined_daily_cf_omits_days_with_no_embedded_join():
    fuelhh = [{"settlement_date": "2020-06-02", "settlement_period": 1, "WIND": 500}]
    embedded = []  # no join for that half-hour
    assert wu.combined_daily_cf_series(fuelhh, embedded, _ns()) == []


def test_lull_episodes_groups_consecutive_sub10_days_with_severity():
    series = [
        {"date": "2020-01-01", "cf": 0.20},  # above -> no lull
        {"date": "2020-01-02", "cf": 0.08},  # lull A start
        {"date": "2020-01-03", "cf": 0.04},  # severe day
        {"date": "2020-01-04", "cf": 0.09},  # lull A end (3 days)
        {"date": "2020-01-05", "cf": 0.50},  # break
        {"date": "2020-01-06", "cf": 0.07},  # lull B (1 day, not severe)
    ]
    lulls = wu.lull_episodes(series)
    assert lulls == [
        {"start": "2020-01-02", "end": "2020-01-04", "days": 3,
         "min_cf": 0.04, "min_cf_date": "2020-01-03", "severe": True},
        {"start": "2020-01-06", "end": "2020-01-06", "days": 1,
         "min_cf": 0.07, "min_cf_date": "2020-01-06", "severe": False},
    ]


def test_lull_episodes_breaks_run_on_a_calendar_gap():
    # 0.08 then a missing day then 0.08 -> two separate 1-day lulls, not one 2-day run.
    series = [{"date": "2020-03-01", "cf": 0.08}, {"date": "2020-03-03", "cf": 0.08}]
    assert [l["days"] for l in wu.lull_episodes(series)] == [1, 1]


def test_carpet_matrix_places_days_by_month_day_with_nulls():
    series = [
        {"date": "2019-01-01", "cf": 0.30},
        {"date": "2019-12-31", "cf": 0.10},
        {"date": "2020-02-29", "cf": 0.05},  # leap day
    ]
    m = wu.carpet_matrix(series)
    assert m["years"] == [2019, 2020]
    assert len(m["doy"]) == 366 and m["doy"][0] == "01-01" and m["doy"][-1] == "12-31"
    i0101 = m["doy"].index("01-01")
    i1231 = m["doy"].index("12-31")
    i0229 = m["doy"].index("02-29")
    assert m["rows"]["2019"][i0101] == 0.30
    assert m["rows"]["2019"][i1231] == 0.10
    assert m["rows"]["2019"][i0229] is None     # 2019 had no 29 Feb
    assert m["rows"]["2020"][i0229] == 0.05
    assert m["rows"]["2020"][i0101] is None     # 2020-01-01 not in series


def test_summary_counts_and_record():
    series = [{"date": "2020-01-0%d" % d, "cf": 0.05} for d in range(1, 8)]  # 7-day lull
    lulls = wu.lull_episodes(series)
    s = wu.summary(series, lulls)
    assert s["counts"] == {"ge_1d": 1, "ge_3d": 1, "ge_7d": 1, "ge_14d": 0}
    assert s["record_lull"]["days"] == 7
    assert s["lowest_day"]["cf"] == 0.05
    assert s["worst_lull_by_year"] == {"2020": 7}


def test_build_payload_has_provenance_and_passes_guard():
    series = [{"date": "2020-01-01", "cf": 0.30, "mean_mw": 3000.0, "capacity_gw": 10.0}]
    p = wu.build_payload(series, "2026-06-27T00:00:00+00:00")
    assert p["basis"] and p["source"] and p["generated_utc"]
    assert "rows" in p["carpet"] and "lulls" in p and "summary" in p
    wu.guard_payload(p)  # must not raise


def test_guard_rejects_out_of_range_cf():
    series = [{"date": "2020-01-01", "cf": 0.30, "mean_mw": 3000.0, "capacity_gw": 10.0}]
    p = wu.build_payload(series, "2026-06-27T00:00:00+00:00")
    p["carpet"]["rows"]["2020"][0] = 9.9  # impossible CF
    try:
        wu.guard_payload(p)
        assert False, "expected GuardError"
    except GuardError:
        pass
