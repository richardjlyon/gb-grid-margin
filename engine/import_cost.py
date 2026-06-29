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

# Maximum daily import cost used by the sqrt visual ramp on the carpet. Tuned to the real
# 2016→edge distribution (median £3.2m, p90 £10.8m, p99 £19.9m, max £94.4m): at £20m only ~1%
# of days saturate full-red and ~⅔ sit in the pale half, so the carpet reads as a pale field with
# red on the genuinely costly days rather than a wash of red. See engine/NOTES.md.
CAP_GBP = 20_000_000


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
        # Floor per-SP contribution at £0: a negative system sell price on an import
        # half-hour means the system is receiving money, not paying — no import cost.
        value_acc[date] += max(imp * 0.5 * price, 0.0)
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

    cap_gbp is the documented module constant CAP_GBP (£20 m); cells above it are clamped.
    legend lists the annotated tick marks on the colour bar (low, mid, and the cap).
    """
    return {
        "cap_gbp": CAP_GBP,
        "legend": [1_000_000, 5_000_000, CAP_GBP],
    }


# ── payload + guard ───────────────────────────────────────────────────────────

from engine.guards import require  # noqa: E402

_BASIS = (
    "Daily GB net import value = sum over settled half-hours of max(net interconnector "
    "inflow, 0) × ½h × GB system sell price. Export half-hours are floored to £0: the "
    "metric captures what the system paid to attract electricity from interconnected "
    "markets, not what was earned on export flows. Settled data: Elexon FUELHH "
    "(interconnectors) and Elexon system cash-out price, back to 2016."
)
_SOURCE = (
    "Elexon FUELHH net interconnector flow × Elexon system (cash-out) price, "
    "settled, back to 2016"
)
_METRIC_LABEL = "net imported energy valued at the GB system price"
_CAVEAT = (
    "Net imported energy valued at the GB system (cash-out) price — not the "
    "contractual cost of the imports, which clear in the day-ahead auction."
)


def build_payload(
    fuelhh_rows: list[dict],
    price_rows: list[dict],
    generated_utc: str,
) -> dict | None:
    """Assemble the full import-cost JSON payload from raw store rows.

    Calls daily_import_value once and feeds all downstream helpers so every
    derived field is computed from the same daily series.
    Returns None when the joined daily series is empty (e.g. price store not yet built).
    """
    from engine.derived import partial_years  # deferred to break circular import

    daily = daily_import_value(fuelhh_rows, price_rows)
    if not daily:
        return None
    dates = [d["date"] for d in daily]
    return {
        "basis": _BASIS,
        "source": _SOURCE,
        "metric_label": _METRIC_LABEL,
        "caveat": _CAVEAT,
        "generated_utc": generated_utc,
        "range": {
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        },
        "partial_years": partial_years(dates),
        "scale": scale(daily),
        "carpet": carpet_matrix(daily),
        "events": events(daily),
        "summary": summary(daily),
    }


def guard_payload(payload: dict) -> None:
    """Assert import-cost payload invariants. Raises GuardError on any breach.

    Invariants:
    - caveat and metric_label must be non-empty (honesty framing must be present).
    - scale.cap_gbp and every scale.legend entry must be positive.
    - Every carpet row must have exactly 366 cells.
    - No carpet cell may be negative (import value is never negative — exports floor
      to £0; a negative cell indicates a logic break).
    - summary.worst_day.value_gbp must equal the maximum carpet cell value (the
      worst day recorded in the summary must match the carpet's peak cell).
    """
    require(payload.get("caveat"), "guard_payload: caveat is empty or missing")
    require(payload.get("metric_label"), "guard_payload: metric_label is empty or missing")

    sc = payload["scale"]
    require(sc["cap_gbp"] > 0,
            f"guard_payload: scale.cap_gbp {sc['cap_gbp']} is not positive")
    for v in sc["legend"]:
        require(v > 0, f"guard_payload: scale.legend entry {v} is not positive")

    max_cell: float | None = None
    for yr, row in payload["carpet"]["rows"].items():
        require(len(row) == 366,
                f"guard_payload: carpet row {yr} has {len(row)} cells, expected 366")
        for cell in row:
            if cell is None:
                continue
            require(cell >= 0,
                    f"guard_payload: carpet cell {cell} < 0 for year {yr} "
                    f"(import value cannot be negative)")
            if max_cell is None or cell > max_cell:
                max_cell = cell

    if max_cell is not None:
        worst = payload["summary"]["worst_day"]["value_gbp"]
        require(
            worst == max_cell,
            f"guard_payload: worst_day.value_gbp {worst} != carpet max {max_cell}",
        )
