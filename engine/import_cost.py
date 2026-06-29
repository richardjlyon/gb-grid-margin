"""Import cost calculations.

Metric: import_value_£(sp) = max(net_import_mw(sp), 0) × 0.5h × system_sell_price(sp)
Export half-hours (net ≤ 0) contribute £0.

net_import_mw logic is identical to engine/grid_engine.py:193 so a future JS port cannot diverge:
    net_imports = sum(v for k, v in mix.items() if k.upper().startswith("INT"))
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

_ONE_DAY = timedelta(days=1)

# Floor for the sqrt visual ramp / dial scale. The live cap is computed from the data
# (_cap_for) so the scale always REACHES the costliest day on record (£94.4m) rather than
# clipping it; this floor only matters for tiny fixtures. See engine/NOTES.md.
CAP_FLOOR_GBP = 20_000_000


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


# ── rolling-year half-hourly RATE carpet (homepage Wind/Sun sibling) ────────────

PERIODS = 48
RATE_CAP_FLOOR = 1_000_000   # £/h floor for the dial/carpet scale (tiny fixtures)
RATE_CAP_STEP = 500_000      # round the cap up to the next £500k above the year's worst rate


def rate_carpet_days(
    fuelhh_rows: list[dict],
    price_rows: list[dict],
    span_days: int = 365,
) -> list[dict]:
    """Per-day SP1..SP48 import-spend RATE grid (£/h), date-sorted, rolling last span_days.

    Mirrors engine.capacity.build_carpet_days so the homepage import carpet is a true sibling
    of the wind/solar carpets (drawCarpetCanvas, hour-of-day × date). Each cell =
    max(net_import_mw, 0) × system_sell_price for that settlement period (MW × £/MWh = £/h);
    export half-hours floor to £0. SPs with no price-store match are left None. DST SP49/50
    drop (clamped to the 48 grid). Cells are rounded to whole £/h.
    """
    from engine.capacity import rolling_days  # shared rolling-window filter

    price_by_key = {
        (r["settlement_date"], r["settlement_period"]): r["system_sell_price"]
        for r in price_rows
    }
    by_day: dict[str, list[float | None]] = {}
    for fh in fuelhh_rows:
        sp = fh["settlement_period"]
        if not (1 <= sp <= PERIODS):
            continue
        key = (fh["settlement_date"], sp)
        if key not in price_by_key:
            continue
        imp = max(net_import_mw(fh), 0.0)
        rate = max(imp * price_by_key[key], 0.0)
        row = by_day.setdefault(fh["settlement_date"], [None] * PERIODS)
        row[sp - 1] = round(rate)
    days = [{"date": d, "cf": by_day[d]} for d in sorted(by_day)]
    return rolling_days(days, span_days)


def rate_distribution(days: list[dict]) -> dict | None:
    """Half-hourly rate distribution (p10/p25/p50/p75/p90 + mean, £/h) over the carpet cells.

    Drives the central-tendency box-plot on BOTH the homepage dial and its legend, the same
    percentile method as site/app.js distForDays. Returns None for an empty grid.
    """
    vals = sorted(c for d in days for c in d["cf"] if c is not None)
    n = len(vals)
    if n == 0:
        return None
    q = lambda p: vals[min(n - 1, int(p * n))]  # noqa: E731
    return {
        "p10": q(0.10), "p25": q(0.25), "p50": q(0.50),
        "p75": q(0.75), "p90": q(0.90),
        "mean": round(sum(vals) / n),
    }


def rate_cap(days: list[dict]) -> int:
    """Dial/carpet scale cap (£/h) = next £500k above the worst half-hourly rate in the window.

    Data-driven so the linear scale always REACHES the year's costliest half-hour (invariant:
    the scale must not clip the real extreme), floored at RATE_CAP_FLOOR for tiny fixtures.
    """
    mx = max((c for d in days for c in d["cf"] if c is not None), default=0)
    return max(RATE_CAP_FLOOR, int(math.ceil(mx / RATE_CAP_STEP) * RATE_CAP_STEP))


# ── import capacity-factor carpet (homepage power sibling) ───────────────────────

def active_capacity_mw(row: dict, caps: dict) -> float:
    """Interconnector capacity reporting in this half-hour = Σ capacities of the legs present.

    The settled FUELHH store blanks a leg before its link was commissioned, so summing only the
    REPORTING legs (value not None/blank) tracks the fleet exactly as it grew — no commissioning
    dates needed. `caps` maps INT* leg code -> rated capacity MW.
    """
    return sum(cap for code, cap in caps.items() if row.get(code) not in (None, ""))


def import_cf_carpet_days(
    fuelhh_rows: list[dict],
    caps: dict,
    span_days: int = 365,
) -> list[dict]:
    """Per-day SP1..SP48 import capacity-factor grid, date-sorted, rolling last span_days.

    cf = max(net import, 0) ÷ active interconnector capacity — the sibling of the wind/solar
    capacity factor (output ÷ DUKES nameplate). Export half-hours floor to 0; a half-hour with no
    interconnector reporting is None (not a div-by-zero). Mirrors engine.capacity.build_carpet_days
    so the homepage import carpet is a true sibling of the wind/solar carpets (drawCarpetCanvas).
    """
    from engine.capacity import rolling_days

    by_day: dict[str, list[float | None]] = {}
    for fh in fuelhh_rows:
        sp = fh["settlement_period"]
        if not (1 <= sp <= PERIODS):
            continue
        cap = active_capacity_mw(fh, caps)
        row = by_day.setdefault(fh["settlement_date"], [None] * PERIODS)
        if cap <= 0:
            continue   # no interconnector reporting -> leave None
        row[sp - 1] = round(max(net_import_mw(fh), 0.0) / cap, 4)
    days = [{"date": d, "cf": by_day[d]} for d in sorted(by_day)]
    return rolling_days(days, span_days)


def cf_distribution(days: list[dict]) -> dict | None:
    """Import-CF distribution (p10..p90 + mean, as percentages 0–100) over the carpet cells.

    Same percentile method as site/app.js distForDays (vals[min(n-1, floor(p·n))]) so the engine
    figure and any JS recompute agree. Returns None for an empty grid.
    """
    vals = sorted(c for d in days for c in d["cf"] if c is not None)
    n = len(vals)
    if n == 0:
        return None
    q = lambda p: vals[min(n - 1, int(p * n))] * 100  # noqa: E731
    return {
        "p10": round(q(0.10), 1), "p25": round(q(0.25), 1), "p50": round(q(0.50), 1),
        "p75": round(q(0.75), 1), "p90": round(q(0.90), 1),
        "mean": round(sum(vals) / n * 100, 1),
    }


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


# ── distribution ──────────────────────────────────────────────────────────────

def distribution(daily: list[dict]) -> dict | None:
    """Daily-cost distribution (p10/p25/p50/p75/p90 + mean) over the whole record.

    Drives the central-tendency box-plot on BOTH the dial and the legend (the same
    percentile method as site/app.js distForDays: vals[min(n-1, floor(p·n))]).
    Returns None for an empty series.
    """
    vals = sorted(d["value_gbp"] for d in daily)
    n = len(vals)
    if n == 0:
        return None
    q = lambda p: vals[min(n - 1, int(p * n))]  # noqa: E731
    return {
        "p10": q(0.10), "p25": q(0.25), "p50": q(0.50),
        "p75": q(0.75), "p90": q(0.90),
        "mean": round(sum(vals) / n, 1),
    }


# ── scale ─────────────────────────────────────────────────────────────────────

def _cap_for(daily: list[dict]) -> int:
    """Scale cap = next £10 m above the costliest day, floored at CAP_FLOOR_GBP.

    Computed from the data so the sqrt ramp / dial scale always CONTAINS the record
    day (currently £94.4 m → £100 m) instead of clipping it at a fixed £20 m.
    """
    mx = max((d["value_gbp"] for d in daily), default=0.0)
    return max(CAP_FLOOR_GBP, int(math.ceil(mx / 10_000_000) * 10_000_000))


def scale(daily: list[dict]) -> dict:
    """Visual scale parameters for the sqrt ramp shared by carpet, legend and dial.

    cap_gbp is data-driven (_cap_for) so it reaches the record day; cells above it clamp.
    legend lists reference tick marks spanning to the cap.
    """
    cap = _cap_for(daily)
    return {
        "cap_gbp": cap,
        # reference ticks below the cap, then the cap itself (always ascending, all ≤ cap)
        "legend": [t for t in (1_000_000, 10_000_000, 50_000_000) if t < cap] + [cap],
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
        "distribution": distribution(daily),
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

    # distribution must be present, non-negative and monotonic (the box-plot is load-bearing).
    dist = payload.get("distribution")
    require(dist is not None, "guard_payload: distribution is missing")
    assert dist is not None  # require() raised on None; this narrows for the type-checker
    order = [dist["p10"], dist["p25"], dist["p50"], dist["p75"], dist["p90"]]
    require(all(a <= b for a, b in zip(order, order[1:])),
            f"guard_payload: distribution percentiles not ascending: {order}")
    require(all(v >= 0 for v in (*order, dist["mean"])),
            "guard_payload: distribution has a negative value")

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


# ── rate payload (homepage) + guard ─────────────────────────────────────────────

_RATE_BASIS = (
    "Rolling-year GB import-spend rate per half-hour = max(net interconnector inflow, 0) × "
    "GB system sell price (MW × £/MWh = £/h). Export half-hours floor to £0. Indexed by "
    "settlement period (local half-hour), last 365 settled days. Settled data: Elexon FUELHH "
    "(interconnectors) and Elexon system cash-out price."
)
_RATE_METRIC_LABEL = "rate at which Britain is paying to import electricity, per half-hour"
_RATE_CAVEAT = (
    "Net imported energy valued at the GB system (cash-out) price — not the contractual "
    "cost of the imports, which clear in the day-ahead auction."
)


def build_rate_payload(
    fuelhh_rows: list[dict],
    price_rows: list[dict],
    generated_utc: str,
    span_days: int = 365,
) -> dict | None:
    """Homepage import-rate payload: rolling-year hour×date £/h carpet + distribution + cap.

    A sibling of capacity_carpets.json (drawCarpetCanvas), carrying the live-read rolling-year
    spend RATE rather than the all-time daily totals (those stay in import_cost.json for the
    detail page). Returns None when no joined half-hours exist (price store not yet built).
    """
    days = rate_carpet_days(fuelhh_rows, price_rows, span_days)
    if not days:
        return None
    return {
        "basis": _RATE_BASIS,
        "source": _SOURCE,
        "metric_label": _RATE_METRIC_LABEL,
        "caveat": _RATE_CAVEAT,
        "generated_utc": generated_utc,
        "window": "rolling_365d",
        "range": {"from": days[0]["date"], "to": days[-1]["date"]},
        "cap_per_h": rate_cap(days),
        "distribution": rate_distribution(days),
        "days": days,
    }


def guard_rate_payload(payload: dict) -> None:
    """Assert homepage import-rate payload invariants. Raises GuardError on any breach.

    - caveat / metric_label non-empty (honesty framing present).
    - cap_per_h positive AND >= the worst carpet cell (the extreme must be on-scale, not clipped).
    - distribution present, non-negative, percentiles ascending (the box-plot is load-bearing).
    - every day grid has exactly 48 periods; no cell negative (spend rate is never < £0).
    """
    require(payload.get("caveat"), "guard_rate_payload: caveat is empty or missing")
    require(payload.get("metric_label"), "guard_rate_payload: metric_label is empty or missing")
    require(payload["cap_per_h"] > 0,
            f"guard_rate_payload: cap_per_h {payload['cap_per_h']} is not positive")

    dist = payload.get("distribution")
    require(dist is not None, "guard_rate_payload: distribution is missing")
    assert dist is not None
    order = [dist["p10"], dist["p25"], dist["p50"], dist["p75"], dist["p90"]]
    require(all(a <= b for a, b in zip(order, order[1:])),
            f"guard_rate_payload: distribution percentiles not ascending: {order}")
    require(all(v >= 0 for v in (*order, dist["mean"])),
            "guard_rate_payload: distribution has a negative value")

    max_cell = 0
    for d in payload["days"]:
        require(len(d["cf"]) == PERIODS,
                f"guard_rate_payload: day {d['date']} has {len(d['cf'])} periods, expected {PERIODS}")
        for cell in d["cf"]:
            if cell is None:
                continue
            require(cell >= 0,
                    f"guard_rate_payload: cell {cell} < 0 on {d['date']} (spend rate cannot be negative)")
            max_cell = max(max_cell, cell)
    require(payload["cap_per_h"] >= max_cell,
            f"guard_rate_payload: cap_per_h {payload['cap_per_h']} < worst cell {max_cell} (extreme clipped)")


# ── power payload (homepage capacity-factor sibling) + guard ─────────────────────

_POWER_BASIS = (
    "Net imports as a share of GB interconnector capacity per half-hour = max(net interconnector "
    "inflow, 0) ÷ the capacity of the interconnector legs reporting that half-hour. The sibling of "
    "the wind/solar capacity factor (output ÷ nameplate). Export half-hours floor to 0; the active "
    "capacity tracks the fleet as it grew (a leg is blank in settled FUELHH before commissioning). "
    "Last 365 settled days. Capacities: DESNZ interconnector statistics (see data/interconnectors.json)."
)
_POWER_SOURCE = "Elexon FUELHH net interconnector flow ÷ DESNZ GB interconnector capacity"


def build_power_payload(
    fuelhh_rows: list[dict],
    caps: dict,
    total_capacity_mw: int,
    generated_utc: str,
    span_days: int = 365,
) -> dict | None:
    """Homepage import-power payload: rolling-year hour×date capacity-factor carpet + dial nameplate.

    A sibling of capacity_carpets.json: the dial divides by `total_capacity_mw` (the current fleet,
    the MW ring nameplate), the carpet by the per-half-hour active capacity. Returns None when no
    half-hours have any interconnector reporting.
    """
    days = import_cf_carpet_days(fuelhh_rows, caps, span_days)
    if not days:
        return None
    return {
        "basis": _POWER_BASIS,
        "source": _POWER_SOURCE,
        "generated_utc": generated_utc,
        "window": "rolling_365d",
        "range": {"from": days[0]["date"], "to": days[-1]["date"]},
        "capacity_mw": total_capacity_mw,
        "sat": 1.0,
        "distribution": cf_distribution(days),
        "days": days,
    }


def guard_power_payload(payload: dict) -> None:
    """Assert homepage import-power payload invariants. Raises GuardError on any breach.

    - capacity_mw positive (the dial nameplate).
    - every day grid has exactly 48 periods; every cf is None or within [0, 2] (a share of capacity;
      brief over-nameplate flows tolerated, like the wind/solar carpet guard).
    """
    require(payload["capacity_mw"] > 0,
            f"guard_power_payload: capacity_mw {payload['capacity_mw']} is not positive")
    for d in payload["days"]:
        require(len(d["cf"]) == PERIODS,
                f"guard_power_payload: day {d['date']} has {len(d['cf'])} periods, expected {PERIODS}")
        for cf in d["cf"]:
            require(cf is None or 0.0 <= cf <= 2.0,
                    f"guard_power_payload: cf {cf} on {d['date']} out of [0, 2]")
