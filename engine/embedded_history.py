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


def daily_solar_mwh(rows: list[dict], day: str) -> float:
    """Embedded solar energy (MWh) on one settlement day = Σ(MW per period × 0.5 h)."""
    return sum(r["embedded_solar_mw"] for r in rows
               if r["settlement_date"] == day and r.get("embedded_solar_mw") is not None) * 0.5


def solar_crosscheck(embedded_mwh: float, pvlive_mwh: float, tol: float = 0.10) -> dict:
    """Compare a day's embedded solar against the independent PV_Live national figure.

    The historical twin of the live ±10% NESO-vs-PV_Live guard. Vacuously ok when PV_Live
    is zero (winter night / pre-solar era) — nothing to divide by.
    """
    if pvlive_mwh <= 0:
        return {"ok": True, "rel_diff": 0.0,
                "embedded_mwh": embedded_mwh, "pvlive_mwh": pvlive_mwh}
    rel = abs(embedded_mwh - pvlive_mwh) / pvlive_mwh
    return {"ok": rel <= tol, "rel_diff": rel,
            "embedded_mwh": embedded_mwh, "pvlive_mwh": pvlive_mwh}


# --- NESO Historic Demand Data fetch (CKAN datastore) -----------------------

NESO = "https://api.neso.energy/api/3/action"
HD_PACKAGE = "historic-demand-data"
# NESO populates ~21 days in arrears and revises retrospectively; stay well back so the
# daily append only commits settled embedded values.
NESO_LAG_DAYS = 25
_PAGE = 32000  # CKAN datastore page size; a year is ~17,520 rows.


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "grid-gauge/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def resource_ids() -> dict[int, str]:
    """Map {year: resource_id} for the Historic Demand Data package.

    Each yearly resource is named with its year (e.g. 'Historic Demand Data 2016'); parse
    the four-digit year out of the resource name/description. Raises if none are found
    (a portal restructure must be noticed, not silently skipped).
    """
    pkg = _get_json(f"{NESO}/package_show?id={HD_PACKAGE}")
    out: dict[int, str] = {}
    for res in pkg["result"]["resources"]:
        text = f"{res.get('name', '')} {res.get('description', '')}"
        for token in text.replace("-", " ").split():
            if token.isdigit() and len(token) == 4 and 2000 <= int(token) <= 2100:
                out[int(token)] = res["id"]
                break
    if not out:
        raise ValueError("no yearly resources found for historic-demand-data — portal changed?")
    return out


def fetch_year_records(rid: str) -> list[dict]:
    """All datastore records for one yearly resource, paged."""
    records: list[dict] = []
    offset = 0
    while True:
        q = urllib.parse.urlencode({"resource_id": rid, "limit": _PAGE, "offset": offset})
        result = _get_json(f"{NESO}/datastore_search?{q}")["result"]
        batch = result["records"]
        records.extend(batch)
        offset += len(batch)
        if not batch or offset >= result.get("total", 0):
            break
    return records


PVLIVE = "https://api.solar.sheffield.ac.uk/pvlive/api/v4"


def fetch_pvlive(date_from: date, date_to: date) -> PvLiveSeries:
    """PV_Live GB national (GSP 0) half-hourly outturn for a date range (inclusive)."""
    q = urllib.parse.urlencode({
        "start": f"{date_from.isoformat()}T00:00:00",
        "end": f"{date_to.isoformat()}T23:59:59",
        "extra_fields": "",
    })
    return PvLiveSeries.model_validate(_get_json(f"{PVLIVE}/gsp/0?{q}"))


def build_range(start: date, end: date, base_dir: Path = HISTORY_DIR) -> int:
    """Backfill/append the embedded store over [start, end] inclusive, fetched per year."""
    rids = resource_ids()
    written = 0
    for year in range(start.year, end.year + 1):
        rid = rids.get(year)
        if rid is None:
            print(f"  no resource for {year}, skipping")
            continue
        rows = [r for r in parse_records(fetch_year_records(rid))
                if start.isoformat() <= r["settlement_date"] <= end.isoformat()]
        written += append_rows(rows, base_dir)
    return written


def latest_settled_day() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=NESO_LAG_DAYS)


# --- CLI --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import sys
    from engine import history

    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "validate"

    if cmd == "backfill":
        start = date.fromisoformat(args[1]) if len(args) > 1 else EMBEDDED_EDGE
        end = date.fromisoformat(args[2]) if len(args) > 2 else latest_settled_day()
        print(f"backfill embedded {start}..{end} …")
        print(f"  {build_range(start, end)} rows written")
    elif cmd == "append":
        end = latest_settled_day()
        start = end - timedelta(days=NESO_LAG_DAYS + 7)  # overlap absorbs late settlement
        print(f"append embedded {start}..{end}: {build_range(start, end)} rows written")
    elif cmd == "validate":
        rows = read_store()
        if not rows:
            print("embedded store empty")
            return
        start = date.fromisoformat(rows[0]["settlement_date"])
        end = date.fromisoformat(rows[-1]["settlement_date"])
        rep = history.validate_range(rows, start, end,
                                     known_gaps=history.load_known_gaps())
        print(f"embedded store {start}..{end}: ok={rep['ok']} "
              f"expected={rep['expected_rows']} actual={rep['actual_rows']} "
              f"unexplained={len(rep['unexplained'])} dupes={len(rep['duplicates'])}")
        for inc in rep["unexplained"]:
            print(f"  UNEXPLAINED {inc['date']}: {inc['actual']}/{inc['expected']}")
        if not rep["ok"]:
            raise SystemExit(1)
    elif cmd == "crosscheck":
        # PV_Live ±10% solar cross-check on a sample of summer-midday days.
        rows = read_store()
        sample = args[1:] or ["2017-06-21", "2020-06-21", "2024-06-21"]
        bad = 0
        for day in sample:
            d = date.fromisoformat(day)
            pv_rows = fetch_pvlive(d, d).rows()
            pvlive_mwh = sum(mw for _, mw in pv_rows) * 0.5
            rep = solar_crosscheck(daily_solar_mwh(rows, day), pvlive_mwh)
            flag = "ok" if rep["ok"] else "FAIL"
            print(f"  {day}: embedded={rep['embedded_mwh']:.0f} MWh "
                  f"pvlive={rep['pvlive_mwh']:.0f} MWh rel={rep['rel_diff']:.1%} {flag}")
            bad += not rep["ok"]
        if bad:
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown command {cmd!r}; use backfill | append | validate | crosscheck")


if __name__ == "__main__":
    main()
