"""Grid Gauge — historical embedded solar/wind store (Reliability Stripe, Stage A).

Backfills NESO's published Historic Demand Data embedded *outturn estimate*
(EMBEDDED_WIND_GENERATION / EMBEDDED_SOLAR_GENERATION, half-hourly) into an append-only,
git-diffable CSV store that joins 1:1 to the settled FUELHH store on
(settlement_date, settlement_period). Embedded generation is distribution-connected and
unmetered: these are NESO's modelled estimates, not settled meter readings — disclosed
wherever they surface. Source: https://www.neso.energy/data-portal/historic-demand-data
(NESO Open Data Licence).

Store layout (wide, one row per settlement half-hour):
    data/history/embedded_YYYY.csv   one file per settlement-date year, identical header.
"""

from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from engine import widestore
from engine.models import EmbeddedHistRow, PvLiveSeries

UK = ZoneInfo("Europe/London")

# Align the embedded backfill to the FUELHH store's edge (the join floor), even though
# NESO's embedded series reaches back to 2009.
EMBEDDED_EDGE = date(2016, 1, 1)

HISTORY_DIR = Path("data/history")
_TEXT_COLUMNS = {"settlement_date", "period_start_utc"}

COLUMNS = ["settlement_date", "settlement_period", "period_start_utc",
           "embedded_wind_mw", "embedded_solar_mw",
           "embedded_wind_capacity_mw", "embedded_solar_capacity_mw"]


def period_start_utc(settlement_date: str, period: int) -> str:
    """UTC start of a settlement period, from its date and period number.

    Settlement periods are contiguous 30-minute real-time intervals counting from local
    midnight, so period p starts at (local-midnight-in-UTC) + (p-1)*30min. Computing in
    UTC sidesteps the DST fold: there is no ambiguity in elapsed real time.
    """
    y, m, d = (int(x) for x in settlement_date.split("-"))
    midnight_utc = datetime(y, m, d, tzinfo=UK).astimezone(timezone.utc)
    start = midnight_utc + timedelta(minutes=30 * (period - 1))
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _round_or_none(v: float | None) -> int | None:
    return None if v is None else round(v)


def to_row(rec: EmbeddedHistRow) -> dict:
    """One validated NESO record → one wide store row (integer MW; None preserved)."""
    return {
        "settlement_date": rec.settlement_date,
        "settlement_period": rec.settlement_period,
        "period_start_utc": period_start_utc(rec.settlement_date, rec.settlement_period),
        "embedded_wind_mw": _round_or_none(rec.embedded_wind_mw),
        "embedded_solar_mw": _round_or_none(rec.embedded_solar_mw),
        "embedded_wind_capacity_mw": _round_or_none(rec.embedded_wind_capacity_mw),
        "embedded_solar_capacity_mw": _round_or_none(rec.embedded_solar_capacity_mw),
    }


def parse_records(records: list[dict]) -> list[dict]:
    """Validate raw NESO records and return wide rows, sorted by (date, period)."""
    rows = [to_row(EmbeddedHistRow.model_validate(r)) for r in records]
    return sorted(rows, key=lambda r: (r["settlement_date"], r["settlement_period"]))


def year_path(settlement_date: str, base_dir: Path = HISTORY_DIR) -> Path:
    """Year-bucketed file path for a settlement date: embedded_YYYY.csv."""
    return Path(base_dir) / f"embedded_{settlement_date[:4]}.csv"


def append_rows(rows: list[dict], base_dir: Path = HISTORY_DIR) -> int:
    """Append wide rows to their per-year buckets, idempotent. Raises on revision."""
    return widestore.append_rows(
        rows, COLUMNS, _TEXT_COLUMNS, lambda sd: year_path(sd, base_dir))


def read_store(base_dir: Path = HISTORY_DIR) -> list[dict]:
    """Read and merge all embedded_*.csv files from base_dir, sorted by (date, period)."""
    return widestore.read_store(base_dir, "embedded_*.csv", COLUMNS, _TEXT_COLUMNS)
