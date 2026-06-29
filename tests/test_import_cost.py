from engine import import_cost as ic


def test_net_import_sums_INT_legs_case_insensitive_blanks_zero():
    row = {"INTFR": 1000, "intned": 500, "INTEW": -200, "WIND": 9999, "CCGT": 8000}
    assert ic.net_import_mw(row) == 1300  # 1000 + 500 - 200; non-INT ignored

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
