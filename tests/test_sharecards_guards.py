"""Share-card build guards.

load_cards / build must FAIL LOUDLY on missing or out-of-range source data,
never silently render a wrong card (the cards are screenshotted, so a bad
figure becomes a shared image).
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
    wu = {"generated_utc": "2026-06-25T21:39:53.7+00:00",
          "lulls": [
              {"start": "2025-10-12", "end": "2025-10-14", "days": 3, "min_cf": 0.0393},
          ],
          "summary": {
              "counts": {"ge_1d": 1, "ge_3d": 1, "ge_7d": 0, "ge_14d": 0},
              "record_lull": {"start": "2016-06-03", "end": "2016-06-19", "days": 17,
                              "min_cf": 0.05, "min_cf_date": "2016-06-10", "severe": False},
              "lowest_day": {"date": "2016-01-19", "cf": 0.0087},
              "worst_lull_by_year": {},
              "mean_cf": 0.2231,
              "below_10pct_days": 13,
              "below_5pct_days": 1,
          }}
    blobs = {"latest.json": overrides.get("latest", latest),
             "wind_unreliability.json": overrides.get("wu", wu)}
    for name, blob in blobs.items():
        (d / name).write_text(json.dumps(blob))
    return d


# --- guards: load_cards fails loudly on bad data ----------------------------

def test_load_cards_passes_on_good_data(tmp_path):
    cards, asof = sharecards.load_cards(_write_data(tmp_path))
    assert {c["slug"] for c in cards} == {"live-balance", "recent-lull"}


def test_load_cards_trips_on_firm_pct_out_of_range(tmp_path):
    bad = {"verdict": {"snapshot": "2026-06-25T23:35:00Z", "firm_pct": 180.0,
                       "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}
    with pytest.raises(GuardError, match="firm"):
        sharecards.load_cards(_write_data(tmp_path, latest=bad))


def test_load_cards_trips_cleanly_on_corrupt_snapshot(tmp_path):
    bad = {"verdict": {"snapshot": "not-a-date", "firm_pct": 74.7,
                       "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}
    with pytest.raises(GuardError, match="snapshot"):
        sharecards.load_cards(_write_data(tmp_path, latest=bad))


def test_load_cards_trips_when_no_lull_has_days_ge_3(tmp_path):
    bad_wu = {"generated_utc": "2026-06-25T21:39:53.7+00:00",
              "lulls": [
                  {"start": "2025-10-12", "end": "2025-10-13", "days": 2, "min_cf": 0.05},
              ],
              "summary": {
                  "counts": {"ge_1d": 1, "ge_3d": 0, "ge_7d": 0, "ge_14d": 0},
                  "record_lull": None, "lowest_day": None, "worst_lull_by_year": {},
                  "mean_cf": 0.2, "below_10pct_days": 0, "below_5pct_days": 0,
              }}
    with pytest.raises(GuardError):
        sharecards.load_cards(_write_data(tmp_path, wu=bad_wu))


def test_build_returns_1_cleanly_on_corrupt_snapshot(tmp_path, capsys):
    bad = {"verdict": {"snapshot": "not-a-date", "firm_pct": 74.7,
                       "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}
    rc = sharecards.build(data_dir=_write_data(tmp_path, latest=bad),
                          site_dir=tmp_path / "site")
    assert rc == 1
    assert "card build failed" in capsys.readouterr().err.lower()


def test_build_fails_loudly_when_a_source_file_is_missing(tmp_path, capsys):
    d = _write_data(tmp_path)
    (d / "wind_unreliability.json").unlink()  # corrupt the inputs
    rc = sharecards.build(data_dir=d, site_dir=tmp_path / "site")
    assert rc == 1
    err = capsys.readouterr().err
    assert "card build failed" in err.lower() or "wind_unreliability" in err.lower()


# --- warning card provenance: stamps carry real timestamps -------------------

def test_warning_card_stamp_carries_issued_at_when_in_force():
    c = sharecards.warning_card({"in_force": True, "type": "EMN",
        "type_label": "Electricity Margin Notice",
        "issued_at": "2026-06-24T15:30:00Z", "window": None})
    assert "Elexon SYSWARN" in c["stamp"]
    assert "24 Jun" in c["stamp"]  # issued-at threaded into the stamp


def test_warning_card_clear_stamp_needs_no_issued_at():
    c = sharecards.warning_card({"in_force": False})
    assert "Elexon SYSWARN" in c["stamp"]
