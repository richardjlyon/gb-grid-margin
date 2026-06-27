"""Grid Gauge — per-source renewables capacity-factor carpets (Entry 02).

Two half-hourly capacity-factor day-grids over the rolling last 12 months — wind and solar — for the
"capacity trap" carpet plots. Cells are indexed by (settlement_date, settlement_period), so the
time-of-day axis is the local clock (BST/GMT handled for free; SP1 = 00:00 local). Wind cf =
(transmission FUELHH WIND + embedded wind) / DUKES wind nameplate (annual-step); solar cf =
embedded solar / NESO embedded-solar capacity (contemporaneous, GB/DC — the methodology-correct
denominator for the embedded-solar numerator). Joins FUELHH to the embedded store on
(settlement_date, settlement_period). Settled outturn, ~3 weeks behind the live gauge (disclosed seam).
Replaces the 2026-06-26 load-duration curve, which was illegible to a general audience.
"""

from __future__ import annotations

from datetime import date, timedelta

from engine.grid_engine import WIND
from engine.models import NameplateSeries

PERIODS = 48


def wind_cf(fuelhh_row: dict, embedded_row: dict, ns: NameplateSeries) -> float | None:
    """Wind capacity factor for one half-hour, or None if no wind capacity. Blanks coerce to 0."""
    year = int(fuelhh_row["settlement_date"][:4])
    denom = ns.capacity_for(year).wind_gw * 1000
    if denom <= 0:
        return None
    num = sum((fuelhh_row.get(f) or 0) for f in WIND) + (embedded_row.get("embedded_wind_mw") or 0)
    return num / denom


def solar_cf(embedded_row: dict) -> float | None:
    """Solar capacity factor for one half-hour (embedded solar / NESO embedded-solar capacity).

    Night cells are 0.0 (genuine zero output), NOT None. None only when capacity is absent/zero.
    """
    cap = embedded_row.get("embedded_solar_capacity_mw")
    if not cap or cap <= 0:
        return None
    return (embedded_row.get("embedded_solar_mw") or 0) / cap


def build_carpet_days(fuelhh_rows: list[dict], embedded_rows: list[dict],
                      ns: NameplateSeries, kind: str) -> list[dict]:
    """Per-day SP1..SP48 cf grid for `kind` ('wind'|'solar'), date-sorted.

    Joins FUELHH to embedded on (settlement_date, settlement_period); a period present in BOTH stores
    fills slot SP-1. DST 50-period days drop SP49/50 (clamped to the 48 grid). Days with no joined
    periods are omitted. Both carpets share the same joined key-set so their grids align.
    """
    emb_by_key = {(r["settlement_date"], r["settlement_period"]): r for r in embedded_rows}
    by_day: dict[str, list[float | None]] = {}
    for fh in fuelhh_rows:
        sp = fh["settlement_period"]
        if not (1 <= sp <= PERIODS):
            continue
        emb = emb_by_key.get((fh["settlement_date"], sp))
        if emb is None:
            continue
        cf = wind_cf(fh, emb, ns) if kind == "wind" else solar_cf(emb)
        row = by_day.setdefault(fh["settlement_date"], [None] * PERIODS)
        row[sp - 1] = round(cf, 4) if cf is not None else None
    return [{"date": d, "cf": by_day[d]} for d in sorted(by_day)]


def rolling_days(days: list[dict], span_days: int = 365) -> list[dict]:
    """The day-grids within `span_days` of the latest day (date-filtered, not count-filtered)."""
    if not days:
        return []
    cutoff = date.fromisoformat(days[-1]["date"]) - timedelta(days=span_days)
    return [d for d in days if date.fromisoformat(d["date"]) >= cutoff]


from engine.guards import require  # noqa: E402  (grouped near use)

SAT = {"wind": 0.55, "solar": 0.60}   # cf at/above which a cell is the palest (full-output) end

_BASIS_WIND = (
    "Wind capacity factor per half-hour = (transmission WIND [Elexon FUELHH, settled] + embedded "
    "wind [NESO outturn]) / DUKES total wind nameplate (annual-step). Indexed by settlement period "
    "(local half-hour). Settled, ~3 weeks behind live."
)
_BASIS_SOLAR = (
    "Solar capacity factor per half-hour = embedded solar (NESO outturn) / NESO embedded-solar "
    "capacity (contemporaneous, GB/DC) — the methodology-correct denominator for the embedded-solar "
    "numerator. Night cells are genuine 0, not gaps. Settled, ~3 weeks behind live."
)
_SEAM = ("The live gauge reads NESO's embedded FORECAST; the carpets read settled OUTTURN, ~3 weeks "
         "behind — the same measures, a forecast-vs-settlement seam.")
_SRC_WIND = "Elexon FUELHH (settled) + NESO embedded wind / DUKES 6.2 wind nameplate (annual-step)"
_SRC_SOLAR = "NESO embedded solar / NESO embedded-solar capacity (settled outturn)"


def build_payload(wind_days: list[dict], solar_days: list[dict],
                  nameplate_mw: int, generated_utc: str) -> dict:
    ref = wind_days or solar_days
    rng = ({"from": ref[0]["date"], "to": ref[-1]["date"]} if ref else {"from": None, "to": None})
    return {
        "basis_wind": _BASIS_WIND, "basis_solar": _BASIS_SOLAR, "seam_note": _SEAM,
        "source_wind": _SRC_WIND, "source_solar": _SRC_SOLAR,
        "generated_utc": generated_utc, "window": "rolling_365d", "range": rng,
        "gauge": {"nameplate_mw": nameplate_mw}, "sat": SAT,
        "wind": {"days": wind_days}, "solar": {"days": solar_days},
    }


def guard_payload(payload: dict) -> None:
    """Stage 9 build-time gate: fail loudly before capacity_carpets.json is written."""
    for kind in ("wind", "solar"):
        days = payload[kind]["days"]
        require(len(days) > 0, f"capacity carpet {kind}: no days")
        require(360 <= len(days) <= 367, f"capacity carpet {kind}: {len(days)} days, expected ~365")
        ds = [d["date"] for d in days]
        require(ds == sorted(ds) and len(ds) == len(set(ds)),
                f"capacity carpet {kind}: days not sorted/unique")
        for d in days:
            require(len(d["cf"]) == PERIODS,
                    f"capacity carpet {kind} {d['date']}: {len(d['cf'])} periods, expected {PERIODS}")
            for v in d["cf"]:
                require(v is None or 0.0 <= v <= 2.0,
                        f"capacity carpet {kind} {d['date']}: cf {v} out of [0,2]")
    require(payload["gauge"]["nameplate_mw"] > 0, "capacity gauge nameplate_mw must be > 0")
    for k, v in payload["sat"].items():
        require(0.0 < v <= 1.0, f"capacity sat {k}={v} out of (0,1]")
