import pytest

from engine import import_cost as ic


def test_net_import_sums_INT_legs_case_insensitive_blanks_zero():
    row = {"INTFR": 1000, "intned": 500, "INTEW": -200, "WIND": 9999, "CCGT": 8000,
           "INTNED2": None, "intifa": ""}
    # None/blank INT legs must contribute 0 (would TypeError without the guard).
    assert ic.net_import_mw(row) == 1300  # 1000 + 500 - 200; non-INT ignored; None/"" -> 0

def test_daily_value_sums_positive_import_mwh_times_price():
    # SP1: 2000 MW @ £100 -> 2000*0.5*100 = £100,000 ; SP2: export -300 -> £0
    fuelhh = [
        {"settlement_date": "2026-06-23", "settlement_period": 1, "INTFR": 2000},
        {"settlement_date": "2026-06-23", "settlement_period": 2, "INTFR": -300},
    ]
    price = [
        {"settlement_date": "2026-06-23", "settlement_period": 1, "system_sell_price": 100.0},
        {"settlement_date": "2026-06-23", "settlement_period": 2, "system_sell_price": 800.0},
    ]
    out = ic.daily_import_value(fuelhh, price)
    assert out == [{"date": "2026-06-23", "value_gbp": 100000.0, "import_mwh": 1000.0, "mean_price": 100.0}]


# ── _doy_labels ────────────────────────────────────────────────────────────────

def test_doy_labels_366_entries_includes_leap_day():
    labels = ic._doy_labels()
    assert len(labels) == 366
    assert labels[0] == "01-01"
    assert "02-29" in labels
    assert labels[-1] == "12-31"


# ── carpet_matrix ──────────────────────────────────────────────────────────────

_DAILY = [
    {"date": "2024-02-29", "value_gbp": 500000.0, "import_mwh": 100.0, "mean_price": 100.0},
    {"date": "2025-01-10", "value_gbp": 3000000.0, "import_mwh": 500.0, "mean_price": 200.0},
    {"date": "2025-06-01", "value_gbp": 1000000.0, "import_mwh": 200.0, "mean_price": 150.0},
    {"date": "2026-06-23", "value_gbp": 8000000.0, "import_mwh": 1000.0, "mean_price": 300.0},
    {"date": "2026-03-15", "value_gbp": 2000000.0, "import_mwh": 300.0, "mean_price": 250.0},
]


def test_carpet_matrix_places_value_at_correct_doy_column():
    result = ic.carpet_matrix(_DAILY)
    doy = result["doy"]
    assert "06-23" in doy
    col_idx = doy.index("06-23")
    assert result["rows"]["2026"][col_idx] == 8000000.0


def test_carpet_matrix_leap_day_at_0229_column():
    result = ic.carpet_matrix(_DAILY)
    doy = result["doy"]
    assert "02-29" in doy, "doy must include a 29-Feb slot"
    col_idx = doy.index("02-29")
    assert result["rows"]["2024"][col_idx] == 500000.0


def test_carpet_matrix_missing_days_are_none():
    result = ic.carpet_matrix(_DAILY)
    doy = result["doy"]
    # 2025 has no entry on 2025-06-23; that slot must be None
    col_idx = doy.index("06-23")
    assert result["rows"]["2025"][col_idx] is None
    # 2025 is NOT a leap year, so its 02-29 slot must also stay None
    col_feb29 = doy.index("02-29")
    assert result["rows"]["2025"][col_feb29] is None


def test_carpet_matrix_years_sorted_and_complete():
    result = ic.carpet_matrix(_DAILY)
    assert result["years"] == [2024, 2025, 2026]
    assert len(result["doy"]) == 366
    assert all(len(v) == 366 for v in result["rows"].values())


# ── summary ────────────────────────────────────────────────────────────────────

def test_summary_worst_day_is_max_value():
    result = ic.summary(_DAILY)
    assert result["worst_day"] == {"date": "2026-06-23", "value_gbp": 8000000.0}


def test_summary_total_by_year_sums_per_year():
    result = ic.summary(_DAILY)
    tby = result["total_by_year"]
    assert tby["2024"] == 500000.0
    assert tby["2025"] == 4000000.0   # 3_000_000 + 1_000_000
    assert tby["2026"] == 10000000.0  # 8_000_000 + 2_000_000


def test_summary_year_to_date_is_latest_year_total():
    result = ic.summary(_DAILY)
    assert result["year_to_date"] == result["total_by_year"]["2026"]


# ── events ─────────────────────────────────────────────────────────────────────

def test_events_returns_costliest_days_descending():
    result = ic.events(_DAILY)
    values = [d["value_gbp"] for d in result]
    assert values == sorted(values, reverse=True)


def test_events_honours_top_n():
    result = ic.events(_DAILY, top_n=3)
    assert len(result) == 3
    # The top-3 costliest are 8m, 3m, 2m
    assert result[0]["value_gbp"] == 8000000.0
    assert result[1]["value_gbp"] == 3000000.0
    assert result[2]["value_gbp"] == 2000000.0


def test_events_default_top_n_is_8():
    # With only 5 rows, all 5 are returned when top_n=8
    result = ic.events(_DAILY)
    assert len(result) == len(_DAILY)


# ── scale ──────────────────────────────────────────────────────────────────────

def test_scale_returns_documented_cap_and_legend():
    result = ic.scale(_DAILY)
    assert result["cap_gbp"] == 10_000_000
    assert result["legend"] == [1_000_000, 5_000_000, 10_000_000]


# ── build_payload + guard_payload ──────────────────────────────────────────────

_FUELHH_MINI = [
    {"settlement_date": "2025-06-01", "settlement_period": 1, "INTFR": 1000},
]
_PRICE_MINI = [
    {"settlement_date": "2025-06-01", "settlement_period": 1, "system_sell_price": 200.0},
]
# 1000 MW × 0.5 h × £200 = £100,000
_EXPECTED_VALUE = 100_000.0


def test_build_payload_provenance_keys_present():
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    for key in ("basis", "source", "metric_label", "caveat", "generated_utc",
                "range", "partial_years", "scale", "carpet", "events", "summary", "cited"):
        assert key in payload, f"missing key: {key}"


def test_build_payload_exact_source_string():
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    assert payload["source"] == (
        "Elexon FUELHH net interconnector flow × Elexon system (cash-out) price, "
        "settled, back to 2016"
    )


def test_build_payload_exact_cited_dict():
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    assert payload["cited"] == {
        "label": "Montel EnAppSys, via the Guardian",
        "date": "2026-06-24",
        "value_per_mwh": 1379,
        "note": "emergency-import price; not reproducible from public data",
    }


def test_build_payload_exact_metric_label():
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    assert payload["metric_label"] == "net imported energy valued at the GB system price"


def test_build_payload_exact_caveat():
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    assert payload["caveat"] == (
        "Net imported energy valued at the GB system (cash-out) price — not the "
        "contractual cost of the imports, which clear in the day-ahead auction."
    )


def test_build_payload_worst_day_equals_expected_value():
    # The single fixture day is the worst day: 1000 MW × 0.5 h × £200 = £100,000
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    assert payload["summary"]["worst_day"]["value_gbp"] == _EXPECTED_VALUE


def test_build_payload_passes_guard():
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    ic.guard_payload(payload)  # must not raise


def test_guard_payload_raises_on_negative_carpet_cell():
    from engine.guards import GuardError
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    # Inject a negative value into a carpet cell (the load-bearing invariant)
    rows = payload["carpet"]["rows"]
    year_key = list(rows.keys())[0]
    # Find the first non-None cell and flip it negative
    for i, cell in enumerate(rows[year_key]):
        if cell is not None:
            rows[year_key][i] = -1.0
            break
    with pytest.raises(GuardError):
        ic.guard_payload(payload)


def test_guard_payload_raises_on_worst_day_not_max_cell():
    from engine.guards import GuardError
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    # Inflate worst_day so it no longer matches the carpet max
    payload["summary"]["worst_day"]["value_gbp"] += 999.0
    with pytest.raises(GuardError):
        ic.guard_payload(payload)


def test_guard_payload_raises_on_carpet_row_wrong_length():
    from engine.guards import GuardError
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    year_key = list(payload["carpet"]["rows"].keys())[0]
    payload["carpet"]["rows"][year_key].pop()  # remove one element → length 365
    with pytest.raises(GuardError):
        ic.guard_payload(payload)


def test_guard_payload_raises_on_empty_caveat():
    from engine.guards import GuardError
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    payload["caveat"] = ""
    with pytest.raises(GuardError):
        ic.guard_payload(payload)


def test_guard_payload_raises_on_empty_metric_label():
    from engine.guards import GuardError
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    payload["metric_label"] = ""
    with pytest.raises(GuardError):
        ic.guard_payload(payload)


def test_guard_payload_raises_on_nonpositive_cap_gbp():
    from engine.guards import GuardError
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    payload["scale"]["cap_gbp"] = 0
    with pytest.raises(GuardError):
        ic.guard_payload(payload)


def test_guard_payload_raises_on_nonpositive_legend_entry():
    from engine.guards import GuardError
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    payload["scale"]["legend"][0] = 0
    with pytest.raises(GuardError):
        ic.guard_payload(payload)
