"""Import cost calculations.

Metric: import_value_£(sp) = max(net_import_mw(sp), 0) × 0.5h × system_sell_price(sp)
Export half-hours (net ≤ 0) contribute £0.

net_import_mw logic is identical to engine/grid_engine.py:193 so a future JS port cannot diverge:
    net_imports = sum(v for k, v in mix.items() if k.upper().startswith("INT"))
"""

from __future__ import annotations

from collections import defaultdict


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
    for date in sorted(value_acc):
        # mean_price divides the RAW accumulators (not the rounded output fields) so an
        # independent recompute that divides raw sums cannot diverge by ±0.005.
        mean_price = round(value_acc[date] / mwh_acc[date], 2) if mwh_acc[date] > 0 else None
        value_gbp = round(value_acc[date], 1)
        import_mwh = round(mwh_acc[date], 1)
        result.append({
            "date": date,
            "value_gbp": value_gbp,
            "import_mwh": import_mwh,
            "mean_price": mean_price,
        })
    return result
