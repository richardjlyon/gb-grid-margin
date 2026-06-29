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
