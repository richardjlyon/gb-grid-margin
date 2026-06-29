"""Grid Conditions OVERCAST lamp — conditional 'clear-sky' solar distribution.

Solar capacity factor is dominated by the diurnal and seasonal cycles, so a flat percentile cannot
express 'cloudy'. This builds, per (week-of-year, settlement period) cell, the empirical distribution
of half-hourly solar CF over the WHOLE embedded-solar record — 'what this half-hour, this season, has
delivered'. Two numbers per cell:

  * p25      — the RELATIVE overcast line: live CF below it = in the cloudiest quarter for this slot
               (the site's usual-half lamp policy, conditioned on solar geometry).
  * ceiling  — a ROBUST clear-sky reference: the P95 of the cell, NOT the raw max (a single bad
               outturn point, a capacity-column glitch, or cloud-edge over-irradiance would inflate
               the max and make every real day read as cloudy). The lamp reads live CF / ceiling as
               '% of a clear day'.

CF = embedded_solar / embedded_solar_capacity per half-hour (per-row, growth-detrended; the same
basis as the Entry-02 solar carpet). Night / low-sun cells (ceiling <= DAY_FLOOR) carry null —
OVERCAST is a daytime-only instrument. Entirely empirical: no clear-sky physics model (respects the
project's 'no modelled figures' rule); the reference is the clearest the slot has actually been.
"""

from __future__ import annotations

from datetime import date

from engine.capacity import solar_cf
from engine.guards import require

WEEKS = 52
PERIODS = 48
DAY_FLOOR = 0.05      # a cell whose clear-sky reference (P95) is at/below this = night/low-sun -> null
CEILING_PCTL = 0.95   # robust clear-sky reference (not the fragile raw max)
WINDOW_WEEKS = 1      # pool +/- this many weeks (wrap-around) to stabilise each cell's percentiles
MIN_SAMPLES = 20      # a pooled cell with fewer samples than this is too sparse -> null


def week_index(settlement_date: str) -> int:
    """0..51 week-of-year from an ISO date; the final week absorbs the year's tail (doy 358..366)."""
    doy = date.fromisoformat(settlement_date).timetuple().tm_yday
    return min(WEEKS - 1, (doy - 1) // 7)


def _pctl(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank percentile, matching the site's distForDays()."""
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))]


def conditional_grid(embedded_rows: list[dict], window_weeks: int = WINDOW_WEEKS,
                     min_samples: int = MIN_SAMPLES) -> list[list]:
    """grid[week][sp-1] = [p25, ceiling] (CF, rounded), or None for a night / sparse cell."""
    buckets: list[list[list[float]]] = [[[] for _ in range(PERIODS)] for _ in range(WEEKS)]
    for r in embedded_rows:
        sp = r.get("settlement_period")
        if not isinstance(sp, int) or not (1 <= sp <= PERIODS):
            continue
        cf = solar_cf(r)
        if cf is None:
            continue
        buckets[week_index(r["settlement_date"])][sp - 1].append(cf)

    grid: list[list] = []
    for w in range(WEEKS):
        row: list = []
        for sp in range(PERIODS):
            pool: list[float] = []
            for dw in range(-window_weeks, window_weeks + 1):
                pool.extend(buckets[(w + dw) % WEEKS][sp])
            if len(pool) < min_samples:
                row.append(None)
                continue
            pool.sort()
            ceiling = _pctl(pool, CEILING_PCTL)
            if ceiling <= DAY_FLOOR:               # night / low-sun: no cloud signal to give
                row.append(None)
            else:
                row.append([round(_pctl(pool, 0.25), 4), round(ceiling, 4)])
        grid.append(row)
    return grid


_BASIS = (
    "Per (week-of-year, settlement-period) cell: the empirical distribution of half-hourly solar "
    "capacity factor (embedded solar / NESO embedded-solar capacity) over the whole record, pooled "
    "across a +/-1-week window. p25 = the relative overcast line (live CF below it = the cloudiest "
    "quarter for this slot); ceiling = P95 of the cell, a robust clear-sky reference (not the raw "
    "max). The OVERCAST lamp trips below p25 and reads live CF / ceiling as '% of a clear day'. Night "
    "/ low-sun cells (ceiling <= 0.05) are null — a daytime-only instrument. Entirely empirical; no "
    "clear-sky physics model."
)
_SRC = "NESO embedded solar / NESO embedded-solar capacity (settled outturn, whole record)"
_SEAM = ("The live lamp reads NESO's embedded FORECAST capacity factor; this grid is settled OUTTURN "
         "— the same measure, a forecast-vs-settlement seam.")


def build_payload(grid: list[list], generated_utc: str, n_rows: int) -> dict:
    return {
        "basis": _BASIS, "source": _SRC, "seam_note": _SEAM,
        "generated_utc": generated_utc, "rows": n_rows,
        "weeks": WEEKS, "periods": PERIODS,
        "day_floor": DAY_FLOOR, "ceiling_pctl": CEILING_PCTL, "window_weeks": WINDOW_WEEKS,
        "grid": grid,
    }


def guard_payload(payload: dict) -> None:
    """Stage-9 build-time gate: fail loudly before solar_overcast.json is written."""
    grid = payload["grid"]
    floor = payload["day_floor"]
    require(len(grid) == WEEKS, f"solar overcast: {len(grid)} weeks, expected {WEEKS}")
    day_cells = 0
    for w, wk in enumerate(grid):
        require(len(wk) == PERIODS, f"solar overcast week {w}: {len(wk)} periods, expected {PERIODS}")
        for cell in wk:
            if cell is None:
                continue
            day_cells += 1
            require(len(cell) == 2, f"solar overcast week {w}: cell {cell} is not [p25, ceiling]")
            p25, ceiling = cell
            require(0.0 <= p25 <= ceiling <= 2.0,
                    f"solar overcast week {w}: bad cell {cell} (need 0 <= p25 <= ceiling <= 2)")
            require(ceiling > floor, f"solar overcast week {w}: day cell ceiling {ceiling} <= floor")
    require(day_cells > 200, f"solar overcast: only {day_cells} daytime cells, expected hundreds")
