"""Pydantic models for each upstream feed boundary.

These exist so a silent schema change at Elexon/NESO/Sheffield fails loudly at parse
time, rather than flowing through as a wrong published figure. Field aliases map the
upstream JSON names to Python attribute names; extra fields are ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FuelInstRecord(BaseModel):
    """One Elexon FUELINST record: instantaneous generation for a fuel type."""

    model_config = ConfigDict(populate_by_name=True)

    start_time: str = Field(alias="startTime")
    fuel_type: str = Field(alias="fuelType")
    generation: int


class EmbeddedRow(BaseModel):
    """One NESO embedded forecast row: embedded solar + wind estimate and capacity."""

    model_config = ConfigDict(populate_by_name=True)

    date_gmt: str = Field(alias="DATE_GMT")
    time_gmt: str = Field(alias="TIME_GMT")
    solar_mw: int = Field(alias="EMBEDDED_SOLAR_FORECAST")
    wind_mw: int = Field(alias="EMBEDDED_WIND_FORECAST")
    solar_capacity_mw: int = Field(alias="EMBEDDED_SOLAR_CAPACITY")
    wind_capacity_mw: int = Field(alias="EMBEDDED_WIND_CAPACITY")

    def when(self) -> datetime:
        """UTC timestamp of this row, from its date and time-of-day fields."""
        return datetime.strptime(
            f"{self.date_gmt[:10]} {self.time_gmt}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)


class PvLiveResponse(BaseModel):
    """Sheffield PV_Live national outturn, in its columnar meta+data form."""

    meta: list[str]
    data: list[list]

    def _first(self) -> dict:
        return dict(zip(self.meta, self.data[0]))

    def solar_mw(self) -> float:
        return float(self._first()["generation_mw"])

    def time(self) -> str:
        return str(self._first()["datetime_gmt"])


class DemandOutturnRow(BaseModel):
    """One Elexon demand-outturn row; itsdo is the reconciliation reference."""

    model_config = ConfigDict(populate_by_name=True)

    start_time: str = Field(alias="startTime")
    settlement_period: int = Field(alias="settlementPeriod")
    itsdo: int = Field(alias="initialTransmissionSystemDemandOutturn")


class Nameplate(BaseModel):
    """Published installed-capacity denominators (DUKES). Dated, cited, self-reconciling."""

    as_of: str
    source: str
    source_url: str
    published: str = ""
    wind_onshore_gw: float
    wind_offshore_gw: float
    wind_gw: float
    solar_gw: float
    wind_plus_solar_gw: float
    basis_note: str = ""

    @model_validator(mode="after")
    def _reconcile(self) -> "Nameplate":
        if abs(self.wind_gw - (self.wind_onshore_gw + self.wind_offshore_gw)) > 0.02:
            raise ValueError(
                f"wind_gw {self.wind_gw} != onshore {self.wind_onshore_gw} "
                f"+ offshore {self.wind_offshore_gw}")
        if abs(self.wind_plus_solar_gw - (self.wind_gw + self.solar_gw)) > 0.02:
            raise ValueError(
                f"wind_plus_solar_gw {self.wind_plus_solar_gw} != "
                f"wind {self.wind_gw} + solar {self.solar_gw}")
        return self
