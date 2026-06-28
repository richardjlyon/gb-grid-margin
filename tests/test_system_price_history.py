from engine import system_price_history as sph


def test_parse_day_keeps_priced_periods_only():
    payload = {"data": [
        {"settlementDate": "2026-06-23", "settlementPeriod": 42, "systemSellPrice": 800.0},
        {"settlementDate": "2026-06-23", "settlementPeriod": 43, "systemSellPrice": None},
    ]}
    assert sph.parse_day(payload) == [
        {"settlement_date": "2026-06-23", "settlement_period": 42, "system_sell_price": 800.0},
    ]
