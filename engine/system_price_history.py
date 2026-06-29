"""GB Grid Margin — settled system sell-price history store.

Pulls Elexon's BMRS settlement system prices into an append-only, git-diffable CSV store
keyed (settlement_date, settlement_period) — one row per settlement half-hour, one file
per settlement year. Elexon revises settled system prices retrospectively; the store uses
``on_revision="update"`` for the daily append so revisions are absorbed silently, with git
as the audit trail.

Endpoint:
    GET https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/{date}
    JSON: {"data": [{"settlementDate": "YYYY-MM-DD", "settlementPeriod": N,
                     "systemSellPrice": float_or_null, ...}, ...]}

Store layout (wide, one row per settlement half-hour):
    data/history/system_price_YYYY.csv   one file per settlement-date year, identical header.
Columns: settlement_date, settlement_period, system_sell_price (£/MWh, float stored as text
to preserve decimal precision — not truncated to integer like the MW columns in fuelhh/embedded).
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from engine import widestore

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
HISTORY_DIR = Path("data/history")
KNOWN_GAPS_PATH = HISTORY_DIR / "system_price_known_gaps.csv"

# settlement_date is text (ISO date string).
# system_sell_price is stored as text to preserve float precision (£/MWh can be fractional);
# read_store() converts it back to float after reading.
COLUMNS = ["settlement_date", "settlement_period", "system_sell_price"]
_TEXT_COLUMNS = {"settlement_date", "system_sell_price"}

# Settlement prices lag slightly less than FUELHH; stay back a few days to avoid
# provisional same-day figures that may still be revised.
SETTLE_LAG_DAYS = 5

# Verified clean-data edge for settlement system prices (mirrors FUELHH edge).
PRICE_EDGE = date(2016, 1, 1)


def parse_day(payload: dict) -> list[dict]:
    """Parse one day's system-prices JSON response → list of store rows.

    Each output row: {settlement_date, settlement_period, system_sell_price}.
    Records with a null systemSellPrice are dropped (the settlement period has no
    published price yet — incomplete runs are not stored).
    """
    out = []
    for r in payload.get("data", []):
        price = r.get("systemSellPrice")
        if price is None:
            continue
        out.append({
            "settlement_date": r["settlementDate"],
            "settlement_period": r["settlementPeriod"],
            "system_sell_price": float(price),
        })
    return out


def year_path(settlement_date: str, base_dir: Path = HISTORY_DIR) -> Path:
    """Path of the per-year store file holding ``settlement_date`` (YYYY-MM-DD)."""
    return Path(base_dir) / f"system_price_{settlement_date[:4]}.csv"


def append_rows(rows: list[dict], base_dir: Path = HISTORY_DIR,
                on_revision: str = "raise") -> int:
    """Append system-price rows to per-year files, append-only and idempotent.

    ``on_revision`` ("raise" | "update" | "skip") — the daily append uses "update"
    to absorb Elexon's retrospective settlement-price revisions (see ``widestore.append_rows``).
    Returns the number of rows newly written or updated.
    """
    # Normalise the price to the SAME string form the CSV round-trip produces.
    # system_sell_price is a TEXT column, so widestore's idempotency check compares the
    # in-memory value against the DictReader string read back from disk. Storing a float
    # in memory (800.0) would never equal the stored string ('800.0'), misclassifying every
    # identical re-append as a revision. str(float(x)) matches what DictWriter writes.
    normalised = [{**r, "system_sell_price": str(float(r["system_sell_price"]))} for r in rows]
    return widestore.append_rows(
        normalised, COLUMNS, _TEXT_COLUMNS,
        lambda sd: year_path(sd, base_dir),
        on_revision)


def read_store(base_dir: Path = HISTORY_DIR) -> list[dict]:
    """Read the whole system-price store across year files, sorted by (settlement_date, period).

    system_sell_price is returned as float (stored as text in the CSV to preserve
    decimal precision; converted back to float on read).
    """
    rows = widestore.read_store(base_dir, "system_price_20*.csv", COLUMNS, _TEXT_COLUMNS)
    for r in rows:
        if r["system_sell_price"] is not None:
            r["system_sell_price"] = float(r["system_sell_price"])
    return rows


# --- Elexon fetch ------------------------------------------------------------

def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "grid-gauge/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def fetch_day(day: date) -> list[dict]:
    """Fetch and parse system prices for a single settlement date."""
    url = f"{BASE}/balancing/settlement/system-prices/{day.isoformat()}"
    return parse_day(_get_json(url))


def build_range(
    start: date, end: date, base_dir: Path = HISTORY_DIR,
    on_revision: str = "raise"
) -> int:
    """Backfill/append the store over [start, end] inclusive, one day at a time.

    Returns the number of rows written.
    """
    written = 0
    d = start
    while d <= end:
        rows = fetch_day(d)
        written += append_rows(rows, base_dir, on_revision)
        d += timedelta(days=1)
    return written


# --- Validation --------------------------------------------------------------

def validate_store(rows: list[dict], start: date, end: date) -> dict:
    """Validate the store over [start, end]: completeness by period count and no dupes.

    Reuses engine.history's DST-aware expected_periods() and validate_range() since
    settlement periods follow the same UK half-hourly convention as FUELHH.
    """
    from engine import history
    known_gaps = history.load_known_gaps(KNOWN_GAPS_PATH)
    return history.validate_range(rows, start, end, known_gaps=known_gaps)


# --- CLI ---------------------------------------------------------------------

def latest_settled_day() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=SETTLE_LAG_DAYS)


def main(argv: list[str] | None = None) -> None:
    import sys

    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "validate"

    if cmd == "backfill":
        start = date.fromisoformat(args[1]) if len(args) > 1 else PRICE_EDGE
        end = date.fromisoformat(args[2]) if len(args) > 2 else latest_settled_day()
        print(f"backfill system-prices {start}..{end} …")
        n = build_range(start, end)
        print(f"  {n} rows written")
    elif cmd == "append":
        end = latest_settled_day()
        start = end - timedelta(days=7)  # idempotent overlap absorbs late revisions
        n = build_range(start, end, on_revision="update")
        print(f"append system-prices {start}..{end}: {n} rows written")
    elif cmd == "validate":
        rows = read_store()
        if not rows:
            print("system-price store empty")
            return
        start = date.fromisoformat(rows[0]["settlement_date"])
        end = date.fromisoformat(rows[-1]["settlement_date"])
        rep = validate_store(rows, start, end)
        print(f"system-price store {start}..{end}: ok={rep['ok']} "
              f"expected={rep['expected_rows']} actual={rep['actual_rows']} "
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
