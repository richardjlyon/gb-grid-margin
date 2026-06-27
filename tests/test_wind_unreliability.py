from engine.models import NameplateSeries
from engine import wind_unreliability as wu


def _ns():
    # 10 GW wind in every year used by these tests (annual-step series).
    return NameplateSeries.model_validate({
        "source": "test", "source_url": "test", "interpolation": "annual-step",
        "series": [
            {"year": y, "wind_onshore_gw": 5.0, "wind_offshore_gw": 5.0, "solar_gw": 1.0}
            for y in range(2016, 2027)
        ],
    })


def test_combined_daily_cf_means_transmission_plus_embedded_over_nameplate():
    # Two half-hours on one day: transmission WIND 500 & 700, embedded wind 100 & 300.
    # combined MW = 600, 1000 -> mean 800 MW; cap 10 GW -> cf 0.08.
    fuelhh = [
        {"settlement_date": "2020-06-01", "settlement_period": 1, "WIND": 500},
        {"settlement_date": "2020-06-01", "settlement_period": 2, "WIND": 700},
    ]
    embedded = [
        {"settlement_date": "2020-06-01", "settlement_period": 1, "embedded_wind_mw": 100},
        {"settlement_date": "2020-06-01", "settlement_period": 2, "embedded_wind_mw": 300},
    ]
    out = wu.combined_daily_cf_series(fuelhh, embedded, _ns())
    assert out == [{"date": "2020-06-01", "cf": 0.08, "mean_mw": 800.0, "capacity_gw": 10.0}]


def test_combined_daily_cf_omits_days_with_no_embedded_join():
    fuelhh = [{"settlement_date": "2020-06-02", "settlement_period": 1, "WIND": 500}]
    embedded = []  # no join for that half-hour
    assert wu.combined_daily_cf_series(fuelhh, embedded, _ns()) == []
