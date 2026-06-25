"""Feed-boundary model tests — upstream schema drift must fail loudly at parse time."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from engine.models import (
    DemandOutturnRow,
    EmbeddedRow,
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


def test_demand_outturn_row_parses_itsdo():
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
    assert row.itsdo == 23201


def test_demand_outturn_row_rejects_missing_itsdo():
    with pytest.raises(ValidationError):
        DemandOutturnRow.model_validate(
            {"startTime": "2026-06-25T13:00:00Z", "settlementPeriod": 29}
        )
