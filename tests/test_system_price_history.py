from datetime import date

from engine import history, system_price_history as sph


def test_parse_day_keeps_priced_periods_only():
    payload = {"data": [
        {"settlementDate": "2026-06-23", "settlementPeriod": 42, "systemSellPrice": 800.0},
        {"settlementDate": "2026-06-23", "settlementPeriod": 43, "systemSellPrice": None},
    ]}
    assert sph.parse_day(payload) == [
        {"settlement_date": "2026-06-23", "settlement_period": 42, "system_sell_price": 800.0},
    ]


def test_reappend_is_idempotent_noop(tmp_path):
    """Re-appending identical rows must not raise (default raise policy) and must
    write nothing the second time — the CSV round-trip (DictWriter/DictReader) is
    text, so the in-memory price must match its stored string form."""
    payload = {"data": [
        {"settlementDate": "2026-06-23", "settlementPeriod": 42, "systemSellPrice": 800.0},
        {"settlementDate": "2026-06-23", "settlementPeriod": 43, "systemSellPrice": -12.5},
        {"settlementDate": "2026-06-23", "settlementPeriod": 44, "systemSellPrice": 49.99},
    ]}
    rows = sph.parse_day(payload)

    first = sph.append_rows(rows, base_dir=tmp_path)
    assert first == 3

    # Re-appending the SAME rows under the default "raise" policy must be a clean no-op.
    second = sph.append_rows(rows, base_dir=tmp_path)
    assert second == 0

    # read_store still returns floats (text on disk, float on read).
    stored = sph.read_store(base_dir=tmp_path)
    assert [r["system_sell_price"] for r in stored] == [800.0, -12.5, 49.99]


def test_known_gaps_gate_passes_documented_missing_day():
    """validate_range passes when an incomplete day matches the known_gaps manifest."""
    # Synthetic: 47 of 48 periods present for 2016-01-03 (mirrors the real store gap).
    rows = [{"settlement_date": "2016-01-03", "settlement_period": sp,
             "system_sell_price": 50.0} for sp in range(1, 48)]
    start = end = date(2016, 1, 3)
    known_gaps = {"2016-01-03": {"actual": 47, "expected": 48}}
    result = history.validate_range(rows, start, end, known_gaps=known_gaps)
    assert result["ok"] is True
    assert result["unexplained"] == []


def test_known_gaps_gate_fails_undocumented_missing_day():
    """validate_range fails when an incomplete day is NOT in the known_gaps manifest."""
    rows = [{"settlement_date": "2016-01-03", "settlement_period": sp,
             "system_sell_price": 50.0} for sp in range(1, 48)]
    start = end = date(2016, 1, 3)
    result = history.validate_range(rows, start, end, known_gaps={})
    assert result["ok"] is False
    assert len(result["unexplained"]) == 1
    assert result["unexplained"][0]["date"] == "2016-01-03"
