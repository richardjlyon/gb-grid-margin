"""Grid Gauge site build.

Two subcommands:
- `emit-vectors`  regenerates tests/fixtures/verdict_vectors.json — the golden parity
  vectors that pin the Python engine and the JS port (site/verdict.js) to the SAME
  numbers. The expected values are produced by the frozen compute_verdict, so the
  Python side is correct-by-construction. Run by a human deliberately; NEVER in CI
  (a wrong engine edit must not be able to regenerate-and-self-certify green).
- `build`        (see Stage 3) writes site/data/latest.json from live feeds.

Run: `uv run python -m engine.build_site emit-vectors`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from engine import grid_engine
from engine.grid_engine import (
    BASE,
    NESO,
    NESO_EMBEDDED_RID,
    PVLIVE,
    compute_verdict,
    embedded_in_window,
    validate_snapshot,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "verdict_vectors.json"
LATEST_JSON = REPO / "site" / "data" / "latest.json"
SCHEMA_VERSION = 1


def _emb(solar: int, wind: int, time: str = "2026-06-25T13:30Z") -> dict:
    return {"solar_mw": solar, "wind_mw": wind, "time": time}


# Verdict vectors — each exercises a distinct corner of the denominator/grouping logic.
VERDICT_INPUTS = [
    {"name": "baseline",
     "mix": {"CCGT": 6000, "OCGT": 0, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000,
             "INTFR": 1000, "INTIRL": -300, "OTHER": 500, "NPSHYD": 100, "PS": -800},
     "embedded": _emb(10000, 1000)},
    {"name": "high_solar_midday",
     "mix": {"CCGT": 4000, "WIND": 6000, "NUCLEAR": 3500, "BIOMASS": 1500,
             "INTFR": 1500, "OTHER": 300},
     "embedded": _emb(13000, 1200)},
    {"name": "low_wind_lull",
     "mix": {"CCGT": 18000, "WIND": 800, "NUCLEAR": 3500, "BIOMASS": 2000,
             "INTFR": 3000, "OTHER": 400},
     "embedded": _emb(200, 150)},
    {"name": "net_export",
     "mix": {"CCGT": 6000, "WIND": 9000, "NUCLEAR": 3000, "BIOMASS": 2000,
             "INTFR": -1500, "INTNED": -800, "OTHER": 300},
     "embedded": _emb(1000, 500)},
    {"name": "ps_pumping",
     "mix": {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000,
             "INTFR": 700, "PS": -1200, "OTHER": 300},
     "embedded": _emb(4000, 600)},
    {"name": "nonpositive_fuel_excluded_from_other",
     "mix": {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000,
             "INTFR": 700, "COAL": 0, "OIL": -50, "OTHER": 300},
     "embedded": _emb(4000, 600)},
    {"name": "unknown_fuel_enters_other",
     "mix": {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000,
             "INTFR": 700, "UNOBTANIUM": 120},
     "embedded": _emb(4000, 600)},
    {"name": "lowercase_interconnector",
     "mix": {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000,
             "intfr": 700, "OTHER": 300},
     "embedded": _emb(4000, 600)},
    # Boundary: gas_pct = 2450 / 20000 * 100 = 12.25 exactly → round-half-even → 12.2.
    # A naive half-up JS port returns 12.3 and turns the parity gate red.
    {"name": "half_even_boundary",
     "mix": {"CCGT": 2450, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000, "INTFR": 550},
     "embedded": _emb(6000, 1000)},
]

# Snapshot-completeness vectors (validate_snapshot).
SNAPSHOT_INPUTS = [
    {"name": "complete_bucket",
     "mix": {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "INTFR": 700}, "demand": 20000},
    {"name": "incomplete_missing_ccgt",
     "mix": {"WIND": 5000, "NUCLEAR": 3000, "INTFR": 700}, "demand": 20000},
]

# Embedded-freshness vectors (embedded_in_window).
EMBEDDED_INPUTS = [
    {"name": "in_window",
     "embedded_time": "2026-06-25T14:00Z", "snapshot_time": "2026-06-25T13:40:00Z"},
    {"name": "out_of_window",
     "embedded_time": "2026-06-25T14:30Z", "snapshot_time": "2026-06-25T13:40:00Z"},
]


def emit_vectors() -> None:
    verdict_cases = [
        {"name": c["name"], "mix": c["mix"], "embedded": c["embedded"],
         "expected": compute_verdict(c["mix"], c["embedded"])}
        for c in VERDICT_INPUTS
    ]
    snapshot_cases = [
        {"name": c["name"], "mix": c["mix"], "demand": c["demand"],
         "expected_valid": validate_snapshot(c["mix"], c["demand"])}
        for c in SNAPSHOT_INPUTS
    ]
    embedded_cases = [
        {"name": c["name"], "embedded_time": c["embedded_time"],
         "snapshot_time": c["snapshot_time"],
         "expected_valid": embedded_in_window(c["embedded_time"], c["snapshot_time"])}
        for c in EMBEDDED_INPUTS
    ]
    payload = {
        "_note": "Golden parity vectors. Regenerate ONLY via `uv run python -m "
                 "engine.build_site emit-vectors` (never in CI). Expected values are "
                 "compute_verdict output — correct-by-construction.",
        "verdict_cases": verdict_cases,
        "snapshot_cases": snapshot_cases,
        "embedded_cases": embedded_cases,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {len(verdict_cases)} verdict / {len(snapshot_cases)} snapshot / "
          f"{len(embedded_cases)} embedded vectors → {FIXTURE.relative_to(REPO)}")


def import_block(net_import_mw: float, import_pct: float,
                 price_per_mwh, price_stamp) -> dict | None:
    """Build the live import-spend block for latest.json.

    Returns None when price is unavailable (published as JSON null).
    rate_per_h = max(net_import_mw, 0) × price_per_mwh  [MW × £/MWh = £/h]
    Parity-locked to site/render.js:importRatePerHour — same formula, same golden inputs.
    """
    if price_per_mwh is None:
        return None
    return {
        "rate_per_h": max(max(net_import_mw, 0.0) * price_per_mwh, 0.0),
        "net_import_mw": net_import_mw,
        "import_pct": import_pct,
        "price_per_mwh": price_per_mwh,
        "price_stamp": price_stamp,
    }


def _sp_start_hhmm(sp: int) -> str:
    """HH:MM for the start of settlement period sp (1-indexed, 30-min half-hours)."""
    minutes = (sp - 1) * 30
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def _price_stamp(settled_date: date, sp: int) -> str:
    """Format the honest stamp: 'latest settled half-hour · DD Mon, HH:MM'."""
    return (f"latest settled half-hour · "
            f"{settled_date.strftime('%-d %b')}, {_sp_start_hhmm(sp)}")


def fetch_latest_price() -> tuple:
    """Return (price_per_mwh, price_stamp) for the most recent available settled SP.

    Tries today then yesterday via system_price_history.fetch_day; takes the row with
    the highest settlement_period. Degrades to (None, None) on any error — never raises.
    """
    from engine import system_price_history
    try:
        today = datetime.now(timezone.utc).date()
        for day in [today, today - timedelta(days=1)]:
            # Short timeout: this is best-effort and must never hold the build long.
            rows = system_price_history.fetch_day(day, timeout=15)
            if rows:
                best = max(rows, key=lambda r: r["settlement_period"])
                # system_sell_price IS the single GB cash-out/imbalance price: since Ofgem P305
                # (Nov 2015) GB runs a SINGLE imbalance price, so sell == buy == "the system
                # price" — the correct figure for net imports valued at the GB system price.
                return best["system_sell_price"], _price_stamp(day, best["settlement_period"])
        return None, None
    except Exception:
        return None, None


def _atomic_write(target: Path, text: str) -> None:
    """Write text to target atomically: temp file in the same dir, fsync, os.replace.

    A half-written or failed write never replaces the existing (good) target.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".latest-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _payload(verdict: dict, snapshot: str, embedded: dict, pvlive: dict,
             indo: int, import_data=None) -> dict:
    age_min = abs(
        (datetime.fromisoformat(embedded["time"]) - datetime.fromisoformat(snapshot))
        .total_seconds()) / 60
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "import": import_data,
        "provenance": {
            "build_time_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot,
            "embedded_time": embedded["time"],
            "embedded_age_min": round(age_min, 1),
            "indo": indo,
            "pvlive_solar_mw": pvlive["solar_mw"],
            "reconcile_residual_pct": verdict.get("reconcile_residual_pct"),
            # LIVE NESO GB-DC capacities — the capacity-trap denominators (NOT nameplate).
            "solar_capacity_mw": embedded["solar_capacity_mw"],
            "wind_capacity_mw": embedded["wind_capacity_mw"],
            "source_urls": {
                "fuelinst": f"{BASE}/datasets/FUELINST/stream",
                "neso_embedded": f"{NESO}/datastore_search?resource_id={NESO_EMBEDDED_RID}",
                "indo": f"{BASE}/demand/outturn",
                "pvlive": f"{PVLIVE}/gsp/0",
            },
        },
    }


def build(target: Path = LATEST_JSON) -> int:
    """Fetch live feeds, compute + guard the verdict, write latest.json atomically.

    On ANY failure (a feed error, an incomplete snapshot, a guard trip) it prints the
    error, returns non-zero, and leaves the existing target byte-identical.
    """
    try:
        records = grid_engine.fetch_fuelinst()
        snapshot, mix = grid_engine.latest_snapshot(records)
        embedded = grid_engine.fetch_embedded_neso()
        pvlive = grid_engine.fetch_pvlive_solar()
        indo = grid_engine.fetch_indo()

        verdict = compute_verdict(mix, embedded)
        verdict["snapshot"] = snapshot

        if not validate_snapshot(mix, verdict["national_demand_mw"]):
            raise RuntimeError("incomplete FUELINST snapshot — refusing to publish")
        if not embedded_in_window(embedded["time"], snapshot):
            raise RuntimeError("embedded estimate outside the freshness window")
        grid_engine.sanity_check(verdict, pvlive["solar_mw"], indo, embedded)
    except Exception as e:  # any failure must leave the good fallback untouched
        print(f"build failed ({type(e).__name__}): {e}", file=sys.stderr)
        return 1

    # Fetch the live system price (best-effort — failure yields import: null, not a build failure).
    import_data = None
    try:
        price_per_mwh, price_stamp = fetch_latest_price()
        import_data = import_block(
            verdict["net_import_mw"], verdict["import_pct"],
            price_per_mwh, price_stamp,
        )
    except Exception as e:
        print(f"import price fetch failed ({type(e).__name__}): {e} — continuing", file=sys.stderr)

    _atomic_write(target, json.dumps(
        _payload(verdict, snapshot, embedded, pvlive, indo, import_data),
        indent=2) + "\n")
    print(f"wrote {target}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"emit-vectors", "build"}:
        print("usage: python -m engine.build_site {emit-vectors|build}", file=sys.stderr)
        return 2
    if argv[1] == "emit-vectors":
        emit_vectors()
        return 0
    return build()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
