"""Import cost calculations.

Metric: import_value_£(sp) = max(net_import_mw(sp), 0) × 0.5h × system_sell_price(sp)
Export half-hours (net ≤ 0) contribute £0.

net_import_mw logic is identical to engine/grid_engine.py:193 so a future JS port cannot diverge:
    net_imports = sum(v for k, v in mix.items() if k.upper().startswith("INT"))
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

_ONE_DAY = timedelta(days=1)

# Maximum daily import cost used by the sqrt visual ramp on the carpet.
CAP_GBP = 10_000_000


def net_import_mw(row: dict) -> float:
    """Sum all INT* interconnector legs (case-insensitive). None/blank → 0."""
    total = 0.0
    for k, v in row.items():
        if k.upper().startswith("INT"):
            if v is None or v == "":
                v = 0
            total += float(v)
    return total


def daily_import_value(
    fuelhh_rows: list[dict],
    price_rows: list[dict],
) -> list[dict]:
    """Join FUELHH rows to price rows on (settlement_date, settlement_period).

    Returns list[{date, value_gbp, import_mwh, mean_price}] sorted date-ascending.
    SPs with no price-store match are skipped.
    mean_price is value-weighted (value_gbp / import_mwh) or None when import_mwh == 0.
    """
    price_by_key: dict[tuple, float] = {
        (r["settlement_date"], r["settlement_period"]): r["system_sell_price"]
        for r in price_rows
    }

    value_acc: dict[str, float] = defaultdict(float)
    mwh_acc: dict[str, float] = defaultdict(float)

    for row in fuelhh_rows:
        key = (row["settlement_date"], row["settlement_period"])
        if key not in price_by_key:
            continue
        price = price_by_key[key]
        imp = max(net_import_mw(row), 0.0)
        date = row["settlement_date"]
        value_acc[date] += imp * 0.5 * price
        mwh_acc[date] += imp * 0.5

    result = []
    for d in sorted(value_acc):
        # mean_price divides the RAW accumulators (not the rounded output fields) so an
        # independent recompute that divides raw sums cannot diverge by ±0.005.
        mean_price = round(value_acc[d] / mwh_acc[d], 2) if mwh_acc[d] > 0 else None
        value_gbp = round(value_acc[d], 1)
        import_mwh = round(mwh_acc[d], 1)
        result.append({
            "date": d,
            "value_gbp": value_gbp,
            "import_mwh": import_mwh,
            "mean_price": mean_price,
        })
    return result


# ── carpet matrix ─────────────────────────────────────────────────────────────

def _doy_labels() -> list[str]:
    """The 366 'MM-DD' column keys, using a leap year (2020) so 29 Feb has a slot."""
    d, end = date(2020, 1, 1), date(2020, 12, 31)
    out = []
    while d <= end:
        out.append(d.strftime("%m-%d"))
        d += _ONE_DAY
    return out


def carpet_matrix(daily: list[dict]) -> dict:
    """Years × day-of-year import-value grid.

    Returns {"years": [int, …], "doy": ["MM-DD" × 366], "rows": {str(year): [value_gbp|None × 366]}}.
    Columns keyed by month-day using a leap-year template so 29 Feb always has a slot; missing days None.
    """
    labels = _doy_labels()
    col = {lab: i for i, lab in enumerate(labels)}
    years = sorted({int(s["date"][:4]) for s in daily})
    rows = {str(y): [None] * len(labels) for y in years}
    for s in daily:
        rows[s["date"][:4]][col[s["date"][5:]]] = s["value_gbp"]
    return {"years": years, "doy": labels, "rows": rows}


# ── summary ───────────────────────────────────────────────────────────────────

def summary(daily: list[dict]) -> dict:
    """High-level summary of the daily import value series.

    Returns:
        worst_day      -- {date, value_gbp} for the single most expensive day.
        total_by_year  -- {str(year): Σ value_gbp} rounded to 1 dp.
        year_to_date   -- total_by_year entry for the latest year in the series.
    """
    worst = max(daily, key=lambda r: r["value_gbp"])
    totals: dict[str, float] = defaultdict(float)
    for r in daily:
        totals[r["date"][:4]] += r["value_gbp"]
    total_by_year = {yr: round(v, 1) for yr, v in sorted(totals.items())}
    latest_year = max(total_by_year)
    return {
        "worst_day": {"date": worst["date"], "value_gbp": worst["value_gbp"]},
        "total_by_year": total_by_year,
        "year_to_date": total_by_year[latest_year],
    }


# ── events ────────────────────────────────────────────────────────────────────

def events(daily: list[dict], top_n: int = 8) -> list[dict]:
    """The top_n costliest import days, value-descending, for inline carpet annotation."""
    ranked = sorted(daily, key=lambda r: r["value_gbp"], reverse=True)
    return [{"date": r["date"], "value_gbp": r["value_gbp"]} for r in ranked[:top_n]]


# ── scale ─────────────────────────────────────────────────────────────────────

def scale(daily: list[dict]) -> dict:  # noqa: ARG001 — daily reserved for future auto-ranging
    """Visual scale parameters for the carpet sqrt ramp.

    cap_gbp is the documented module constant CAP_GBP (£10 m); cells above it are clamped.
    legend lists the annotated tick marks on the colour bar.
    """
    return {
        "cap_gbp": CAP_GBP,
        "legend": [1_000_000, 5_000_000, 10_000_000],
    }
