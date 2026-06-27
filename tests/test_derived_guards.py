"""Tests for derived build-time guards (ytd shares + nameplate).

Task 14 removed guard_outputs() wholesale. These tests verify the targeted guard
block added back in build(): ytd shares must sum to ~100% per year, and the DUKES
nameplate anchor must self-reconcile before anything is written to site/data/.
"""

from __future__ import annotations

import json

import pytest

from engine import derived

# A minimal single-row store — only settlement_date is needed by build() before the
# guard fires (transmission_shares is monkeypatched in both tests).
_MIN_ROW = {
    "settlement_date": "2026-01-01",
    "settlement_period": 1,
    "period_start_utc": "2026-01-01T00:00:00Z",
}

# Good shares: sum to exactly 100.
_GOOD_SHARES = {"wind": 30.0, "gas": 40.0, "nuclear": 20.0,
                "biomass": 5.0, "other": 3.0, "net_imports": 2.0}


def _good_ts(rows, year):
    return {"shares_pct": _GOOD_SHARES, "supply_mwh": 1_000_000.0}


def test_build_returns_1_on_ytd_shares_not_summing_100(monkeypatch, tmp_path, capsys):
    """Guard fires when ytd shares don't sum to 100 — build aborts, nothing written."""
    monkeypatch.setattr(derived, "read_store", lambda: [_MIN_ROW])
    # Return shares that sum to 70, not 100.
    monkeypatch.setattr(derived, "transmission_shares",
                        lambda rows, year: {
                            "shares_pct": {"wind": 30.0, "gas": 40.0},
                            "supply_mwh": 1_000_000.0,
                        })
    monkeypatch.setattr(derived.embedded_history, "read_store", lambda: [])

    rc = derived.build(out_dir=tmp_path)

    assert rc == 1
    assert list(tmp_path.glob("*.json")) == []
    err = capsys.readouterr().err
    assert "GuardError" in err or "sum" in err


def test_build_returns_1_on_broken_nameplate_reconciliation(monkeypatch, tmp_path, capsys):
    """Guard fires when nameplate wind+solar doesn't reconcile — build aborts, nothing written."""
    monkeypatch.setattr(derived, "read_store", lambda: [_MIN_ROW])
    monkeypatch.setattr(derived, "transmission_shares", _good_ts)
    # wind(32.082) + solar(18.28) = 50.362, but wind_plus_solar_gw says 99.0 — corrupt.
    bad_nameplate = {
        "wind_gw": 32.082, "solar_gw": 18.28,
        "wind_plus_solar_gw": 99.0,
        "wind_onshore_gw": 16.166, "wind_offshore_gw": 15.916,
    }
    bad_np_path = tmp_path / "bad_nameplate.json"
    bad_np_path.write_text(json.dumps(bad_nameplate))
    monkeypatch.setattr(derived, "NAMEPLATE_ANCHOR_PATH", bad_np_path)
    monkeypatch.setattr(derived.embedded_history, "read_store", lambda: [])

    rc = derived.build(out_dir=tmp_path / "out")

    assert rc == 1
    err = capsys.readouterr().err
    assert "GuardError" in err or "reconcil" in err
