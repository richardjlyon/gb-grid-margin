"""Feed-boundary model tests — upstream schema drift must fail loudly at parse time."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from engine.models import (
    DemandHhRow,
    DemandOutturnRow,
    EmbeddedRow,
    FuelHhRow,
    FuelInstRecord,
    PvLiveResponse,
)


def test_fuelinst_record_parses_real_record():
    rec = FuelInstRecord.model_validate(
        {"startTime": "2026-06-25T13:30:00Z", "fuelType": "CCGT", "generation": 6350}
    )
    assert rec.fuel_type == "CCGT"
    assert rec.generation == 6350


def test_fuelinst_record_rejects_missing_generation():
    with pytest.raises(ValidationError):
        FuelInstRecord.model_validate(
            {"startTime": "2026-06-25T13:30:00Z", "fuelType": "CCGT"}
        )


NESO_ROW = {
    "_id": 1,
    "DATE_GMT": "2026-06-25T00:00:00",
    "TIME_GMT": "13:30",
    "SETTLEMENT_DATE": "2026-06-25T00:00:00",
    "SETTLEMENT_PERIOD": 29,
    "EMBEDDED_WIND_FORECAST": 1401,
    "EMBEDDED_WIND_CAPACITY": 6417,
    "EMBEDDED_SOLAR_FORECAST": 13449,
    "EMBEDDED_SOLAR_CAPACITY": 22126,
}


def test_embedded_row_parses_real_record():
    row = EmbeddedRow.model_validate(NESO_ROW)
    assert row.solar_mw == 13449
    assert row.wind_mw == 1401
    assert row.solar_capacity_mw == 22126
    assert row.wind_capacity_mw == 6417


def test_embedded_row_when_is_utc_datetime():
    row = EmbeddedRow.model_validate(NESO_ROW)
    assert row.when() == datetime(2026, 6, 25, 13, 30, tzinfo=timezone.utc)


def test_embedded_row_rejects_missing_solar():
    bad = {k: v for k, v in NESO_ROW.items() if k != "EMBEDDED_SOLAR_FORECAST"}
    with pytest.raises(ValidationError):
        EmbeddedRow.model_validate(bad)


PVLIVE_RESPONSE = {
    "meta": ["gsp_id", "datetime_gmt", "generation_mw", "installedcapacity_mwp"],
    "data": [[0, "2026-06-25T13:00:00Z", 14384.1, 23300.507]],
}


def test_pvlive_response_exposes_national_solar():
    resp = PvLiveResponse.model_validate(PVLIVE_RESPONSE)
    assert resp.solar_mw() == 14384.1
    assert resp.time() == "2026-06-25T13:00:00Z"


def test_pvlive_response_rejects_missing_generation_column():
    bad = {
        "meta": ["gsp_id", "datetime_gmt"],
        "data": [[0, "2026-06-25T13:00:00Z"]],
    }
    with pytest.raises((ValidationError, KeyError, ValueError)):
        PvLiveResponse.model_validate(bad).solar_mw()


def test_demand_outturn_row_parses_indo():
    row = DemandOutturnRow.model_validate(
        {
            "publishTime": "2026-06-25T13:30:00Z",
            "startTime": "2026-06-25T13:00:00Z",
            "settlementDate": "2026-06-25",
            "settlementPeriod": 29,
            "initialDemandOutturn": 21538,
            "initialTransmissionSystemDemandOutturn": 23201,
        }
    )
    assert row.indo == 21538


def test_demand_outturn_row_rejects_missing_indo():
    with pytest.raises(ValidationError):
        DemandOutturnRow.model_validate(
            {"startTime": "2026-06-25T13:00:00Z", "settlementPeriod": 29}
        )


def test_demand_outturn_row_keeps_present_but_null_indo():
    # Elexon occasionally publishes a present-but-null demand for the latest period;
    # that parses to None (fetch_indo then skips back to the last non-null row).
    row = DemandOutturnRow.model_validate(
        {"startTime": "2026-06-25T13:00:00Z", "settlementPeriod": 29,
         "initialDemandOutturn": None}
    )
    assert row.indo is None


FUELHH_ROW = {
    "dataset": "FUELHH",
    "publishTime": "2024-06-01T00:00:00Z",
    "startTime": "2024-05-31T23:30:00Z",
    "settlementDate": "2024-06-01",
    "settlementPeriod": 2,
    "fuelType": "CCGT",
    "generation": 3114,
}


def test_fuelhh_row_parses_real_record():
    row = FuelHhRow.model_validate(FUELHH_ROW)
    assert row.settlement_date == "2024-06-01"
    assert row.settlement_period == 2
    assert row.start_time == "2024-05-31T23:30:00Z"
    assert row.fuel_type == "CCGT"
    assert row.generation == 3114


def test_fuelhh_row_keeps_signed_interconnector_value():
    row = FuelHhRow.model_validate({**FUELHH_ROW, "fuelType": "INTEW", "generation": -528})
    assert row.generation == -528


def test_fuelhh_row_rejects_missing_generation():
    bad = {k: v for k, v in FUELHH_ROW.items() if k != "generation"}
    with pytest.raises(ValidationError):
        FuelHhRow.model_validate(bad)


DEMAND_HH_ROW = {
    "publishTime": "2024-05-31T23:30:00Z",
    "startTime": "2024-05-31T23:00:00Z",
    "settlementDate": "2024-06-01",
    "settlementPeriod": 1,
    "initialDemandOutturn": 20626,
    "initialTransmissionSystemDemandOutturn": 22782,
}


def test_demand_hh_row_parses_both_series():
    row = DemandHhRow.model_validate(DEMAND_HH_ROW)
    assert row.settlement_date == "2024-06-01"
    assert row.settlement_period == 1
    assert row.indo == 20626
    assert row.itsdo == 22782


def test_demand_hh_row_rejects_missing_indo():
    bad = {k: v for k, v in DEMAND_HH_ROW.items() if k != "initialDemandOutturn"}
    with pytest.raises(ValidationError):
        DemandHhRow.model_validate(bad)


def test_demand_hh_row_allows_null_value_but_requires_the_key():
    # Real historical rows carry a present-but-null ITSDO; that parses to None (a blank
    # cell). A missing key is still a schema error (above) — null is data, absence is drift.
    row = DemandHhRow.model_validate({**DEMAND_HH_ROW,
                                      "initialTransmissionSystemDemandOutturn": None})
    assert row.itsdo is None
    assert row.indo == 20626
