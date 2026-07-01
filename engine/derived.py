"""Grid Gauge — derived daily series (Stage 5).

Computes the year-to-date transmission-system shares and the reliability/capacity/wind
metrics from the settled history store (`data/history/*.csv`, settled FUELHH) and the
DUKES annual nameplate series (`data/nameplate_series.json`, annual-step). Written to
`site/data/*.json`. No modelled figures — every value is a settled Elexon figure
over a published DUKES capacity.

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
from datetime import datetime, timezone
from pathlib import Path

from engine import (capacity, chrome, embedded_history, import_cost, methodology, reliability,
                    solar_overcast, sources, system_price_history, wind_unreliability)
from engine.build_site import _atomic_write
from engine.grid_engine import GAS, WIND
from engine.guards import GuardError, check_nameplate_sane, check_shares_sum_100
from engine.history import read_store
from engine.models import NameplateSeries

NAMEPLATE_SERIES_PATH = Path("data/nameplate_series.json")
NAMEPLATE_ANCHOR_PATH = Path("data/nameplate.json")
INTERCONNECTORS_PATH = Path("data/interconnectors.json")
SITE_DATA = Path("site/data")

# Generation fuels that fall into "other" for the transmission-share split — the positive
# transmission fuels outside the named groups. PS (pumped-storage round-trip) is excluded
# entirely, mirroring the live denominator; interconnectors are handled as signed net flow.
_OTHER_FUELS = ("NPSHYD", "OTHER", "COAL", "OIL")

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


def build(out_dir: Path = SITE_DATA) -> int:
    """Recompute every derived series from the store and write site/data/*.json."""
    rows = read_store()
    if not rows:
        print("store empty — nothing to derive")
        return 1
    ns = load_nameplate_series()

    years = sorted({int(r["settlement_date"][:4]) for r in rows})
    latest_year = max(years)
    partial = partial_years(sorted({r["settlement_date"] for r in rows}))
    shares_by_year = {y: transmission_shares(rows, y) for y in years}

    generated = _now()

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
        for y, yd in ytd["years"].items():
            check_shares_sum_100(f"ytd {y}", yd["shares_pct"])
        check_nameplate_sane(nameplate)
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
            ("reliability_year",
             reliability.build_payload(reliability.pack(reliability.rolling_year(full)), generated)),
        ]
        rel_carpet_days = capacity.rolling_days(reliability.build_carpet_days(rows, embedded_rows))
        rel_carpet = reliability.build_carpet_payload(rel_carpet_days, generated)
        try:
            reliability.guard_carpet_payload(rel_carpet)
        except GuardError as e:
            print(f"reliability carpet build failed (GuardError): {e}", file=sys.stderr)
            return 1
        reliability_files.append(("reliability_carpet", rel_carpet))

        # Per-source gauge nameplates. Wind = DUKES total wind (annual anchor). Solar = the latest
        # NESO embedded-solar capacity in the store, so the solar gauge matches its NESO-based carpet.
        wind_nameplate_mw = round(nameplate["wind_gw"] * 1000)
        _latest_emb = max(embedded_rows, key=lambda r: (r["settlement_date"], r["settlement_period"]))
        solar_nameplate_mw = round(_latest_emb.get("embedded_solar_capacity_mw")
                                   or nameplate["solar_gw"] * 1000)
        wind_days = capacity.rolling_days(capacity.build_carpet_days(rows, embedded_rows, ns, "wind"))
        solar_days = capacity.rolling_days(capacity.build_carpet_days(rows, embedded_rows, ns, "solar"))
        cap_payload = capacity.build_payload(wind_days, solar_days,
                                             wind_nameplate_mw, solar_nameplate_mw, generated)
        try:
            capacity.guard_payload(cap_payload)
        except GuardError as e:
            print(f"capacity carpets build failed (GuardError): {e}", file=sys.stderr)
            return 1
        reliability_files.append(("capacity_carpets", cap_payload))

        # Whole-record wind unreliability (Entry 03): combined-basis daily CF, lull episodes,
        # years×day-of-year carpet. Built over the WHOLE store (not rolling), combined edge.
        wu_series = wind_unreliability.combined_daily_cf_series(rows, embedded_rows, ns)
        wu_payload = wind_unreliability.build_payload(wu_series, generated)
        try:
            wind_unreliability.guard_payload(wu_payload)
        except GuardError as e:
            print(f"wind unreliability build failed (GuardError): {e}", file=sys.stderr)
            return 1
        reliability_files.append(("wind_unreliability", wu_payload))

        # Conditional solar 'overcast' grid (Grid Conditions OVERCAST lamp): per (week, settlement
        # period) cell, the p25 overcast line + a robust P95 clear-sky reference, over the whole
        # embedded-solar record. Built from the same embedded_rows; night cells null.
        so_payload = solar_overcast.build_payload(
            solar_overcast.conditional_grid(embedded_rows), generated, len(embedded_rows))
        try:
            solar_overcast.guard_payload(so_payload)
        except GuardError as e:
            print(f"solar overcast build failed (GuardError): {e}", file=sys.stderr)
            return 1
        reliability_files.append(("solar_overcast", so_payload))
    else:
        print("embedded store empty — skipping reliability_*.json + capacity_carpets.json "
              "(run embedded_history backfill)")

    # Import cost: net interconnector flow × system (cash-out) price, daily £ carpet.
    price_rows = system_price_history.read_store()
    ic_payload = import_cost.build_payload(rows, price_rows, generated)
    if ic_payload is None:
        print("system-price store empty — skipping import_cost.json", file=sys.stderr)
    else:
        try:
            import_cost.guard_payload(ic_payload)
        except GuardError as e:
            print(f"import cost build failed (GuardError): {e}", file=sys.stderr); return 1
        reliability_files.append(("import_cost", ic_payload))

    # Homepage import-rate carpet: rolling-year half-hourly spend RATE (£/h), a Wind/Sun sibling.
    # The all-time daily totals above (import_cost.json) feed the import detail page; this small
    # rolling-year payload feeds the homepage panel. Skipped (not fatal) if the price store is empty.
    ir_payload = import_cost.build_rate_payload(rows, price_rows, generated)
    if ir_payload is None:
        print("system-price store empty — skipping import_rate.json", file=sys.stderr)
    else:
        try:
            import_cost.guard_rate_payload(ir_payload)
        except GuardError as e:
            print(f"import rate build failed (GuardError): {e}", file=sys.stderr); return 1
        reliability_files.append(("import_rate", ir_payload))

    # Homepage import-power carpet: net imports as a share of interconnector capacity (the §02 sibling).
    # Capacities (per DESNZ) come from data/interconnectors.json; the per-half-hour denominator is the
    # capacity of the legs reporting that half-hour, so it tracks the fleet as it grew.
    interconnectors = json.loads(INTERCONNECTORS_PATH.read_text())
    caps = {code: link["capacity_mw"] for code, link in interconnectors["links"].items()}
    ip_payload = import_cost.build_power_payload(
        rows, caps, interconnectors["total_capacity_mw"], generated)
    if ip_payload is None:
        print("no interconnector half-hours — skipping import_power.json", file=sys.stderr)
    else:
        try:
            import_cost.guard_power_payload(ip_payload)
        except GuardError as e:
            print(f"import power build failed (GuardError): {e}", file=sys.stderr); return 1
        reliability_files.append(("import_power", ip_payload))

    # Provenance registry: the single author of every figure's source + basis + caveats. Emitted
    # always (not gated on the embedded store) — the methodology page + provenance gate depend on it.
    sources_payload = sources.build_payload(generated)
    try:
        sources.guard_payload(sources_payload)
    except GuardError as e:
        print(f"sources build failed (GuardError): {e}", file=sys.stderr); return 1
    reliability_files.append(("sources", sources_payload))

    # Post-mortem scenarios: render the authored taxonomy against the settled stores into
    # site/post-mortem/*.html + scenario_<slug>.json (skips any scenario not yet covered by the
    # embedded store, non-fatal).
    from engine import scenarios as _scenarios
    try:
        scenario_named = _scenarios.build_all(rows, embedded_rows, price_rows, ns, caps, generated)
    except GuardError as e:
        print(f"scenario build failed (GuardError): {e}", file=sys.stderr); return 1
    reliability_files.extend(scenario_named)
    if scenario_named:
        print(f"generated {len(scenario_named)} post-mortem page(s)")

    # Regenerate the methodology page's source cards from the same registry (build-time, static).
    methodology.build(sources_payload)
    print("regenerated site/methodology.html source cards")

    # Keep the shared page chrome (masthead/nav, footer, head assets) single-sourced across pages.
    chrome.build()

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in [("ytd_shares", ytd), ("nameplate", nameplate),
                          *reliability_files]:
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
