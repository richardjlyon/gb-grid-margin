"""Stage A embedded-history pipeline — period→UTC, parse, wide store, validation."""

from __future__ import annotations

import pytest

from engine.embedded_history import (
    COLUMNS,
    append_rows,
    daily_solar_mwh,
    parse_records,
    period_start_utc,
    read_store,
    solar_crosscheck,
    to_row,
    year_path,
)
from engine.models import EmbeddedHistRow


def _rec(period, wind, solar, day="2016-06-01", wcap=5000, scap=9000):
    return {"SETTLEMENT_DATE": day, "SETTLEMENT_PERIOD": period,
            "EMBEDDED_WIND_GENERATION": wind, "EMBEDDED_SOLAR_GENERATION": solar,
            "EMBEDDED_WIND_CAPACITY": wcap, "EMBEDDED_SOLAR_CAPACITY": scap}


class TestToRow:
    def test_row_has_all_columns_and_rounds_mw(self):
        row = to_row(EmbeddedHistRow.model_validate(_rec(24, 1200.4, 3400.6)))
        assert set(row) == set(COLUMNS)
        assert row["embedded_wind_mw"] == 1200
        assert row["embedded_solar_mw"] == 3401
        assert row["period_start_utc"] == "2016-06-01T10:30:00Z"  # period 24, BST

    def test_none_stays_none(self):
        row = to_row(EmbeddedHistRow.model_validate(_rec(1, "", "0")))
        assert row["embedded_wind_mw"] is None
        assert row["embedded_solar_mw"] == 0


class TestParseRecords:
    def test_sorted_and_validated(self):
        rows = parse_records([_rec(2, 10, 20), _rec(1, 5, 6)])
        assert [r["settlement_period"] for r in rows] == [1, 2]

    def test_compound_key_sort_across_two_dates(self):
        # Records supplied out of order across two different settlement dates.
        raw = [_rec(2, 10, 20, day="2016-06-02"), _rec(1, 5, 6, day="2016-06-01")]
        rows = parse_records(raw)
        assert [(r["settlement_date"], r["settlement_period"]) for r in rows] == [
            ("2016-06-01", 1), ("2016-06-02", 2)
        ]


class TestPeriodStartUtc:
    def test_normal_day_period_1_is_local_midnight(self):
        # 2016-06-01 is BST (UTC+1): local 00:00 == 2016-05-31T23:00Z.
        assert period_start_utc("2016-06-01", 1) == "2016-05-31T23:00:00Z"

    def test_normal_day_period_2_is_30_min_later(self):
        assert period_start_utc("2016-06-01", 2) == "2016-05-31T23:30:00Z"

    def test_winter_day_period_1_is_utc_midnight(self):
        # 2016-01-01 is GMT (UTC+0): local 00:00 == 2016-01-01T00:00Z.
        assert period_start_utc("2016-01-01", 1) == "2016-01-01T00:00:00Z"

    def test_autumn_clock_back_period_6_crosses_the_fold(self):
        # 2016-10-30 autumn back (50 periods). Local midnight is BST (UTC+1) ->
        # 2016-10-29T23:00Z; period 6 starts 2.5h later in real time.
        assert period_start_utc("2016-10-30", 6) == "2016-10-30T01:30:00Z"


class TestStore:
    def test_year_path(self, tmp_path):
        assert year_path("2016-06-01", tmp_path).name == "embedded_2016.csv"

    def test_append_then_read_roundtrips_none(self, tmp_path):
        rows = parse_records([_rec(1, "", "0"), _rec(2, 1200, 3400)])
        assert append_rows(rows, tmp_path) == 2
        back = read_store(tmp_path)
        assert len(back) == 2
        assert back[0]["embedded_wind_mw"] is None
        assert back[0]["embedded_solar_mw"] == 0
        assert back[1]["embedded_wind_mw"] == 1200

    def test_idempotent_reappend_is_noop(self, tmp_path):
        rows = parse_records([_rec(1, 100, 200)])
        append_rows(rows, tmp_path)
        assert append_rows(rows, tmp_path) == 0

    def test_revision_raises(self, tmp_path):
        append_rows(parse_records([_rec(1, 100, 200)]), tmp_path)
        with pytest.raises(ValueError, match="revision"):
            append_rows(parse_records([_rec(1, 999, 200)]), tmp_path)

    def test_revision_update_tolerated(self, tmp_path):
        """NESO revises embedded estimates retrospectively; the daily append uses
        on_revision='update' so the overlap window converges instead of crashing."""
        append_rows(parse_records([_rec(1, 100, 200)]), tmp_path)
        n = append_rows(parse_records([_rec(1, 999, 200)]), tmp_path, on_revision="update")
        assert n == 1
        from engine.embedded_history import read_store
        assert read_store(tmp_path)[0]["embedded_wind_mw"] == 999


class TestSolarCrosscheck:
    def test_daily_solar_mwh_sums_half_hours(self, tmp_path):
        append_rows(parse_records([_rec(20, 0, 1000), _rec(21, 0, 3000)]), tmp_path)
        # (1000 + 3000) MW × 0.5 h = 2000 MWh
        assert daily_solar_mwh(read_store(tmp_path), "2016-06-01") == 2000.0

    def test_within_tolerance_ok(self):
        r = solar_crosscheck(1040.0, 1000.0, tol=0.10)  # +4%
        assert r["ok"] is True
        assert round(r["rel_diff"], 3) == 0.04

    def test_outside_tolerance_fails(self):
        assert solar_crosscheck(1300.0, 1000.0, tol=0.10)["ok"] is False  # +30%

    def test_zero_pvlive_is_vacuously_ok(self):
        assert solar_crosscheck(0.0, 0.0)["ok"] is True

    def test_exactly_at_tolerance_boundary_is_ok(self):
        # rel_diff == tol exactly: the <= boundary must pass (not fail).
        assert solar_crosscheck(1100.0, 1000.0, tol=0.10)["ok"] is True

    def test_daily_solar_mwh_skips_none(self, tmp_path):
        # One row with solar=None (blank), one with solar=2000 MW. Only the real row
        # contributes: 2000 MW × 0.5 h = 1000 MWh.
        rows = parse_records([_rec(1, 100, ""), _rec(2, 100, 2000)])
        append_rows(rows, tmp_path)
        assert daily_solar_mwh(read_store(tmp_path), "2016-06-01") == 1000.0
