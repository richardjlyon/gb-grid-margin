"""Generic wide-CSV store — column-parameterised append/idempotent/revision contract."""

from __future__ import annotations

import pytest

from engine import widestore

COLS = ["settlement_date", "settlement_period", "period_start_utc", "a_mw", "b_mw"]
TEXT = {"settlement_date", "period_start_utc"}


def _row(period, a, b, day="2016-06-01"):
    return {"settlement_date": day, "settlement_period": period,
            "period_start_utc": f"{day}T00:00:00Z", "a_mw": a, "b_mw": b}


def _path_for(base, day):
    return base / f"store_{day[:4]}.csv"


def test_append_read_roundtrips_none(tmp_path):
    pf = lambda d: _path_for(tmp_path, d)
    assert widestore.append_rows([_row(1, None, 0), _row(2, 1200, 3400)],
                                 COLS, TEXT, pf) == 2
    back = widestore.read_store(tmp_path, "store_*.csv", COLS, TEXT)
    assert len(back) == 2
    assert back[0]["a_mw"] is None and back[0]["b_mw"] == 0
    assert back[1]["a_mw"] == 1200


def test_idempotent_reappend_is_noop(tmp_path):
    pf = lambda d: _path_for(tmp_path, d)
    widestore.append_rows([_row(1, 100, 200)], COLS, TEXT, pf)
    assert widestore.append_rows([_row(1, 100, 200)], COLS, TEXT, pf) == 0


def test_revision_raises(tmp_path):
    pf = lambda d: _path_for(tmp_path, d)
    widestore.append_rows([_row(1, 100, 200)], COLS, TEXT, pf)
    with pytest.raises(ValueError, match="revision"):
        widestore.append_rows([_row(1, 999, 200)], COLS, TEXT, pf)
