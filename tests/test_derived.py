"""Stage 5 — derived series from the settled history store.

The load-bearing tests here pin the methodology decisions (2026-06-25):
- YTD shares are a transmission-system mix (no embedded), distinct from the live
  national-demand verdict.
"""

from __future__ import annotations

from engine.derived import (
    group_by_day,
    partial_years,
    transmission_shares,
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
