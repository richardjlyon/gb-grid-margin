# tests/test_import_cost_gate.py
"""Independent recompute gate for the import_cost.json payload.

Recomputes daily import value straight from the raw CSV store (data/history/fuelhh_*.csv
and data/history/system_price_*.csv), sharing NO code with engine.import_cost, then
asserts the published payload cells agree on a sample of days. Also checks the
summary.worst_day and sanity-checks known magnitudes.

Skips if the raw data/history files are not present.
"""
from __future__ import annotations

import csv
import glob
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "history"
FUELHH_GLOB = str(HIST / "fuelhh_*.csv")
PRICE_GLOB = str(HIST / "system_price_20*.csv")

pytestmark = pytest.mark.skipif(
    not glob.glob(FUELHH_GLOB) or not glob.glob(PRICE_GLOB),
    reason="history store not present in this checkout",
)


# ---------------------------------------------------------------------------
# Independent recompute — shares NO code with engine.import_cost
# ---------------------------------------------------------------------------

def _independent_daily_import_value() -> dict[str, float]:
    """Recompute daily import value from raw CSVs.

    Join FUELHH to system_price on (settlement_date, settlement_period).
    net_import = sum of INT* legs (case-insensitive; blank/None → 0).
    per-SP contribution = max(max(net_import, 0) * 0.5 * price, 0.0).
    Skip SPs with no price-store match.
    Aggregate per day, round to 1 dp.
    """
    # Load price index: (settlement_date, settlement_period) → float
    price_idx: dict[tuple[str, str], float] = {}
    for path in sorted(glob.glob(PRICE_GLOB)):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                price_idx[(row["settlement_date"], row["settlement_period"])] = float(
                    row["system_sell_price"]
                )

    # Accumulate daily import value from fuelhh rows
    daily_acc: dict[str, float] = {}
    for path in sorted(glob.glob(FUELHH_GLOB)):
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            # Identify INT* columns (case-insensitive, exclude INDO/ITSDO which are demand cols)
            int_cols = [
                c for c in (reader.fieldnames or [])
                if c.upper().startswith("INT") and c not in ("INDO", "ITSDO")
            ]
            for row in reader:
                key = (row["settlement_date"], row["settlement_period"])
                if key not in price_idx:
                    continue
                price = price_idx[key]
                # Sum INT* legs; blanks and None → 0
                net_import = sum(
                    float(row[c]) if row.get(c) not in (None, "") else 0.0
                    for c in int_cols
                )
                imp = max(net_import, 0.0)
                # Floor per-SP contribution at £0 (negative price → no cost)
                contribution = max(imp * 0.5 * price, 0.0)
                d = row["settlement_date"]
                daily_acc[d] = daily_acc.get(d, 0.0) + contribution

    return {d: round(v, 1) for d, v in daily_acc.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _published_payload() -> dict:
    from engine import import_cost, history, system_price_history
    fuelhh_rows = history.read_store()
    price_rows = system_price_history.read_store()
    return import_cost.build_payload(fuelhh_rows, price_rows, "test")


def _carpet_cell(payload: dict, day: str) -> float | None:
    """Return the carpet cell for a given YYYY-MM-DD date, or None if absent."""
    year = day[:4]
    md = day[5:]
    doy = payload["carpet"]["doy"]
    rows = payload["carpet"]["rows"]
    if year not in rows or md not in doy:
        return None
    return rows[year][doy.index(md)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sample_days_match_independent_recompute():
    """Published carpet cells must exactly match independent recompute for sample days."""
    independent = _independent_daily_import_value()
    payload = _published_payload()

    # Sample: 2026-06-23, 2022-12-12 (big day), 2020-02-29 (leap), 2021-07-15 (summer),
    # 2022-11-26 (export day — net negative, so published cell must be £0.0).
    samples = ["2026-06-23", "2022-12-12", "2020-02-29", "2021-07-15", "2022-11-26"]
    checked = 0
    for day in samples:
        published = _carpet_cell(payload, day)
        # All five are settled historical dates that are always present; a missing cell
        # is a data regression, not a benign skip — fail loudly.
        assert published is not None, f"{day}: sample day absent from carpet"
        indep = independent.get(day)
        assert indep is not None, f"{day}: day missing from independent recompute"
        assert published == indep, (
            f"{day}: published={published} != independent={indep}"
        )
        checked += 1

    assert checked == 5, f"expected all 5 sample days checked, got {checked}"


def test_export_day_cell_is_zero_and_nonnegative():
    """Export day (2022-11-26) has net negative imports; its cell must be £0.0."""
    payload = _published_payload()
    cell = _carpet_cell(payload, "2022-11-26")
    assert cell is not None, "2022-11-26 missing from carpet"
    assert cell == 0.0, f"export day cell should be 0.0, got {cell}"
    # Belt-and-braces: assert no cell in any year is negative
    for yr, row in payload["carpet"]["rows"].items():
        for i, v in enumerate(row):
            if v is not None:
                assert v >= 0.0, (
                    f"carpet cell {yr}[{i}] = {v} is negative (import cost can't be negative)"
                )


def test_worst_day_matches_independent_max():
    """summary.worst_day must match the maximum over the independent daily series."""
    independent = _independent_daily_import_value()
    payload = _published_payload()
    worst_date, worst_val = max(independent.items(), key=lambda kv: kv[1])
    pub_worst = payload["summary"]["worst_day"]
    assert pub_worst["date"] == worst_date, (
        f"worst_day.date mismatch: published={pub_worst['date']} independent={worst_date}"
    )
    assert pub_worst["value_gbp"] == worst_val, (
        f"worst_day.value_gbp mismatch: published={pub_worst['value_gbp']} independent={worst_val}"
    )


def test_sanity_magnitudes():
    """Sanity-check known magnitudes against expected order of magnitude (±15%)."""
    independent = _independent_daily_import_value()

    # 2026-06-23: EMN-day context — expected ~£3.5m
    v_jun26 = independent["2026-06-23"]
    assert 3_500_000 * 0.85 <= v_jun26 <= 3_500_000 * 1.15, (
        f"2026-06-23: £{v_jun26:,.1f} is outside ±15% of £3.5m"
    )

    # 2022-12-12: high-price winter squeeze — expected ~£52m
    v_dec22 = independent["2022-12-12"]
    assert 52_000_000 * 0.85 <= v_dec22 <= 52_000_000 * 1.15, (
        f"2022-12-12: £{v_dec22:,.1f} is outside ±15% of £52m"
    )
