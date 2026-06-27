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
    group_by_day,
    partial_years,
    transmission_shares,
    wind_cf_for_day,
)


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
