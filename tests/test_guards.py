"""Stage 9 — the centralised build-time guard set.

These pin the loud-failure contract: a guard either passes silently or raises
GuardError with a message that names the figure and the breach. The build steps
(engine.derived.build, engine.sharecards.build) call these before writing any
public figure, so corrupt or implausible data fails the build instead of being
published. The legitimate exception is a NEGATIVE net-import share on an export
year — explicitly allowed (engine/NOTES.md §8) and asserted here.
"""

from __future__ import annotations

import math

import pytest

from engine.guards import (
    GuardError,
    check_cf_range,
    check_counts_monotonic,
    check_dates_sorted_unique,
    check_finite,
    check_nameplate_sane,
    check_shares_sum_100,
    require,
)


# --- require / check_finite -------------------------------------------------

def test_require_passes_silently_when_true():
    require(True, "should not raise")


def test_require_raises_guarderror_with_message():
    with pytest.raises(GuardError, match="bad thing happened"):
        require(False, "bad thing happened")


def test_check_finite_accepts_a_real_number():
    check_finite("share", 42.0)


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_check_finite_rejects_non_finite(bad):
    with pytest.raises(GuardError, match="share"):
        check_finite("share", bad)


# --- check_shares_sum_100 ---------------------------------------------------

def test_shares_sum_100_passes_on_exactly_100():
    check_shares_sum_100("ytd 2025", {"wind": 30.0, "gas": 40.0, "other": 30.0})


def test_shares_sum_100_passes_within_rounding_tolerance():
    # six 2dp-rounded shares can drift a few hundredths from 100.
    check_shares_sum_100("ytd", {"a": 33.33, "b": 33.33, "c": 33.35})


def test_shares_sum_100_allows_negative_net_import_share():
    # An export year: net_imports is genuinely negative, the rest over-100, sum == 100.
    check_shares_sum_100(
        "ytd 2022",
        {"wind": 30.0, "gas": 45.0, "nuclear": 15.0, "biomass": 8.0,
         "other": 3.76, "net_imports": -1.76})


def test_shares_sum_100_fails_loudly_when_far_from_100():
    with pytest.raises(GuardError, match=r"ytd 2025.*sum"):
        check_shares_sum_100("ytd 2025", {"wind": 30.0, "gas": 40.0, "other": 10.0})


# --- check_counts_monotonic -------------------------------------------------

def test_counts_monotonic_passes_on_well_ordered_counts():
    check_counts_monotonic(2020, observed=366, below_10=40, below_5=12)


def test_counts_monotonic_passes_on_equality():
    check_counts_monotonic(2020, observed=10, below_10=10, below_5=10)


def test_counts_monotonic_fails_when_below5_exceeds_below10():
    with pytest.raises(GuardError, match="2020"):
        check_counts_monotonic(2020, observed=100, below_10=5, below_5=9)


def test_counts_monotonic_fails_when_below10_exceeds_observed():
    with pytest.raises(GuardError, match="2020"):
        check_counts_monotonic(2020, observed=100, below_10=120, below_5=10)


def test_counts_monotonic_fails_on_negative_count():
    with pytest.raises(GuardError):
        check_counts_monotonic(2020, observed=100, below_10=-1, below_5=0)


# --- check_cf_range ---------------------------------------------------------

@pytest.mark.parametrize("cf", [0.0, 0.001, 0.24, 1.0])
def test_cf_range_accepts_valid_capacity_factor(cf):
    check_cf_range("2016-01-01", cf)


@pytest.mark.parametrize("cf", [-0.01, 1.0001 + 0.05, 5.0])
def test_cf_range_rejects_out_of_range(cf):
    with pytest.raises(GuardError, match="2016-01-01"):
        check_cf_range("2016-01-01", cf)


# --- check_dates_sorted_unique ----------------------------------------------

def test_dates_sorted_unique_passes_on_ascending_unique():
    check_dates_sorted_unique(["2016-01-01", "2016-01-02", "2016-01-03"])


def test_dates_sorted_unique_fails_on_duplicate():
    with pytest.raises(GuardError, match="duplicate"):
        check_dates_sorted_unique(["2016-01-01", "2016-01-01"])


def test_dates_sorted_unique_fails_on_unsorted():
    with pytest.raises(GuardError, match="ascending|order"):
        check_dates_sorted_unique(["2016-01-02", "2016-01-01"])


# --- check_nameplate_sane ---------------------------------------------------

def _good_nameplate() -> dict:
    return {"wind_gw": 32.082, "solar_gw": 18.28, "wind_plus_solar_gw": 50.362,
            "wind_onshore_gw": 16.166, "wind_offshore_gw": 15.916}


def test_nameplate_sane_passes_on_real_dukes_figures():
    check_nameplate_sane(_good_nameplate())


def test_nameplate_sane_fails_on_non_positive_wind():
    bad = _good_nameplate() | {"wind_gw": 0.0}
    with pytest.raises(GuardError, match="wind"):
        check_nameplate_sane(bad)


def test_nameplate_sane_fails_when_total_does_not_reconcile():
    bad = _good_nameplate() | {"wind_plus_solar_gw": 99.0}
    with pytest.raises(GuardError, match="reconcile|wind_plus_solar"):
        check_nameplate_sane(bad)


def test_nameplate_sane_fails_on_absurdly_large_capacity():
    # A wrong-unit feed (MW pasted as GW) must trip, not publish.
    bad = _good_nameplate() | {"wind_gw": 32082.0, "wind_plus_solar_gw": 32100.28,
                               "solar_gw": 18.28}
    with pytest.raises(GuardError):
        check_nameplate_sane(bad)
