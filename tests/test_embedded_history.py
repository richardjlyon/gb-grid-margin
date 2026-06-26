"""Stage A embedded-history pipeline — period→UTC, parse, wide store, validation."""

from __future__ import annotations

from datetime import date

import pytest

from engine.embedded_history import period_start_utc


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
