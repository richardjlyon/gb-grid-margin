"""Stage 9 — share-card build guards + provenance.

Two Stage 9 obligations for the cards:
1. load_cards / build must FAIL LOUDLY on missing or out-of-range source data,
   never silently render a wrong card (the cards are screenshotted, so a bad
   figure becomes a shared image).
2. Every card stamp carries a real timestamp: settled cards thread the source
   JSON's generated_utc (rebuilt date); the warning card threads issued_at.
"""

from __future__ import annotations

import json

import pytest

from engine import sharecards
from engine.guards import GuardError


def _write_data(tmp_path, **overrides):
    d = tmp_path / "data"
    d.mkdir()
    latest = {"verdict": {"snapshot": "2026-06-25T23:35:00Z", "firm_pct": 74.7,
                          "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}
    nameplate = {"wind_plus_solar_gw": 50.362}
    counters = {"latest_year": 2026, "partial_years": [2026],
                "generated_utc": "2026-06-25T21:39:53.7+00:00",
                "years": {"2026": {"days_observed": 171, "below_10pct": 13, "below_5pct": 1}}}
    records = {"generated_utc": "2026-06-25T21:39:53.7+00:00",
               "lowest_cf_day": {"date": "2016-01-19", "cf": 0.0087},
               "longest_sub10pct_run": {"start": "2016-06-03", "end": "2016-06-19", "days": 17}}
    stripe = {"mean_cf": 0.2231, "generated_utc": "2026-06-25T21:39:53.7+00:00",
              "days": [{"cf": 0.1}, {"cf": 0.3}]}
    blobs = {"latest.json": overrides.get("latest", latest),
             "nameplate.json": overrides.get("nameplate", nameplate),
             "counters.json": overrides.get("counters", counters),
             "records.json": overrides.get("records", records),
             "stripe.json": overrides.get("stripe", stripe)}
    for name, blob in blobs.items():
        (d / name).write_text(json.dumps(blob))
    return d


# --- guards: load_cards fails loudly on bad data ----------------------------

def test_load_cards_passes_on_good_data(tmp_path):
    cards, asof = sharecards.load_cards(_write_data(tmp_path))
    assert {c["slug"] for c in cards} >= {"firm-now", "capacity-trap"}


def test_load_cards_trips_on_firm_pct_out_of_range(tmp_path):
    bad = {"verdict": {"snapshot": "2026-06-25T23:35:00Z", "firm_pct": 180.0,
                       "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}
    with pytest.raises(GuardError, match="firm"):
        sharecards.load_cards(_write_data(tmp_path, latest=bad))


def test_load_cards_trips_on_zero_nameplate_capacity(tmp_path):
    with pytest.raises(GuardError):
        sharecards.load_cards(_write_data(tmp_path, nameplate={"wind_plus_solar_gw": 0.0}))


def test_load_cards_trips_on_negative_gas_mw(tmp_path):
    bad = {"verdict": {"snapshot": "2026-06-25T23:35:00Z", "firm_pct": 74.7,
                       "wind_mw": 11413, "solar_mw": 0, "gas_mw": -5}}
    with pytest.raises(GuardError):
        sharecards.load_cards(_write_data(tmp_path, latest=bad))


def test_load_cards_trips_on_broken_record_cf(tmp_path):
    bad = {"generated_utc": "2026-06-25T21:39:53.7+00:00",
           "lowest_cf_day": {"date": "2016-01-19", "cf": 9.9},
           "longest_sub10pct_run": {"start": "a", "end": "b", "days": 17}}
    with pytest.raises(GuardError, match="2016-01-19"):
        sharecards.load_cards(_write_data(tmp_path, records=bad))


def test_load_cards_trips_cleanly_on_null_lowest_cf_day(tmp_path):
    # records() emits lowest_cf_day=None for an empty store — must be a clean GuardError,
    # never a raw TypeError from dereferencing None.
    bad = {"generated_utc": "2026-06-25T21:39:53.7+00:00", "lowest_cf_day": None,
           "longest_sub10pct_run": {"start": None, "end": None, "days": 0}}
    with pytest.raises(GuardError, match="lowest_cf_day"):
        sharecards.load_cards(_write_data(tmp_path, records=bad))


def test_load_cards_trips_cleanly_on_corrupt_snapshot(tmp_path):
    bad = {"verdict": {"snapshot": "not-a-date", "firm_pct": 74.7,
                       "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}
    with pytest.raises(GuardError, match="snapshot"):
        sharecards.load_cards(_write_data(tmp_path, latest=bad))


def test_build_returns_1_cleanly_on_corrupt_snapshot(tmp_path, capsys):
    bad = {"verdict": {"snapshot": "not-a-date", "firm_pct": 74.7,
                       "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}
    rc = sharecards.build(data_dir=_write_data(tmp_path, latest=bad),
                          site_dir=tmp_path / "site")
    assert rc == 1
    assert "card build failed" in capsys.readouterr().err.lower()


def test_build_fails_loudly_when_a_source_file_is_missing(tmp_path, capsys):
    d = _write_data(tmp_path)
    (d / "stripe.json").unlink()  # corrupt the inputs
    rc = sharecards.build(data_dir=d, site_dir=tmp_path / "site")
    assert rc == 1
    err = capsys.readouterr().err
    assert "card build failed" in err.lower() or "stripe" in err.lower()


# --- provenance: stamps carry real timestamps -------------------------------

def test_settled_cards_thread_rebuilt_timestamp(tmp_path):
    cards, _ = sharecards.load_cards(_write_data(tmp_path))
    by = {c["slug"]: c for c in cards}
    # the rebuilt date is threaded from generated_utc into the settled stamps
    assert "25 Jun 2026" in by["wind-stripe"]["stamp"]
    assert "25 Jun 2026" in by["days-below-10"]["stamp"]
    assert "25 Jun 2026" in by["lowest-day"]["stamp"]
    assert "25 Jun 2026" in by["longest-calm"]["stamp"]


def test_settled_stamp_falls_back_gracefully_without_generated_utc(tmp_path):
    stripe = {"mean_cf": 0.2231, "days": [{"cf": 0.1}]}  # no generated_utc
    cards, _ = sharecards.load_cards(_write_data(tmp_path, stripe=stripe))
    by = {c["slug"]: c for c in cards}
    assert "Elexon FUELHH" in by["wind-stripe"]["stamp"]  # still has a source line


def test_warning_card_stamp_carries_issued_at_when_in_force():
    c = sharecards.warning_card({"in_force": True, "type": "EMN",
        "type_label": "Electricity Margin Notice",
        "issued_at": "2026-06-24T15:30:00Z", "window": None})
    assert "Elexon SYSWARN" in c["stamp"]
    assert "24 Jun" in c["stamp"]  # issued-at threaded into the stamp


def test_warning_card_clear_stamp_needs_no_issued_at():
    c = sharecards.warning_card({"in_force": False})
    assert "Elexon SYSWARN" in c["stamp"]
