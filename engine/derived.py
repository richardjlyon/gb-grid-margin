"""Grid Gauge — derived daily series (Stage 5).

Computes everything the daily cards need from the settled history store
(`data/history/*.csv`, settled FUELHH) and the DUKES annual nameplate series
(`data/nameplate_series.json`, annual-step): the wind stripe, the failure counters,
the records, and the year-to-date transmission-system shares. Written to
`site/data/*.json`. No modelled figures — every value is a settled Elexon figure
over a published DUKES capacity.

Two methodology decisions are baked in here (Richard-confirmed 2026-06-25; see
engine/NOTES.md §8). They are the difference between a figure that survives a hostile
read and one that does not, so each output file carries its `basis` disclosure inline.

CAPACITY-FACTOR BASIS — a conservative lower bound. FUELHH `WIND` is transmission-
metered only; it excludes the embedded (distribution-connected) wind NESO estimates
separately. The denominator is DUKES TOTAL UK wind nameplate (annual-step). Dividing a
transmission-only numerator by a total-capacity denominator makes the daily wind
capacity factor a LOWER BOUND — the true output/total-installed ratio is higher, because
embedded wind output is missing from the top. The bias direction (understatement) is
fixed and disclosed; it is never presented as the literal load factor.

The CF is a mean-power figure: mean(WIND MW over the day's present periods) / nameplate
MW. For a normal 48-period day this equals daily energy ÷ (capacity × 24 h); on a short
clock-change day (46 periods) or a known-gap day it normalises rather than penalising
the day for fewer half-hours.

YTD SHARES BASIS — transmission system, not national demand. The store is settled FUELHH
only and carries no embedded solar/wind, so a national-demand share (as the live verdict
uses) is impossible from settled data. The shares here are transmission generation + net
interconnectors over transmission supply, pumped-storage round-trip and embedded both
excluded — internally consistent, but NOT comparable to the live national-demand verdict.
Embedded solar is absent by construction; the file says so.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from engine import capacity, embedded_history, reliability
from engine.build_site import _atomic_write
from engine.grid_engine import GAS, WIND
from engine.guards import (
    GuardError,
    check_cf_range,
    check_counts_monotonic,
    check_dates_sorted_unique,
    check_nameplate_sane,
    check_shares_sum_100,
    require,
)
from engine.history import read_store
from engine.models import NameplateSeries

NAMEPLATE_SERIES_PATH = Path("data/nameplate_series.json")
NAMEPLATE_ANCHOR_PATH = Path("data/nameplate.json")
SITE_DATA = Path("site/data")

BELOW_10PCT = 0.10
BELOW_5PCT = 0.05

# Generation fuels that fall into "other" for the transmission-share split — the positive
# transmission fuels outside the named groups. PS (pumped-storage round-trip) is excluded
# entirely, mirroring the live denominator; interconnectors are handled as signed net flow.
_OTHER_FUELS = ("NPSHYD", "OTHER", "COAL", "OIL")

_BASIS_CF = (
    "Daily wind capacity factor = mean(transmission WIND MW over the day's present "
    "periods) / total UK wind nameplate (DUKES 6.2, annual-step). CONSERVATIVE LOWER "
    "BOUND: FUELHH WIND is transmission-metered only and excludes embedded "
    "(distribution-connected) wind output, while the denominator is total installed wind "
    "— so the true load factor is higher than shown. Mean-power basis normalises short "
    "clock-change and known-gap days. Source: Elexon FUELHH (settled) / DUKES 6.2."
)
# Travels with any file that ships CROSS-YEAR figures (the per-year trend, the all-time
# records, the per-year counters). The lower-bound understatement is NOT uniform across
# years — it is largest early (more onshore wind was embedded, off FUELHH) and shrinks as
# offshore, all transmission-metered, grows. So the apparent year-on-year rise is largely a
# denominator-mix artifact, not a real change in wind performance, and all-time extremes
# cluster in the earliest (most-understated) years. Within-year daily variability is honest;
# cross-year *level* comparison is confounded and must be read with this caveat, never sold
# as a trend. See engine/NOTES.md §8.
_CROSS_YEAR_CAVEAT = (
    "Cross-year comparison is confounded: the lower-bound understatement is largest in early "
    "years (more wind was embedded/off-FUELHH then) and shrinks as transmission-metered "
    "offshore grows, so the year-on-year rise is largely a denominator-mix artifact — not a "
    "real improvement in wind output — and all-time records skew to the earliest years. Read "
    "within-year variability, not the cross-year level. See engine/NOTES.md §8."
)
_BASIS_SHARES = (
    "Transmission-system mix: settled FUELHH generation + net interconnector flow over "
    "transmission supply. Pumped-storage round-trip and embedded solar/wind are both "
    "excluded. This is NOT the live national-demand verdict and must not be compared to "
    "it: embedded solar is netted off national demand and cannot appear in a settled-data "
    "transmission share. Source: Elexon FUELHH (settled)."
)


# --- loading ----------------------------------------------------------------

def load_nameplate_series(path: Path = NAMEPLATE_SERIES_PATH) -> NameplateSeries:
    return NameplateSeries.model_validate_json(Path(path).read_text())


def group_by_day(rows: list[dict]) -> dict[str, list[dict]]:
    """Partition store rows by settlement_date."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["settlement_date"], []).append(r)
    return out


def partial_years(dates: list[str]) -> list[int]:
    """Years whose observed span does not cover the whole calendar year, ascending.

    A year is partial if its earliest observed date is after 1 Jan or its latest is before
    31 Dec — e.g. the current year (data stops a few settled days back) or a truncated edge
    year. Flagged so a seasonally-incomplete year (a winter-heavy YTD) is never read as a
    record against full years.
    """
    span: dict[int, list[str]] = {}
    for d in dates:
        span.setdefault(int(d[:4]), []).append(d)
    out = []
    for y in sorted(span):
        lo, hi = min(span[y]), max(span[y])
        if lo > f"{y}-01-01" or hi < f"{y}-12-31":
            out.append(y)
    return out


# --- wind capacity factor ---------------------------------------------------

def day_mean_mw(day_rows: list[dict], series: str = "WIND") -> float | None:
    """Mean MW for a series over a day's present (non-blank) periods, or None if all blank."""
    vals = [r[series] for r in day_rows if r.get(series) is not None]
    return sum(vals) / len(vals) if vals else None


def wind_cf_for_day(day_rows: list[dict], capacity_gw: float) -> float:
    """Mean-power wind capacity factor for one day against a total-nameplate denominator."""
    mean_mw = day_mean_mw(day_rows, "WIND")
    return (mean_mw or 0.0) / (capacity_gw * 1000)


def wind_cf_series(rows: list[dict], ns: NameplateSeries) -> list[dict]:
    """Per-day wind CF for the whole store, date-ascending, annual-step nameplate."""
    out = []
    for day, day_rows in sorted(group_by_day(rows).items()):
        year = int(day[:4])
        cap = ns.capacity_for(year).wind_gw
        mean_mw = day_mean_mw(day_rows, "WIND")
        if mean_mw is None:
            continue
        out.append({
            "date": day,
            "cf": round(mean_mw / (cap * 1000), 4),
            "mean_mw": round(mean_mw, 1),
            "capacity_gw": cap,
        })
    return out


# --- failure counters -------------------------------------------------------

def failure_counters(cf_series: list[dict]) -> dict[int, dict]:
    """Per calendar year: days observed and days below the 10% / 5% CF thresholds.

    Thresholds are strict less-than: exactly 10% is not below 10%.
    """
    out: dict[int, dict] = {}
    for s in cf_series:
        year = int(s["date"][:4])
        c = out.setdefault(year, {"days_observed": 0, "below_10pct": 0, "below_5pct": 0})
        c["days_observed"] += 1
        if s["cf"] < BELOW_10PCT:
            c["below_10pct"] += 1
        if s["cf"] < BELOW_5PCT:
            c["below_5pct"] += 1
    return out


# --- records ----------------------------------------------------------------

_ONE_DAY = timedelta(days=1)


def records(cf_series: list[dict]) -> dict:
    """All-time lowest/highest daily CF and the longest calendar-consecutive sub-10% run."""
    if not cf_series:
        return {"lowest_cf_day": None, "highest_cf_day": None,
                "longest_sub10pct_run": {"start": None, "end": None, "days": 0}}

    lowest = min(cf_series, key=lambda s: s["cf"])
    highest = max(cf_series, key=lambda s: s["cf"])

    best = {"start": None, "end": None, "days": 0}
    run_start = None
    prev = None
    run_len = 0
    for s in sorted(cf_series, key=lambda s: s["date"]):
        below = s["cf"] < BELOW_10PCT
        adjacent = prev is not None and (
            date.fromisoformat(s["date"]) - date.fromisoformat(prev) == _ONE_DAY)
        if below and adjacent and run_len > 0:
            run_len += 1
        elif below:
            run_start = s["date"]
            run_len = 1
        else:
            run_len = 0
        if run_len > best["days"]:
            best = {"start": run_start, "end": s["date"], "days": run_len}
        prev = s["date"]

    return {
        "lowest_cf_day": {k: lowest[k] for k in ("date", "cf", "mean_mw", "capacity_gw")},
        "highest_cf_day": {k: highest[k] for k in ("date", "cf", "mean_mw", "capacity_gw")},
        "longest_sub10pct_run": best,
    }


# --- transmission-system shares ---------------------------------------------

def _sum_mwh(rows: list[dict], series: str) -> float:
    """Energy (MWh) for a series over the given rows = Σ(MW × 0.5), blanks skipped."""
    return sum(r[series] for r in rows if r.get(series) is not None) * 0.5


def transmission_shares(rows: list[dict], year: int) -> dict:
    """Transmission-system fuel shares for one calendar year (see module docstring).

    supply = wind + gas + nuclear + biomass + other + net interconnector imports.
    Pumped storage is excluded entirely; embedded solar/wind do not exist in the store.
    Shares sum to 100% by construction.
    """
    year_rows = [r for r in rows if r["settlement_date"][:4] == str(year)]

    wind = sum(_sum_mwh(year_rows, f) for f in WIND)
    gas = sum(_sum_mwh(year_rows, f) for f in GAS)
    nuclear = _sum_mwh(year_rows, "NUCLEAR")
    biomass = _sum_mwh(year_rows, "BIOMASS")
    other = sum(_sum_mwh(year_rows, f) for f in _OTHER_FUELS)
    net_imports = sum(
        r[k] for r in year_rows for k in r
        if k.upper().startswith("INT") and r.get(k) is not None) * 0.5

    group_mwh = {"wind": wind, "gas": gas, "nuclear": nuclear, "biomass": biomass,
                 "other": other, "net_imports": net_imports}
    supply = sum(group_mwh.values())
    shares = {g: (v / supply * 100 if supply else 0.0) for g, v in group_mwh.items()}

    return {
        "year": year,
        "supply_mwh": supply,
        "group_mwh": group_mwh,
        "shares_pct": shares,
    }


# --- build site/data/*.json -------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def guard_outputs(stripe: dict, counters_out: dict, records_out: dict,
                  ytd: dict, nameplate: dict) -> None:
    """Stage 9 build-time gate: fail loudly before any derived figure is written.

    Checks every public derived figure against engine.guards — the stripe's daily
    CF range and date order, the failure counters' monotonicity, each year's
    transmission shares summing to 100%, the all-time records' internal order, and
    the nameplate denominators' sanity. Raises GuardError (caught by build) on any
    breach. A negative net-import share is allowed by construction (see guards).
    """
    days = stripe["days"]
    require(len(days) > 0, "stripe has no days — empty derived series")
    check_dates_sorted_unique([d["date"] for d in days])
    for d in days:
        check_cf_range(d["date"], d["cf"])

    for y, c in counters_out["years"].items():
        check_counts_monotonic(int(y), c["days_observed"], c["below_10pct"],
                               c["below_5pct"])

    for y, yd in ytd["years"].items():
        check_shares_sum_100(f"ytd {y}", yd["shares_pct"])

    low = records_out["lowest_cf_day"]
    high = records_out["highest_cf_day"]
    if low and high:
        check_cf_range(low["date"], low["cf"])
        check_cf_range(high["date"], high["cf"])
        require(low["cf"] <= high["cf"],
                f"records: lowest cf {low['cf']} exceeds highest {high['cf']}")
    require(records_out["longest_sub10pct_run"]["days"] >= 0,
            "records: negative longest sub-10% run length")

    check_nameplate_sane(nameplate)


def build(out_dir: Path = SITE_DATA) -> int:
    """Recompute every derived series from the store and write site/data/*.json."""
    rows = read_store()
    if not rows:
        print("store empty — nothing to derive")
        return 1
    ns = load_nameplate_series()

    cf = wind_cf_series(rows, ns)
    counters = failure_counters(cf)
    recs = records(cf)

    years = sorted({int(s["date"][:4]) for s in cf})
    latest_year = max(years)
    partial = partial_years([s["date"] for s in cf])
    shares_by_year = {y: transmission_shares(rows, y) for y in years}

    per_year_mean = {
        str(y): round(sum(s["cf"] for s in cf if int(s["date"][:4]) == y)
                      / max(1, sum(1 for s in cf if int(s["date"][:4]) == y)), 4)
        for y in years
    }
    mean_cf = round(sum(s["cf"] for s in cf) / len(cf), 4) if cf else 0.0

    generated = _now()
    source_cf = "Elexon FUELHH (settled) / DUKES 6.2 nameplate (annual-step)"

    stripe = {
        "basis": _BASIS_CF,
        "cross_year_caveat": _CROSS_YEAR_CAVEAT,
        "metric": "Daily wind capacity factor (conservative lower bound)",
        "source": source_cf,
        "generated_utc": generated,
        "range": {"from": cf[0]["date"], "to": cf[-1]["date"]},
        "partial_years": partial,
        "mean_cf": mean_cf,
        "per_year_mean_cf": per_year_mean,
        "days": [{"date": s["date"], "cf": s["cf"]} for s in cf],
    }

    counters_out = {
        "basis": _BASIS_CF,
        "cross_year_caveat": _CROSS_YEAR_CAVEAT,
        "metric": "Days with daily wind capacity factor below 10% / 5% of total nameplate",
        "source": source_cf,
        "generated_utc": generated,
        "thresholds": {"below_10pct": BELOW_10PCT, "below_5pct": BELOW_5PCT},
        "latest_year": latest_year,
        "partial_years": partial,
        "years": {str(y): counters[y] for y in years},
    }

    records_out = {
        "basis": _BASIS_CF,
        "cross_year_caveat": _CROSS_YEAR_CAVEAT,
        "records_note": ("All-time extremes over the whole settled store. Because the "
                         "lower-bound understatement is largest in early years, the record "
                         "low and the longest sub-10% run land in the earliest, most-"
                         "understated years — read them with the cross_year_caveat."),
        "source": source_cf,
        "generated_utc": generated,
        **recs,
    }

    ytd = {
        "basis": _BASIS_SHARES,
        "source": "Elexon FUELHH (settled)",
        "generated_utc": generated,
        "no_solar_note": ("Embedded solar is netted off national demand and absent from "
                          "settled FUELHH; it cannot appear in a settled-data transmission "
                          "share."),
        "signed_imports_note": ("net_imports is a signed net flow: a net-export year is "
                                "negative (e.g. 2022). Shares still sum to 100% but a pie/"
                                "stacked chart must render net interconnectors as a signed "
                                "bar, not a wedge."),
        "latest_year": latest_year,
        "partial_years": partial,
        "years": {
            str(y): {
                "supply_mwh": round(shares_by_year[y]["supply_mwh"], 1),
                "shares_pct": {g: round(v, 2)
                               for g, v in shares_by_year[y]["shares_pct"].items()},
                "partial": (y in partial),
            }
            for y in years
        },
    }

    # Publish the DUKES nameplate anchor to the web root so the capacity-trap card has a
    # sound, dated denominator (the live NESO embedded-wind capacity is embedded-only —
    # it would read ~146% of capacity; see engine/NOTES.md §2 and §8).
    nameplate = json.loads(NAMEPLATE_ANCHOR_PATH.read_text())

    try:
        guard_outputs(stripe, counters_out, records_out, ytd, nameplate)
    except GuardError as e:
        print(f"derived build failed (GuardError): {e}", file=sys.stderr)
        return 1

    # Reliability stripe series (Stage B): national reliable share per half-hour, from the
    # FUELHH store joined to the embedded store. Skipped (not fatal) if embedded isn't built.
    embedded_rows = embedded_history.read_store()
    reliability_files: list[tuple[str, dict]] = []
    if embedded_rows:
        full = reliability.build_series(rows, embedded_rows)
        reliability_files = [
            ("reliability_all", reliability.build_payload(reliability.pack(full), generated)),
            ("reliability_year",
             reliability.build_payload(reliability.pack(reliability.rolling_year(full)), generated)),
        ]

        cf_full = capacity.build_cf_series(rows, embedded_rows, ns)
        cf_window = capacity.rolling_year(cf_full)
        cap_payload = capacity.build_payload(
            capacity.load_duration_curve(cf_window),
            capacity.summary_stats(cf_window), cf_window, generated, ns)
        try:
            capacity.guard_payload(cap_payload)
        except GuardError as e:
            print(f"capacity build failed (GuardError): {e}", file=sys.stderr)
            return 1
        reliability_files.append(("capacity_curve", cap_payload))
    else:
        print("embedded store empty — skipping reliability_*.json + capacity_curve.json "
              "(run embedded_history backfill)")

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in [("stripe", stripe), ("counters", counters_out),
                          ("records", records_out), ("ytd_shares", ytd),
                          ("nameplate", nameplate), *reliability_files]:
        _atomic_write(out_dir / f"{name}.json", json.dumps(payload, indent=2) + "\n")
        print(f"wrote {out_dir / f'{name}.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] != "build":
        print("usage: python -m engine.derived build", file=sys.stderr)
        return 2
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
