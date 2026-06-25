"""Stage 5 — derived series from the settled history store.

The load-bearing tests here pin the methodology decisions (2026-06-25):
- the wind capacity factor is a mean-power figure (mean MW / nameplate MW), so a
  short clock-change or a known-gap day is normalised, not penalised;
- the denominator is annual-step DUKES TOTAL wind nameplate — the CF is therefore a
  CONSERVATIVE LOWER BOUND (transmission-only numerator, total-capacity denominator);
- YTD shares are a transmission-system mix (no embedded), distinct from the live
  national-demand verdict.
"""

from __future__ import annotations

from engine.derived import (
    day_mean_mw,
    failure_counters,
    group_by_day,
    partial_years,
    records,
    transmission_shares,
    wind_cf_for_day,
    wind_cf_series,
)
from engine.models import NameplateSeries


# A small synthetic nameplate series so CF tests do not couple to exact DUKES cells.
def _ns() -> NameplateSeries:
    return NameplateSeries.model_validate({
        "source": "test", "source_url": "test", "interpolation": "annual-step",
        "series": [
            {"year": 2016, "wind_onshore_gw": 10.0, "wind_offshore_gw": 6.0, "solar_gw": 1.0},
            {"year": 2017, "wind_onshore_gw": 12.0, "wind_offshore_gw": 8.0, "solar_gw": 1.0},
        ],
    })


def _row(day, period, **series):
    """A store-format wide row: ints or None per series column."""
    row = {"settlement_date": day, "settlement_period": period,
           "period_start_utc": f"{day}T00:00:00Z"}
    row.update(series)
    return row


def _wind_day(day, mw, n_periods=48):
    """A day of `n_periods` rows, every one carrying WIND = mw."""
    return [_row(day, p, WIND=mw) for p in range(1, n_periods + 1)]


# --- day_mean_mw ------------------------------------------------------------

def test_day_mean_mw_averages_present_periods():
    rows = [_row("2024-01-01", 1, WIND=1000),
            _row("2024-01-01", 2, WIND=3000)]
    assert day_mean_mw(rows, "WIND") == 2000.0


def test_day_mean_mw_skips_blank_cells():
    rows = [_row("2024-01-01", 1, WIND=1000),
            _row("2024-01-01", 2, WIND=None),
            _row("2024-01-01", 3, WIND=2000)]
    # mean over the two present periods, not three.
    assert day_mean_mw(rows, "WIND") == 1500.0


# --- wind_cf_for_day (mean-power basis) -------------------------------------

def test_wind_cf_is_mean_power_over_total_nameplate():
    # 3200 MW mean against 16 GW total nameplate = 0.20.
    rows = _wind_day("2024-01-01", 3200)
    assert wind_cf_for_day(rows, capacity_gw=16.0) == 0.2


def test_wind_cf_short_day_not_penalised():
    # A 46-period clock-change day at the same mean MW yields the same CF as a full day —
    # mean-power normalises, an energy/24h basis would understate it.
    full = wind_cf_for_day(_wind_day("2024-03-31", 3200, n_periods=48), capacity_gw=16.0)
    short = wind_cf_for_day(_wind_day("2024-03-31", 3200, n_periods=46), capacity_gw=16.0)
    assert full == short == 0.2


# --- wind_cf_series (annual-step denominator) -------------------------------

def test_wind_cf_series_uses_annual_step_capacity():
    rows = _wind_day("2016-06-01", 3200) + _wind_day("2017-06-01", 4000)
    series = wind_cf_series(rows, _ns())
    by_date = {s["date"]: s for s in series}
    # 2016 total nameplate = 16 GW -> 3200/16000 = 0.20
    assert by_date["2016-06-01"]["cf"] == 0.2
    assert by_date["2016-06-01"]["capacity_gw"] == 16.0
    # 2017 total nameplate = 20 GW -> 4000/20000 = 0.20
    assert by_date["2017-06-01"]["cf"] == 0.2
    assert by_date["2017-06-01"]["capacity_gw"] == 20.0


def test_wind_cf_series_sorted_by_date():
    rows = _wind_day("2017-06-01", 4000) + _wind_day("2016-06-01", 3200)
    dates = [s["date"] for s in wind_cf_series(rows, _ns())]
    assert dates == sorted(dates)


# --- failure_counters -------------------------------------------------------

def test_failure_counters_thresholds_per_year():
    # Crafted CF values: two days <5% (also <10%), one day between 5% and 10%, one above.
    series = [
        {"date": "2016-01-01", "cf": 0.03, "capacity_gw": 16.0, "mean_mw": 480},
        {"date": "2016-01-02", "cf": 0.04, "capacity_gw": 16.0, "mean_mw": 640},
        {"date": "2016-01-03", "cf": 0.08, "capacity_gw": 16.0, "mean_mw": 1280},
        {"date": "2016-01-04", "cf": 0.50, "capacity_gw": 16.0, "mean_mw": 8000},
        {"date": "2017-01-01", "cf": 0.09, "capacity_gw": 20.0, "mean_mw": 1800},
    ]
    counters = failure_counters(series)
    assert counters[2016] == {"days_observed": 4, "below_10pct": 3, "below_5pct": 2}
    assert counters[2017] == {"days_observed": 1, "below_10pct": 1, "below_5pct": 0}


def test_failure_counters_threshold_is_strict_less_than():
    # Exactly 10% is NOT below 10%; exactly 5% is NOT below 5%.
    series = [
        {"date": "2016-01-01", "cf": 0.10, "capacity_gw": 16.0, "mean_mw": 1600},
        {"date": "2016-01-02", "cf": 0.05, "capacity_gw": 16.0, "mean_mw": 800},
    ]
    counters = failure_counters(series)
    assert counters[2016] == {"days_observed": 2, "below_10pct": 1, "below_5pct": 0}


# --- records ----------------------------------------------------------------

def test_records_lowest_highest_and_longest_run():
    series = [
        {"date": "2016-01-01", "cf": 0.40, "capacity_gw": 16.0, "mean_mw": 6400},
        {"date": "2016-01-02", "cf": 0.06, "capacity_gw": 16.0, "mean_mw": 960},
        {"date": "2016-01-03", "cf": 0.04, "capacity_gw": 16.0, "mean_mw": 640},
        {"date": "2016-01-04", "cf": 0.02, "capacity_gw": 16.0, "mean_mw": 320},
        {"date": "2016-01-05", "cf": 0.55, "capacity_gw": 16.0, "mean_mw": 8800},
        {"date": "2016-01-06", "cf": 0.07, "capacity_gw": 16.0, "mean_mw": 1120},
    ]
    rec = records(series)
    assert rec["lowest_cf_day"]["date"] == "2016-01-04"
    assert rec["lowest_cf_day"]["cf"] == 0.02
    assert rec["highest_cf_day"]["date"] == "2016-01-05"
    assert rec["highest_cf_day"]["cf"] == 0.55
    # Jan 2-4 is a 3-day consecutive run below 10%; Jan 6 is a separate 1-day run.
    assert rec["longest_sub10pct_run"] == {"start": "2016-01-02", "end": "2016-01-04", "days": 3}


def test_records_run_breaks_on_calendar_gap():
    # Two sub-10% days that are NOT calendar-adjacent are two runs of 1, not one of 2.
    series = [
        {"date": "2016-01-01", "cf": 0.03, "capacity_gw": 16.0, "mean_mw": 480},
        {"date": "2016-01-03", "cf": 0.03, "capacity_gw": 16.0, "mean_mw": 480},
    ]
    rec = records(series)
    assert rec["longest_sub10pct_run"]["days"] == 1


# --- transmission_shares (transmission-system basis, no embedded) -----------

def test_transmission_shares_sum_to_100_and_exclude_ps():
    # One period (period 1) carries the full mix; shares are over transmission supply.
    rows = [_row("2024-01-01", 1, WIND=5000, CCGT=6000, OCGT=0, NUCLEAR=3000,
                 BIOMASS=2000, NPSHYD=500, OTHER=500, PS=-800, OIL=0, COAL=0,
                 INTFR=1000, INTIRL=-300)]
    sh = transmission_shares(rows, 2024)
    # supply = wind5000 + gas6000 + nuclear3000 + biomass2000 + other(500+500) + netimports(700)
    #        = 17700 (PS pumping excluded entirely)
    assert sh["supply_mwh"] == 17700 * 0.5
    pct = sh["shares_pct"]
    assert abs(sum(pct.values()) - 100.0) < 1e-6
    assert round(pct["wind"], 4) == round(5000 / 17700 * 100, 4)
    assert round(pct["net_imports"], 4) == round(700 / 17700 * 100, 4)


def test_transmission_shares_skip_blank_cells():
    # A blank interconnector (None) contributes nothing, distinct from a present 0.
    rows = [_row("2024-01-01", 1, WIND=5000, CCGT=5000, NUCLEAR=0, BIOMASS=0,
                 INTFR=None, INTGRNL=2000)]
    sh = transmission_shares(rows, 2024)
    # supply = 5000 + 5000 + 2000 = 12000 (INTFR blank ignored)
    assert sh["supply_mwh"] == 12000 * 0.5


def test_transmission_shares_only_counts_requested_year():
    rows = (_wind_day("2024-01-01", 1000)
            + _wind_day("2025-01-01", 9999))
    sh = transmission_shares(rows, 2024)
    # Only 2024's wind energy, none of 2025's.
    assert sh["group_mwh"]["wind"] == 1000 * 0.5 * 48


# --- partial_years ----------------------------------------------------------

def test_partial_years_flags_incomplete_calendar_years():
    # 2016 spans the full calendar year; 2026 stops in June -> only 2026 is partial.
    dates = (["2016-01-01", "2016-06-15", "2016-12-31"]
             + ["2026-01-01", "2026-06-20"])
    assert partial_years(dates) == [2026]


def test_partial_years_flags_late_start():
    # A year whose earliest observed date is after 1 Jan is partial at the head.
    dates = ["2016-03-01", "2016-12-31"]
    assert partial_years(dates) == [2016]


def test_partial_years_empty_when_all_complete():
    dates = ["2016-01-01", "2016-12-31", "2017-01-01", "2017-12-31"]
    assert partial_years(dates) == []


# --- group_by_day -----------------------------------------------------------

def test_group_by_day_partitions_rows():
    rows = _wind_day("2024-01-01", 1000, n_periods=2) + _wind_day("2024-01-02", 1000, n_periods=3)
    by_day = group_by_day(rows)
    assert set(by_day) == {"2024-01-01", "2024-01-02"}
    assert len(by_day["2024-01-01"]) == 2
    assert len(by_day["2024-01-02"]) == 3
