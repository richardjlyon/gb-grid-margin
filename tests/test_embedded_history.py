"""Stage A embedded-history pipeline — period→UTC, parse, wide store, validation."""

from __future__ import annotations

from datetime import date

import pytest

from engine.embedded_history import COLUMNS, parse_records, period_start_utc, to_row
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
