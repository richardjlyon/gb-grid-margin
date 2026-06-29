"""Conditional solar 'overcast' distribution — unit + guard tests."""

import pytest

from engine import solar_overcast as so
from engine.guards import GuardError


def _row(dt: str, sp: int, solar_mw: float, cap_mw: float = 100.0) -> dict:
    return {
        "settlement_date": dt, "settlement_period": sp,
        "embedded_solar_mw": solar_mw, "embedded_solar_capacity_mw": cap_mw,
    }


def test_week_index_boundaries():
    assert so.week_index("2024-01-01") == 0       # doy 1
    assert so.week_index("2024-01-07") == 0       # doy 7
    assert so.week_index("2024-01-08") == 1       # doy 8
    assert so.week_index("2024-12-31") == 51      # tail absorbed into the last week
    assert so.week_index("2024-07-01") == (183 - 1) // 7  # mid-year, leap doy 183


def test_daytime_cell_is_p25_and_p95_ceiling():
    # One cell (week 0, SP 24): CF 0.1..1.0 across years; window 0 so only this slot pools.
    rows = [_row(f"2016-01-0{(i % 7) + 1}", 24, cf * 100) for i, cf in
            enumerate([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])]
    grid = so.conditional_grid(rows, window_weeks=0, min_samples=1)
    cell = grid[0][23]
    # nearest-rank: p25 -> index int(.25*10)=2 -> 0.3 ; p95 -> int(.95*10)=9 -> 1.0
    assert cell == [0.3, 1.0]


def test_night_cell_is_null():
    rows = [_row(f"2016-01-0{(i % 7) + 1}", 1, 0.0) for i in range(10)]   # SP1 midnight, all dark
    grid = so.conditional_grid(rows, window_weeks=0, min_samples=1)
    assert grid[0][0] is None                     # ceiling 0 <= DAY_FLOOR -> null


def test_sparse_cell_is_null():
    rows = [_row("2016-01-01", 24, 50.0)]          # a single sample
    grid = so.conditional_grid(rows, window_weeks=0, min_samples=20)
    assert grid[0][23] is None


def test_zero_capacity_rows_skipped():
    rows = [_row(f"2016-01-0{(i % 7) + 1}", 24, 50.0, cap_mw=0) for i in range(10)]
    grid = so.conditional_grid(rows, window_weeks=0, min_samples=1)
    assert grid[0][23] is None                     # solar_cf None when capacity <= 0


def test_guard_passes_on_real_shaped_grid():
    # Fill every SP 20..30 across all weeks with a clear daytime distribution -> plenty of day cells.
    rows = []
    for w in range(52):
        d = f"2016-{((w * 7) // 31) + 1:02d}-{((w * 7) % 28) + 1:02d}"
        for sp in range(20, 31):
            for cf in (0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0, 1.0):
                rows.append(_row(d, sp, cf * 100))
    grid = so.conditional_grid(rows, window_weeks=0, min_samples=1)
    payload = so.build_payload(grid, "2026-06-29T00:00:00Z", len(rows))
    so.guard_payload(payload)                       # should not raise


def test_guard_rejects_unsorted_cell():
    payload = so.build_payload([[None] * so.PERIODS for _ in range(so.WEEKS)],
                               "2026-06-29T00:00:00Z", 0)
    payload["grid"][0][24] = [0.9, 0.2]             # p25 > ceiling
    # also needs > 200 day cells to reach the per-cell check; force the bad cell to be the failure
    with pytest.raises(GuardError):
        so.guard_payload({**payload, "grid": [[[0.9, 0.2]] * so.PERIODS for _ in range(so.WEEKS)]})


def test_guard_rejects_too_few_day_cells():
    payload = so.build_payload([[None] * so.PERIODS for _ in range(so.WEEKS)],
                               "2026-06-29T00:00:00Z", 0)
    with pytest.raises(GuardError):
        so.guard_payload(payload)                   # all-night grid -> 0 day cells
