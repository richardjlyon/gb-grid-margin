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

def test_scale_floor_when_max_below_floor():
    # _DAILY max is £8m (< £20m floor) → cap stays at the floor; legend ascends, all ≤ cap.
    result = ic.scale(_DAILY)
    assert result["cap_gbp"] == 20_000_000
    assert result["legend"] == [1_000_000, 10_000_000, 20_000_000]
    assert result["legend"] == sorted(result["legend"])
    assert max(result["legend"]) == result["cap_gbp"]


def test_scale_cap_reaches_record_day():
    # A £94.4m record day must round the cap UP to the next £10m (£100m), not clip at £20m.
    daily = _DAILY + [{"date": "2021-09-09", "value_gbp": 94_384_157.9,
                       "import_mwh": 1.0, "mean_price": 1.0}]
    result = ic.scale(daily)
    assert result["cap_gbp"] == 100_000_000
    assert result["cap_gbp"] >= 94_384_157.9   # the record is on-scale, not clipped
    assert result["legend"] == [1_000_000, 10_000_000, 50_000_000, 100_000_000]


def test_distribution_percentiles_ascending_with_mean():
    d = ic.distribution(_DAILY)
    assert d is not None
    assert d["p10"] <= d["p25"] <= d["p50"] <= d["p75"] <= d["p90"]
    # mean of the 5 _DAILY values (0.5+3+1+8+2 = 14.5m / 5 = 2.9m)
    assert d["mean"] == 2_900_000.0
    assert ic.distribution([]) is None


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
                "range", "partial_years", "scale", "distribution", "carpet",
                "events", "summary"):
        assert key in payload, f"missing key: {key}"


def test_build_payload_exact_source_string():
    payload = ic.build_payload(_FUELHH_MINI, _PRICE_MINI, "2025-06-01T12:00:00Z")
    assert payload["source"] == (
        "Elexon FUELHH net interconnector flow × Elexon system (cash-out) price, "
        "settled, back to 2016"
    )


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


def test_build_payload_empty_returns_none():
    """Empty fuelhh/price stores → None (price store not yet built)."""
    assert ic.build_payload([], [], "t") is None


# ── rolling-year half-hourly RATE carpet (homepage Wind/Sun sibling) ─────────────

# Two settled days; cell = max(net_import_mw, 0) × system_sell_price (£/h).
_RATE_FH = [
    {"settlement_date": "2026-06-22", "settlement_period": 1, "INTFR": 2000},   # 2000 MW
    {"settlement_date": "2026-06-22", "settlement_period": 2, "INTFR": -500},   # export -> £0
    {"settlement_date": "2026-06-23", "settlement_period": 1, "INTFR": 1000},
    {"settlement_date": "2026-06-23", "settlement_period": 48, "INTFR": 4000},
]
_RATE_PR = [
    {"settlement_date": "2026-06-22", "settlement_period": 1, "system_sell_price": 100.0},   # 200,000
    {"settlement_date": "2026-06-22", "settlement_period": 2, "system_sell_price": 800.0},   # export -> 0
    {"settlement_date": "2026-06-23", "settlement_period": 1, "system_sell_price": 200.0},   # 200,000
    {"settlement_date": "2026-06-23", "settlement_period": 48, "system_sell_price": 300.0},  # 1,200,000
]


def test_rate_carpet_days_shape_and_cells():
    days = ic.rate_carpet_days(_RATE_FH, _RATE_PR)
    assert [d["date"] for d in days] == ["2026-06-22", "2026-06-23"]
    for d in days:
        assert len(d["cf"]) == 48
    d22, d23 = days
    assert d22["cf"][0] == 200_000      # 2000 MW × £100
    assert d22["cf"][1] == 0            # export half-hour floored to £0
    assert d22["cf"][2] is None         # no data for this SP
    assert d23["cf"][0] == 200_000      # 1000 MW × £200
    assert d23["cf"][47] == 1_200_000   # 4000 MW × £300, SP48


def test_rate_carpet_skips_sp_without_price():
    fh = _RATE_FH + [{"settlement_date": "2026-06-23", "settlement_period": 5, "INTFR": 9000}]
    days = ic.rate_carpet_days(fh, _RATE_PR)   # no price row for SP5 -> left None
    d23 = next(d for d in days if d["date"] == "2026-06-23")
    assert d23["cf"][4] is None


def test_rate_carpet_rolling_window_drops_old_days():
    fh = _RATE_FH + [{"settlement_date": "2020-01-01", "settlement_period": 1, "INTFR": 1000}]
    pr = _RATE_PR + [{"settlement_date": "2020-01-01", "settlement_period": 1, "system_sell_price": 50.0}]
    days = ic.rate_carpet_days(fh, pr, span_days=365)
    assert "2020-01-01" not in [d["date"] for d in days]


def test_rate_distribution_ascending_with_mean():
    days = ic.rate_carpet_days(_RATE_FH, _RATE_PR)
    d = ic.rate_distribution(days)
    # non-null cells: [200000, 0, 200000, 1200000] -> mean 400000
    assert d["p10"] <= d["p25"] <= d["p50"] <= d["p75"] <= d["p90"]
    assert d["mean"] == 400_000
    assert ic.rate_distribution([]) is None


def test_rate_cap_rounds_up_to_500k_above_max():
    days = ic.rate_carpet_days(_RATE_FH, _RATE_PR)
    # max cell 1,200,000 -> next £500k = £1,500,000
    assert ic.rate_cap(days) == 1_500_000


def test_rate_cap_floor_for_tiny_data():
    tiny = [{"date": "2026-06-23", "cf": [10_000] + [None] * 47}]
    assert ic.rate_cap(tiny) == 1_000_000   # floored


def test_build_rate_payload_keys_and_values():
    p = ic.build_rate_payload(_RATE_FH, _RATE_PR, "2026-06-24T00:00:00Z")
    for key in ("basis", "source", "metric_label", "caveat", "generated_utc",
                "window", "range", "cap_per_h", "distribution", "days"):
        assert key in p, f"missing key: {key}"
    assert p["range"] == {"from": "2026-06-22", "to": "2026-06-23"}
    assert p["cap_per_h"] == 1_500_000
    assert p["window"] == "rolling_365d"


def test_build_rate_payload_empty_returns_none():
    assert ic.build_rate_payload([], [], "t") is None


def test_guard_rate_payload_passes():
    p = ic.build_rate_payload(_RATE_FH, _RATE_PR, "t")
    ic.guard_rate_payload(p)  # must not raise


def test_guard_rate_payload_raises_on_negative_cell():
    from engine.guards import GuardError
    p = ic.build_rate_payload(_RATE_FH, _RATE_PR, "t")
    p["days"][0]["cf"][0] = -1
    with pytest.raises(GuardError):
        ic.guard_rate_payload(p)


def test_guard_rate_payload_raises_on_wrong_row_length():
    from engine.guards import GuardError
    p = ic.build_rate_payload(_RATE_FH, _RATE_PR, "t")
    p["days"][0]["cf"].pop()
    with pytest.raises(GuardError):
        ic.guard_rate_payload(p)


def test_guard_rate_payload_raises_on_nonpositive_cap():
    from engine.guards import GuardError
    p = ic.build_rate_payload(_RATE_FH, _RATE_PR, "t")
    p["cap_per_h"] = 0
    with pytest.raises(GuardError):
        ic.guard_rate_payload(p)


def test_guard_rate_payload_raises_on_cap_below_max_cell():
    from engine.guards import GuardError
    p = ic.build_rate_payload(_RATE_FH, _RATE_PR, "t")
    p["cap_per_h"] = 100   # below the £1.2m max cell -> the extreme would clip
    with pytest.raises(GuardError):
        ic.guard_rate_payload(p)


# ── import capacity-factor carpet (homepage power sibling) ───────────────────────

_CAPS = {"INTFR": 2000, "INTNED": 1000, "INTVKL": 1400}   # total 4400


def test_active_capacity_sums_only_reporting_legs():
    # INTVKL absent from the row -> not counted (link not yet commissioned).
    assert ic.active_capacity_mw({"settlement_period": 1, "INTFR": 1500, "INTNED": 500}, _CAPS) == 3000
    # None / blank legs are not reporting either.
    assert ic.active_capacity_mw({"INTFR": 1500, "INTNED": None, "INTVKL": ""}, _CAPS) == 2000


_PWR_FH = [
    # day 1: only IFA+BritNed reporting (active 3000); net 2000 -> cf 0.6667
    {"settlement_date": "2026-06-22", "settlement_period": 1, "INTFR": 1500, "INTNED": 500},
    # day 1 SP2: export -600 -> cf 0 (floored); active still 3000
    {"settlement_date": "2026-06-22", "settlement_period": 2, "INTFR": -500, "INTNED": -100},
    # day 2: all three reporting (active 4400); net 2200 -> cf 0.5
    {"settlement_date": "2026-06-23", "settlement_period": 1, "INTFR": 1000, "INTNED": 800, "INTVKL": 400},
]


def test_import_cf_carpet_days_shape_and_values():
    days = ic.import_cf_carpet_days(_PWR_FH, _CAPS)
    assert [d["date"] for d in days] == ["2026-06-22", "2026-06-23"]
    for d in days:
        assert len(d["cf"]) == 48
    d22, d23 = days
    assert round(d22["cf"][0], 4) == round(2000 / 3000, 4)   # net 2000 / active 3000
    assert d22["cf"][1] == 0.0                                # export half-hour floored
    assert d22["cf"][2] is None                              # no data
    assert d23["cf"][0] == 0.5                               # net 2200 / active 4400


def test_import_cf_none_when_no_legs_reporting():
    fh = [{"settlement_date": "2026-06-23", "settlement_period": 1}]   # no INT legs at all
    days = ic.import_cf_carpet_days(fh, _CAPS)
    assert days[0]["cf"][0] is None   # active capacity 0 -> cf undefined, not div-by-zero


def test_build_power_payload_keys_and_capacity():
    p = ic.build_power_payload(_PWR_FH, _CAPS, 4400, "2026-06-24T00:00:00Z")
    for key in ("basis", "source", "generated_utc", "window", "range",
                "capacity_mw", "sat", "distribution", "days"):
        assert key in p
    assert p["capacity_mw"] == 4400
    assert p["sat"] == 1.0
    assert p["range"] == {"from": "2026-06-22", "to": "2026-06-23"}


def test_build_power_payload_empty_returns_none():
    assert ic.build_power_payload([], _CAPS, 4400, "t") is None


def test_guard_power_payload_passes():
    p = ic.build_power_payload(_PWR_FH, _CAPS, 4400, "t")
    ic.guard_power_payload(p)


def test_guard_power_payload_raises_on_cf_out_of_range():
    from engine.guards import GuardError
    p = ic.build_power_payload(_PWR_FH, _CAPS, 4400, "t")
    p["days"][0]["cf"][0] = 3.0   # implausible CF
    with pytest.raises(GuardError):
        ic.guard_power_payload(p)


def test_guard_power_payload_raises_on_nonpositive_capacity():
    from engine.guards import GuardError
    p = ic.build_power_payload(_PWR_FH, _CAPS, 4400, "t")
    p["capacity_mw"] = 0
    with pytest.raises(GuardError):
        ic.guard_power_payload(p)
