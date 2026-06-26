"""Stage 9 — derived.build() must FAIL LOUDLY on bad data and write nothing.

The Stage 9 validation gate: inject bad data → the build fails with a clear
message and leaves the published site/data/*.json untouched. guard_outputs is
the centralised check; build() catches a GuardError, reports it, and returns 1
before the atomic write loop runs.
"""

from __future__ import annotations

import pytest

from engine import derived
from engine.guards import GuardError


def _stripe(days):
    return {"days": days}


def _counters(years):
    return {"years": years}


def _ytd(years):
    return {"years": years}


def _good_nameplate():
    return {"wind_gw": 32.082, "solar_gw": 18.28, "wind_plus_solar_gw": 50.362,
            "wind_onshore_gw": 16.166, "wind_offshore_gw": 15.916}


def _records():
    return {"lowest_cf_day": {"date": "2016-01-01", "cf": 0.02},
            "highest_cf_day": {"date": "2016-06-01", "cf": 0.6},
            "longest_sub10pct_run": {"start": "2016-01-01", "end": "2016-01-10",
                                     "days": 10}}


def _good_args():
    return (
        _stripe([{"date": "2016-01-01", "cf": 0.1}, {"date": "2016-01-02", "cf": 0.2}]),
        _counters({"2016": {"days_observed": 2, "below_10pct": 1, "below_5pct": 0}}),
        _records(),
        _ytd({"2016": {"shares_pct": {"wind": 30.0, "gas": 70.0}}}),
        _good_nameplate(),
    )


def test_guard_outputs_passes_on_good_data():
    derived.guard_outputs(*_good_args())


def test_guard_outputs_trips_on_cf_above_one():
    stripe, counters, recs, ytd, nameplate = _good_args()
    stripe["days"][1]["cf"] = 1.4  # wrong-unit / doubled wind feed
    with pytest.raises(GuardError, match="2016-01-02"):
        derived.guard_outputs(stripe, counters, recs, ytd, nameplate)


def test_guard_outputs_trips_on_shares_not_summing_100():
    stripe, counters, recs, ytd, nameplate = _good_args()
    ytd["years"]["2016"]["shares_pct"] = {"wind": 30.0, "gas": 40.0}  # sums to 70
    with pytest.raises(GuardError, match="sum"):
        derived.guard_outputs(stripe, counters, recs, ytd, nameplate)


def test_guard_outputs_trips_on_broken_counter_monotonicity():
    stripe, counters, recs, ytd, nameplate = _good_args()
    counters["years"]["2016"]["below_5pct"] = 2  # exceeds below_10pct (1)
    with pytest.raises(GuardError, match="2016"):
        derived.guard_outputs(stripe, counters, recs, ytd, nameplate)


def test_guard_outputs_trips_on_unsorted_dates():
    stripe, counters, recs, ytd, nameplate = _good_args()
    stripe["days"] = [{"date": "2016-01-02", "cf": 0.2}, {"date": "2016-01-01", "cf": 0.1}]
    with pytest.raises(GuardError, match="ascending|order"):
        derived.guard_outputs(stripe, counters, recs, ytd, nameplate)


def test_guard_outputs_trips_on_insane_nameplate():
    stripe, counters, recs, ytd, nameplate = _good_args()
    nameplate["wind_gw"] = 0.0
    with pytest.raises(GuardError):
        derived.guard_outputs(stripe, counters, recs, ytd, nameplate)


def test_build_fails_loudly_and_writes_nothing_on_bad_store(tmp_path, monkeypatch, capsys):
    """A store whose WIND dwarfs nameplate yields cf >> 1 → build must abort, write nothing."""
    bad_day = [{"settlement_date": "2016-01-01", "settlement_period": p,
                "period_start_utc": "2016-01-01T00:00:00Z", "WIND": 9_000_000}
               for p in range(1, 49)]
    monkeypatch.setattr(derived, "read_store", lambda: bad_day)

    rc = derived.build(out_dir=tmp_path)

    assert rc == 1
    assert list(tmp_path.glob("*.json")) == []  # nothing published
    err = capsys.readouterr().err
    assert "GuardError" in err or "cf" in err
