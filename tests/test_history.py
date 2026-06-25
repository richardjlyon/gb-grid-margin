"""Stage 4 history pipeline — settlement-period arithmetic, wide store, validation gate.

The DST cases are the load-bearing tests: a settlement day is 48 half-hours except on
the two clock-change Sundays, when it is 46 (spring forward) or 50 (autumn back). Get
that wrong and the row-count gate false-alarms twice a year, or silently accepts a hole.
"""

from __future__ import annotations

from datetime import date

import pytest

from engine.history import (
    COLUMNS,
    append_rows,
    daily_mwh,
    expected_periods,
    expected_row_count,
    find_duplicates,
    incomplete_days,
    load_known_gaps,
    pivot_day,
    read_store,
    validate_range,
    year_path,
)
from engine.models import DemandHhRow, FuelHhRow


def _fuel(period, fuel, mw, day="2024-06-01", start="2024-06-01T00:00:00Z"):
    return FuelHhRow.model_validate(
        {"settlementDate": day, "settlementPeriod": period,
         "startTime": start, "fuelType": fuel, "generation": mw}
    )


def _demand(period, indo, itsdo, day="2024-06-01", start="2024-06-01T00:00:00Z"):
    return DemandHhRow.model_validate(
        {"settlementDate": day, "settlementPeriod": period, "startTime": start,
         "initialDemandOutturn": indo, "initialTransmissionSystemDemandOutturn": itsdo}
    )


class TestExpectedPeriods:
    def test_normal_day_is_48(self):
        assert expected_periods(date(2023, 6, 15)) == 48

    def test_spring_forward_day_is_46(self):
        # Last Sunday of March 2023: BST begins, 01:00 -> 02:00, the day loses an hour.
        assert expected_periods(date(2023, 3, 26)) == 46

    def test_autumn_back_day_is_50(self):
        # Last Sunday of October 2023: GMT returns, 02:00 -> 01:00, the day gains an hour.
        assert expected_periods(date(2023, 10, 29)) == 50

    def test_day_after_spring_change_is_48(self):
        assert expected_periods(date(2023, 3, 27)) == 48

    def test_day_after_autumn_change_is_48(self):
        assert expected_periods(date(2023, 10, 30)) == 48


class TestPivotDay:
    def test_builds_one_wide_row_per_period(self):
        fuels = [_fuel(1, "WIND", 5000), _fuel(1, "CCGT", 8000),
                 _fuel(2, "WIND", 5100), _fuel(2, "CCGT", 7900)]
        demand = [_demand(1, 28000, 30000), _demand(2, 27500, 29500)]
        rows = pivot_day(fuels, demand)
        assert [r["settlement_period"] for r in rows] == [1, 2]

    def test_maps_fuels_and_demand_into_columns(self):
        fuels = [_fuel(1, "WIND", 5000), _fuel(1, "CCGT", 8000)]
        demand = [_demand(1, 28000, 30000)]
        row = pivot_day(fuels, demand)[0]
        assert row["WIND"] == 5000
        assert row["CCGT"] == 8000
        assert row["INDO"] == 28000
        assert row["ITSDO"] == 30000
        assert row["period_start_utc"] == "2024-06-01T00:00:00Z"

    def test_absent_series_is_none_not_zero(self):
        # 2016-era day: no BIOMASS, no INTGRNL. Absent must be blank, distinct from 0.
        row = pivot_day([_fuel(1, "WIND", 5000)], [_demand(1, 28000, 30000)])[0]
        assert row["BIOMASS"] is None
        assert row["INTGRNL"] is None

    def test_keeps_signed_interconnector(self):
        row = pivot_day([_fuel(1, "INTEW", -528)], [_demand(1, 28000, 30000)])[0]
        assert row["INTEW"] == -528

    def test_rejects_unknown_fuel_type(self):
        # Fail loud on a roster change so a new fuel code can't silently vanish.
        with pytest.raises(ValueError, match="FUSION"):
            pivot_day([_fuel(1, "FUSION", 99)], [_demand(1, 28000, 30000)])

    def test_normalises_known_truncated_interconnector_alias(self):
        # 2021-09-10 SP22-30: ElecLink's first feed appearance used the truncated code
        # INTELE (generation 0). It is the same asset as INTELEC — normalise to the
        # canonical code; the (zero) value is unchanged. Fail-loud stays for novel codes.
        row = pivot_day([_fuel(1, "INTELE", 0)], [_demand(1, 28000, 30000)])[0]
        assert row["INTELEC"] == 0
        assert "INTELE" not in row

    def test_every_row_has_all_columns(self):
        row = pivot_day([_fuel(1, "WIND", 5000)], [_demand(1, 28000, 30000)])[0]
        assert set(row.keys()) == set(COLUMNS)


def _day(day, periods, base="2024-06-01T00:00:00Z"):
    fuels, demand = [], []
    for p in periods:
        fuels += [_fuel(p, "WIND", 5000 + p, day=day), _fuel(p, "CCGT", 8000 + p, day=day)]
        demand.append(_demand(p, 28000 + p, 30000 + p, day=day))
    return pivot_day(fuels, demand)


class TestStore:
    def test_year_path_partitions_by_settlement_date_year(self, tmp_path):
        assert year_path("2016-01-01", tmp_path).name == "fuelhh_2016.csv"
        assert year_path("2024-12-31", tmp_path).name == "fuelhh_2024.csv"

    def test_append_creates_file_and_round_trips(self, tmp_path):
        rows = _day("2024-06-01", [1, 2])
        append_rows(rows, tmp_path)
        back = read_store(tmp_path)
        assert len(back) == 2
        assert back[0]["WIND"] == 5001
        assert back[0]["ITSDO"] == 30001

    def test_absent_series_round_trips_as_none(self, tmp_path):
        append_rows(pivot_day([_fuel(1, "WIND", 5000, day="2016-01-01")],
                              [_demand(1, 28000, 30000, day="2016-01-01")]), tmp_path)
        back = read_store(tmp_path)
        assert back[0]["BIOMASS"] is None
        assert back[0]["WIND"] == 5000

    def test_append_is_idempotent(self, tmp_path):
        rows = _day("2024-06-01", [1, 2])
        append_rows(rows, tmp_path)
        append_rows(rows, tmp_path)  # re-run same day
        assert len(read_store(tmp_path)) == 2

    def test_append_adds_new_day(self, tmp_path):
        append_rows(_day("2024-06-01", [1, 2]), tmp_path)
        append_rows(_day("2024-06-02", [1, 2]), tmp_path)
        assert len(read_store(tmp_path)) == 4

    def test_rows_partition_into_year_files(self, tmp_path):
        append_rows(_day("2024-12-31", [1]), tmp_path)
        append_rows(_day("2025-01-01", [1]), tmp_path)
        assert (tmp_path / "fuelhh_2024.csv").exists()
        assert (tmp_path / "fuelhh_2025.csv").exists()

    def test_conflicting_revision_raises(self, tmp_path):
        append_rows(_day("2024-06-01", [1]), tmp_path)
        revised = _day("2024-06-01", [1])
        revised[0]["WIND"] = 9999  # same key, different settled value
        with pytest.raises(ValueError, match="revision"):
            append_rows(revised, tmp_path)


class TestExpectedRowCount:
    def test_plain_week_is_7x48(self):
        assert expected_row_count(date(2023, 6, 12), date(2023, 6, 18)) == 7 * 48

    def test_range_with_spring_day_loses_two(self):
        # Week containing the spring-forward Sunday (2023-03-26): six 48-period days + 46.
        assert expected_row_count(date(2023, 3, 20), date(2023, 3, 26)) == 6 * 48 + 46

    def test_range_with_autumn_day_gains_two(self):
        assert expected_row_count(date(2023, 10, 23), date(2023, 10, 29)) == 6 * 48 + 50

    def test_single_day_inclusive(self):
        assert expected_row_count(date(2024, 6, 1), date(2024, 6, 1)) == 48


def _full_day_rows(day):
    return _day(day, list(range(1, expected_periods(date.fromisoformat(day)) + 1)))


class TestGate:
    def test_clean_full_day_passes(self):
        rows = _full_day_rows("2024-06-01")
        report = validate_range(rows, date(2024, 6, 1), date(2024, 6, 1))
        assert report["ok"] is True
        assert report["expected_rows"] == 48
        assert report["actual_rows"] == 48

    def test_missing_half_hour_is_an_incomplete_day(self):
        rows = _day("2024-06-01", [p for p in range(1, 49) if p != 25])  # 47 of 48
        incs = incomplete_days(rows, date(2024, 6, 1), date(2024, 6, 1))
        assert incs == [{"date": "2024-06-01", "actual": 47, "expected": 48, "shortfall": 1}]

    def test_excess_period_is_flagged_as_wrong_count(self):
        rows = _day("2024-06-01", list(range(1, 50)))  # 49 of 48
        incs = incomplete_days(rows, date(2024, 6, 1), date(2024, 6, 1))
        assert incs[0]["actual"] == 49 and incs[0]["expected"] == 48

    def test_spring_day_with_48_periods_is_wrong_count(self):
        # 2023-03-26 must hold 46 half-hours; 48 rows is over-long.
        rows = _day("2023-03-26", list(range(1, 49)))
        incs = incomplete_days(rows, date(2023, 3, 26), date(2023, 3, 26))
        assert incs[0]["actual"] == 48 and incs[0]["expected"] == 46

    def test_noncontiguous_but_complete_day_passes(self):
        # Real Elexon quirk (2016-03-27): 46 half-hours numbered 1..45, 48 — complete,
        # just not contiguous. Count is right, so it must NOT be flagged.
        rows = _day("2023-03-26", list(range(1, 46)) + [48])  # 46 rows on a 46-period day
        assert incomplete_days(rows, date(2023, 3, 26), date(2023, 3, 26)) == []

    def test_fully_missing_day_is_incomplete(self):
        incs = incomplete_days([], date(2024, 6, 1), date(2024, 6, 1))
        assert incs == [{"date": "2024-06-01", "actual": 0, "expected": 48, "shortfall": 48}]

    def test_duplicate_key_detected(self):
        rows = _day("2024-06-01", [1, 2]) + _day("2024-06-01", [2])
        assert ("2024-06-01", 2) in find_duplicates(rows)


class TestKnownGaps:
    def test_recorded_gap_passes(self):
        rows = _day("2024-06-01", list(range(1, 48)))  # 47/48, a documented hole
        kg = {"2024-06-01": {"actual": 47, "expected": 48}}
        rep = validate_range(rows, date(2024, 6, 1), date(2024, 6, 1), known_gaps=kg)
        assert rep["ok"] is True
        assert rep["unexplained"] == []

    def test_unrecorded_gap_fails(self):
        rows = _day("2024-06-01", list(range(1, 48)))
        rep = validate_range(rows, date(2024, 6, 1), date(2024, 6, 1), known_gaps={})
        assert rep["ok"] is False
        assert rep["unexplained"][0]["date"] == "2024-06-01"

    def test_changed_known_gap_is_unexplained(self):
        # A recorded gap that has since changed (e.g. Elexon back-filled one half-hour)
        # no longer matches the frozen record and must resurface for review.
        rows = _day("2024-06-01", list(range(1, 47)))  # now 46/48, recorded as 47
        kg = {"2024-06-01": {"actual": 47, "expected": 48}}
        rep = validate_range(rows, date(2024, 6, 1), date(2024, 6, 1), known_gaps=kg)
        assert rep["ok"] is False

    def test_duplicates_fail_even_when_gaps_accounted(self):
        rows = _day("2024-06-01", list(range(1, 49))) + _day("2024-06-01", [2])
        rep = validate_range(rows, date(2024, 6, 1), date(2024, 6, 1),
                             known_gaps={"2024-06-01": {"actual": 49, "expected": 48}})
        assert rep["ok"] is False
        assert rep["duplicates"]

    def test_shipped_store_reconciles_with_manifest(self):
        # The committed store + known_gaps.csv must fully account for each other.
        from datetime import date as _d
        rows = read_store()
        kg = load_known_gaps()
        start = _d.fromisoformat(rows[0]["settlement_date"])
        end = _d.fromisoformat(rows[-1]["settlement_date"])
        rep = validate_range(rows, start, end, known_gaps=kg)
        assert rep["ok"] is True, f"unexplained: {rep['unexplained'][:5]}"


class TestSpotCheck:
    def test_mw_to_mwh_uses_half_hour_factor(self):
        # 48 periods of constant 1000 MW WIND = 48 * 1000 * 0.5 = 24000 MWh.
        rows = [{**r, "WIND": 1000} for r in _full_day_rows("2024-06-01")]
        assert daily_mwh(rows, "2024-06-01", "WIND") == 24000.0

    def test_daily_mwh_ignores_other_days(self):
        rows = ([{**r, "WIND": 1000} for r in _day("2024-06-01", [1, 2])]
                + [{**r, "WIND": 9999} for r in _day("2024-06-02", [1, 2])])
        assert daily_mwh(rows, "2024-06-01", "WIND") == (1000 + 1000) * 0.5
