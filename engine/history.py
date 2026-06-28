"""Grid Gauge — settled half-hourly history pipeline (Stage 4).

Pulls settled FUELHH (generation by fuel type + signed interconnector flows) and the
national demand outturn from Elexon, and appends them to a committed, git-diffable CSV
store — the source of truth for every historical figure. No modelled numbers: every
value is a settled Elexon figure, traceable to a settlement date and period.

Clean-data edge (verified against the live API, 2026-06-25): FUELHH begins 2016-01-01;
the half-hourly demand outturn begins 2016-03-01. Nothing exists earlier on this API.

Store layout (wide, one row per settlement half-hour):
    data/history/fuelhh_YYYY.csv   one file per settlement-date year, identical header.
Columns: settlement_date, settlement_period, period_start_utc, then one MW column per
fuel/interconnector code, then ND (national demand). A blank cell means the series did
not exist that period (e.g. an interconnector before commissioning); 0 means present
and zero. The store is append-only and idempotent: re-running a day is a no-op.
"""

from __future__ import annotations

import csv
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from engine import widestore
from engine.models import DemandHhRow, FuelHhRow

UK = ZoneInfo("Europe/London")
BASE = "https://data.elexon.co.uk/bmrs/api/v1"

# Verified clean-data edges (2026-06-25): FUELHH from 2016-01-01; demand from 2016-03-01.
FUELHH_EDGE = date(2016, 1, 1)
DEMAND_EDGE = date(2016, 3, 1)

HISTORY_DIR = Path("data/history")

# Columns stored as text, not numbers; everything else is int-or-blank.
_TEXT_COLUMNS = {"settlement_date", "period_start_utc"}

# The wide store's value-bearing series. FUELS + INTERCONNECTORS is the fuelType roster
# as of 2026-06 (10 fuels + 10 interconnectors); the 2016 edge carries a subset, with
# blank cells where a series did not yet exist. A fuelType outside this set fails the
# pivot loudly — a roster change must be noticed and the superset extended, never
# silently dropped.
FUELS = ["BIOMASS", "CCGT", "COAL", "NPSHYD", "NUCLEAR", "OCGT", "OIL", "OTHER", "PS", "WIND"]
INTERCONNECTORS = ["INTELEC", "INTEW", "INTFR", "INTGRNL", "INTIFA2", "INTIRL",
                   "INTNED", "INTNEM", "INTNSL", "INTVKL"]
SERIES = FUELS + INTERCONNECTORS
KNOWN_SERIES = frozenset(SERIES)

# Known truncated/variant fuelType codes mapped to their canonical series. Each entry is
# a deliberate, audited equivalence — never a fuzzy guess. INTELE is ElecLink reported
# under a truncated code on 2021-09-10 (SP22-30, generation 0, its first feed appearance);
# it is the same asset as INTELEC. Normalisation changes the label, never the value.
ALIASES: dict[str, str] = {"INTELE": "INTELEC"}

COLUMNS = (["settlement_date", "settlement_period", "period_start_utc"]
           + SERIES + ["INDO", "ITSDO"])


def expected_periods(day: date) -> int:
    """Number of half-hourly settlement periods in a UK settlement day.

    48 on a normal day; 46 on the spring clock-forward Sunday (the day spans 23h);
    50 on the autumn clock-back Sunday (the day spans 25h). Derived from the tzdata
    rules via Europe/London, not a hardcoded calendar, so it stays correct if the
    DST rule ever changes.
    """
    midnight = datetime(day.year, day.month, day.day, tzinfo=UK)
    nxt = day + timedelta(days=1)
    next_midnight = datetime(nxt.year, nxt.month, nxt.day, tzinfo=UK)
    # Convert to UTC before subtracting: two aware datetimes sharing one zoneinfo
    # tzinfo subtract as naive wall-clock (DST ignored), which would always give 24h.
    span_hours = (
        next_midnight.astimezone(timezone.utc) - midnight.astimezone(timezone.utc)
    ).total_seconds() / 3600
    return round(span_hours * 2)


def pivot_day(
    fuel_rows: list[FuelHhRow], demand_rows: list[DemandHhRow]
) -> list[dict]:
    """Collapse a day's FUELHH + demand rows into one wide dict per settlement period.

    Each output row carries every column in COLUMNS; a series absent that period is
    None (a blank cell), kept distinct from a genuine 0. Raises on a fuelType outside
    the known roster so a feed change cannot pass silently.
    """
    coded = [(ALIASES.get(r.fuel_type, r.fuel_type), r) for r in fuel_rows]
    unknown = {c for c, _ in coded} - KNOWN_SERIES
    if unknown:
        raise ValueError(f"unknown FUELHH fuelType(s) not in store roster: {sorted(unknown)}")

    by_period: dict[int, dict] = {}
    for code, r in coded:
        row = by_period.setdefault(r.settlement_period, {})
        row.setdefault("_meta", (r.settlement_date, r.start_time))
        row[code] = r.generation
    demand_by_period = {d.settlement_period: d for d in demand_rows}

    out = []
    for period in sorted(by_period):
        sd, start = by_period[period]["_meta"]
        d = demand_by_period.get(period)
        row = {
            "settlement_date": sd,
            "settlement_period": period,
            "period_start_utc": start,
            "INDO": d.indo if d else None,
            "ITSDO": d.itsdo if d else None,
        }
        for s in SERIES:
            row[s] = by_period[period].get(s)
        out.append(row)
    return out


# --- Wide CSV store (append-only, idempotent) -------------------------------

def year_path(settlement_date: str, base_dir: Path = HISTORY_DIR) -> Path:
    """Path of the per-year store file holding `settlement_date` (YYYY-MM-DD)."""
    return Path(base_dir) / f"fuelhh_{settlement_date[:4]}.csv"


_key = widestore.key  # retained: find_duplicates() uses it


def append_rows(rows: list[dict], base_dir: Path = HISTORY_DIR,
                on_revision: str = "raise") -> int:
    """Append wide rows to their per-year files, append-only and idempotent.

    A key (settlement_date, settlement_period) already present with identical values is
    skipped (re-running a day is a no-op). A key present with *different* values is a
    settlement revision; ``on_revision`` ("raise" | "update" | "skip") decides the policy
    (see ``widestore.append_rows``). The daily append uses "update"; backfills "raise".
    Returns the number of rows actually written.
    """
    return widestore.append_rows(
        rows, COLUMNS, _TEXT_COLUMNS, lambda sd: year_path(sd, base_dir), on_revision)


def read_store(base_dir: Path = HISTORY_DIR) -> list[dict]:
    """Read the whole store across year files, sorted by (settlement_date, period)."""
    return widestore.read_store(base_dir, "fuelhh_*.csv", COLUMNS, _TEXT_COLUMNS)


# --- Validation gate --------------------------------------------------------

def _dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def expected_row_count(start: date, end: date) -> int:
    """Expected wide-store rows for [start, end] inclusive — one per settlement period,
    DST-corrected (46 on the spring day, 50 on the autumn day)."""
    return sum(expected_periods(d) for d in _dates(start, end))


def incomplete_days(rows: list[dict], start: date, end: date) -> list[dict]:
    """Days in [start, end] whose half-hour count != the DST-aware expected count.

    Completeness is judged by COUNT per day, not by a contiguous 1..N period set:
    early Elexon days are occasionally numbered non-contiguously (e.g. 2016-03-27's 46
    half-hours run 1..45, 48) yet are complete. A wrong count is the real signal — a
    genuine hole (fewer rows than the day's 48/46/50) or an over-long day (more).
    Each entry: {date, actual, expected, shortfall} (shortfall<0 means excess rows).
    """
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["settlement_date"]] = counts.get(r["settlement_date"], 0) + 1
    out = []
    for d in _dates(start, end):
        ds = d.isoformat()
        exp = expected_periods(d)
        act = counts.get(ds, 0)
        if act != exp:
            out.append({"date": ds, "actual": act, "expected": exp,
                        "shortfall": exp - act})
    return out


def find_duplicates(rows: list[dict]) -> set[tuple[str, int]]:
    """Return any (settlement_date, settlement_period) key appearing more than once."""
    seen: set = set()
    dupes: set = set()
    for r in rows:
        k = _key(r)
        (dupes if k in seen else seen).add(k)
    return dupes


KNOWN_GAPS_PATH = HISTORY_DIR / "known_gaps.csv"


def load_known_gaps(path: Path = KNOWN_GAPS_PATH) -> dict[str, dict]:
    """Load the frozen record of genuine Elexon non-publications, keyed by date.

    Each row is a settlement day Elexon never fully published; recording it lets the gate
    pass on documented history while still failing on any NEW gap (a real regression).
    """
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(newline="") as f:
        return {r["settlement_date"]: {"actual": int(r["actual"]),
                                       "expected": int(r["expected"])}
                for r in csv.DictReader(f)}


def validate_range(
    rows: list[dict], start: date, end: date, known_gaps: dict | None = None
) -> dict:
    """Aggregate gate: every day complete (count == expected half-hours) or a recorded
    known gap, and no duplicate keys. `unexplained` holds incomplete days that do not
    match the known-gaps manifest — a new/changed hole that must be reviewed.
    """
    known_gaps = known_gaps or {}
    incs = incomplete_days(rows, start, end)
    unexplained = [
        inc for inc in incs
        if known_gaps.get(inc["date"]) != {"actual": inc["actual"],
                                           "expected": inc["expected"]}
    ]
    dupes = find_duplicates(rows)
    return {
        "ok": not unexplained and not dupes,
        "expected_rows": expected_row_count(start, end),
        "actual_rows": len(rows),
        "incomplete_days": incs,
        "unexplained": unexplained,
        "duplicates": sorted(dupes),
    }


def daily_mwh(rows: list[dict], day: str, series: str) -> float:
    """Energy (MWh) for one series on one settlement day = Σ(MW per period × 0.5 h).

    The settled half-hourly figure is average MW over the period; a period is half an
    hour, so each contributes MW × 0.5 MWh. Skips blank (None) cells.
    """
    total = sum(r[series] for r in rows
                if r["settlement_date"] == day and r.get(series) is not None)
    return total * 0.5


# --- Elexon fetch + backfill ------------------------------------------------

def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "grid-gauge/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def fetch_fuelhh(date_from: date, date_to: date) -> list[FuelHhRow]:
    """Settled FUELHH rows (generation + signed interconnectors) for a settlement-date
    range, inclusive. Uses /stream, which has no 7-day cap."""
    url = (f"{BASE}/datasets/FUELHH/stream"
           f"?settlementDateFrom={date_from.isoformat()}"
           f"&settlementDateTo={date_to.isoformat()}")
    data = _get_json(url)
    assert isinstance(data, list), "FUELHH stream did not return a list"
    return [FuelHhRow.model_validate(r) for r in data]


def fetch_demand(date_from: date, date_to: date) -> list[DemandHhRow]:
    """Half-hourly national/transmission demand outturn (INDO/ITSDO) for a range.

    Uses /demand/outturn/stream (bare array, no range cap); the non-stream
    /demand/outturn is hard-capped at 7 days and 400s on a longer window.
    """
    url = (f"{BASE}/demand/outturn/stream"
           f"?settlementDateFrom={date_from.isoformat()}"
           f"&settlementDateTo={date_to.isoformat()}")
    data = _get_json(url)
    assert isinstance(data, list), "demand/outturn/stream did not return a list"
    return [DemandHhRow.model_validate(r) for r in data]


def _group_by_day(rows: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r.settlement_date, []).append(r)
    return out


def build_range(
    start: date, end: date, base_dir: Path = HISTORY_DIR, chunk_days: int = 31,
    on_revision: str = "raise"
) -> int:
    """Backfill/append the store over [start, end] inclusive, in monthly chunks.

    Each chunk is one FUELHH /stream call and one demand call; rows are grouped by
    settlement date, pivoted to wide, and appended (append-only, idempotent). Demand is
    fetched only on/after its clean edge; before it, the INDO/ITSDO cells stay blank.
    Returns the number of rows written.
    """
    written = 0
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), end)
        fuel_by_day = _group_by_day(fetch_fuelhh(chunk_start, chunk_end))
        demand_by_day: dict[str, list] = {}
        if chunk_end >= DEMAND_EDGE:
            d_from = max(chunk_start, DEMAND_EDGE)
            demand_by_day = _group_by_day(fetch_demand(d_from, chunk_end))
        for day in sorted(fuel_by_day):
            rows = pivot_day(fuel_by_day[day], demand_by_day.get(day, []))
            written += append_rows(rows, base_dir, on_revision)
        chunk_start = chunk_end + timedelta(days=1)
    return written


# --- CLI --------------------------------------------------------------------

# Settled FUELHH lags publication; stay a few days back so the daily append only ever
# commits settled half-hours (never a provisional same-day figure that could be revised).
SETTLE_LAG_DAYS = 5


def latest_settled_day() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=SETTLE_LAG_DAYS)


def main(argv: list[str] | None = None) -> None:
    import sys

    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "validate"

    if cmd == "backfill":
        start = date.fromisoformat(args[1]) if len(args) > 1 else FUELHH_EDGE
        end = date.fromisoformat(args[2]) if len(args) > 2 else latest_settled_day()
        print(f"backfill {start}..{end} …")
        n = build_range(start, end)
        print(f"  {n} rows written")
    elif cmd == "append":
        end = latest_settled_day()
        start = end - timedelta(days=7)  # idempotent overlap absorbs any late settlement
        n = build_range(start, end, on_revision="update")  # absorb Elexon revisions
        print(f"append {start}..{end}: {n} rows written")
    elif cmd == "validate":
        rows = read_store()
        if not rows:
            print("store empty")
            return
        start = date.fromisoformat(rows[0]["settlement_date"])
        end = date.fromisoformat(rows[-1]["settlement_date"])
        rep = validate_range(rows, start, end, known_gaps=load_known_gaps())
        print(f"store {start}..{end}: ok={rep['ok']} "
              f"expected={rep['expected_rows']} actual={rep['actual_rows']} "
              f"incomplete={len(rep['incomplete_days'])} (known) "
              f"unexplained={len(rep['unexplained'])} dupes={len(rep['duplicates'])}")
        for inc in rep["unexplained"]:
            print(f"  UNEXPLAINED {inc['date']}: {inc['actual']}/{inc['expected']} "
                  f"(shortfall {inc['shortfall']})")
        if not rep["ok"]:
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown command {cmd!r}; use backfill | append | validate")


if __name__ == "__main__":
    main()
