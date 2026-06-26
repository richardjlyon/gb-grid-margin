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


class EmbeddedHistRow(BaseModel):
    """One NESO Historic Demand Data row: settled embedded solar + wind *outturn estimate*.

    Distinct from the live forecast model `EmbeddedRow` (which reads *_FORECAST): this is
    NESO's retrospective best-estimate of distribution-connected generation, published ~21
    days in arrears and revised. Blank cells (a series absent that period) coerce to None,
    kept distinct from a genuine 0.
    """

    model_config = ConfigDict(populate_by_name=True)

    settlement_date: str = Field(alias="SETTLEMENT_DATE")
    settlement_period: int = Field(alias="SETTLEMENT_PERIOD")
    embedded_wind_mw: float | None = Field(alias="EMBEDDED_WIND_GENERATION")
    embedded_solar_mw: float | None = Field(alias="EMBEDDED_SOLAR_GENERATION")
    embedded_wind_capacity_mw: float | None = Field(alias="EMBEDDED_WIND_CAPACITY")
    embedded_solar_capacity_mw: float | None = Field(alias="EMBEDDED_SOLAR_CAPACITY")

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data):
        if isinstance(data, dict):
            return {k: (None if v == "" else v) for k, v in data.items()}
        return data


class PvLiveSeries(BaseModel):
    """Sheffield PV_Live national outturn over a range, columnar meta+data form."""

    meta: list[str]
    data: list[list]

    def rows(self) -> list[tuple[str, float]]:
        ti = self.meta.index("datetime_gmt")
        gi = self.meta.index("generation_mw")
        return [(str(r[ti]), float(r[gi])) for r in self.data]


class DemandOutturnRow(BaseModel):
    """One Elexon demand-outturn row; indo (national demand) is the reconciliation reference.

    INDO is used rather than ITSDO because the supply-side reconstruction computes
    *national* demand: ITSDO additionally counts interconnector exports, station load and
    pump-storage pumping as demand, so it diverges from the reconstruction by the export
    volume on an export night (see engine/NOTES.md §3). The value is nullable: Elexon
    occasionally publishes a present-but-null demand for a period.
    """

    model_config = ConfigDict(populate_by_name=True)

    start_time: str = Field(alias="startTime")
    settlement_period: int = Field(alias="settlementPeriod")
    indo: int | None = Field(alias="initialDemandOutturn")


class FuelHhRow(BaseModel):
    """One Elexon FUELHH record: settled half-hourly generation for a fuel type.

    Interconnector legs arrive here too (fuel_type INT*), signed: positive = import to
    GB, negative = export. start_time is the period's UTC start — the unambiguous
    timeline anchor that disambiguates the autumn clock-back fold.
    """

    model_config = ConfigDict(populate_by_name=True)

    settlement_date: str = Field(alias="settlementDate")
    settlement_period: int = Field(alias="settlementPeriod")
    start_time: str = Field(alias="startTime")
    fuel_type: str = Field(alias="fuelType")
    generation: int


class DemandHhRow(BaseModel):
    """One Elexon demand-outturn record: national (INDO) and transmission (ITSDO) demand."""

    model_config = ConfigDict(populate_by_name=True)

    settlement_date: str = Field(alias="settlementDate")
    settlement_period: int = Field(alias="settlementPeriod")
    start_time: str = Field(alias="startTime")
    # Required to be present (schema guard) but nullable — historical rows occasionally
    # carry a present-but-null demand value, which is kept as a blank cell.
    indo: int | None = Field(alias="initialDemandOutturn")
    itsdo: int | None = Field(alias="initialTransmissionSystemDemandOutturn")


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


class NameplateYear(BaseModel):
    """One year's installed-capacity point from the DUKES 6.2 annual series (GW)."""

    year: int
    wind_onshore_gw: float
    wind_offshore_gw: float
    solar_gw: float

    @property
    def wind_gw(self) -> float:
        return round(self.wind_onshore_gw + self.wind_offshore_gw, 3)


class NameplateSeries(BaseModel):
    """The DUKES 6.2 annual capacity series, applied annual-step for historical denominators.

    Annual-step (the v1 rule): each year's published value is held in force until the next
    published year, so every capacity number used is a verbatim DUKES figure — never a
    modelled in-between value. Linear interpolation is deliberately unsupported here.
    """

    source: str
    source_url: str
    published: str = ""
    interpolation: str
    basis_note: str = ""
    series: list[NameplateYear]

    @model_validator(mode="after")
    def _check(self) -> "NameplateSeries":
        years = [p.year for p in self.series]
        if len(years) != len(set(years)):
            raise ValueError("duplicate year in nameplate series")
        if years != sorted(years):
            raise ValueError("nameplate series must be year-ascending")
        if self.interpolation != "annual-step":
            raise ValueError(
                f"unsupported interpolation rule {self.interpolation!r}; "
                "only annual-step is implemented (v1: no modelled figures)")
        return self

    def capacity_for(self, year: int) -> NameplateYear:
        """The published point in force for `year` under annual-step (held until the next)."""
        candidates = [p for p in self.series if p.year <= year]
        if not candidates:
            raise ValueError(
                f"no nameplate capacity published on/before {year} "
                f"(series starts {self.series[0].year})")
        return candidates[-1]
