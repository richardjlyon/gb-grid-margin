"""Grid Gauge — live data engine (v1 kickoff).

Pulls the latest FUELINST snapshot from Elexon's BMRS Insights API and computes
the live headline numbers: the verdict pair and the capacity-trap share.

No modelled figures. Every number here is measured generation from Elexon.

Known gap (flagged, not bodged): FUELINST carries no SOLAR. Embedded solar is
netted off national demand and must be ingested separately (NESO embedded
estimate / Sheffield Solar PV_Live) before solar can appear in any headline.
Until then this engine reports the transmission-metered mix and says so.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://data.elexon.co.uk/bmrs/api/v1"

# Fuel-type groupings within FUELINST.
GAS = {"CCGT", "OCGT"}
WIND = {"WIND"}
# All interconnectors are INT*; handled by prefix, not an explicit set.


def fetch_fuelinst(minutes: int = 30) -> list[dict]:
    """Return FUELINST records published in the last `minutes` minutes."""
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%MZ")
    to = now.strftime("%Y-%m-%dT%H:%MZ")
    url = f"{BASE}/datasets/FUELINST/stream?publishDateTimeFrom={frm}&publishDateTimeTo={to}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def latest_snapshot(records: list[dict]) -> tuple[str, dict[str, int]]:
    """Collapse records to the single most recent 5-min snapshot: {fuelType: MW}."""
    if not records:
        raise RuntimeError("FUELINST returned no records")
    latest = max(r["startTime"] for r in records)
    mix = {r["fuelType"]: r["generation"] for r in records if r["startTime"] == latest}
    return latest, mix


def compute_verdict(mix: dict[str, int]) -> dict:
    """Compute live shares from a FUELINST snapshot.

    Denominator = sum of all positive-flowing sources serving demand (generation
    plus net imports). Pumping load (negative PS / interconnector export) is
    excluded from the denominator, not netted into it.
    """
    wind = sum(mix.get(f, 0) for f in WIND)
    gas = sum(mix.get(f, 0) for f in GAS)
    imports = sum(v for k, v in mix.items() if k.startswith("INT"))
    nuclear = mix.get("NUCLEAR", 0)
    biomass = mix.get("BIOMASS", 0)

    supply = sum(v for v in mix.values() if v > 0)  # MW serving demand

    def pct(x: int) -> float:
        return round(x / supply * 100, 1) if supply else 0.0

    return {
        "snapshot": None,  # filled by caller
        "supply_mw": supply,
        "wind_mw": wind,
        "gas_mw": gas,
        "net_import_mw": imports,
        "nuclear_mw": nuclear,
        "biomass_mw": biomass,
        "wind_pct": pct(wind),
        "gas_pct": pct(gas),
        "import_pct": pct(imports),
        "gas_plus_imports_pct": pct(gas + imports),
        "solar_included": False,  # FUELINST has no solar — see module docstring
    }


def sanity_check(v: dict) -> None:
    """Build-time guard: fail loudly if the numbers are implausible."""
    assert v["supply_mw"] > 0, "non-positive supply"
    assert 0 <= v["wind_pct"] <= 100, f"wind_pct out of range: {v['wind_pct']}"
    assert v["gas_plus_imports_pct"] <= 100.0, "gas+imports over 100%"


def main() -> None:
    records = fetch_fuelinst()
    snapshot, mix = latest_snapshot(records)
    verdict = compute_verdict(mix)
    verdict["snapshot"] = snapshot
    sanity_check(verdict)

    print(f"Snapshot: {snapshot}  (transmission mix — excludes embedded solar)")
    print(f"  Wind & this-fuel-set : {verdict['wind_pct']}%  ({verdict['wind_mw']} MW)")
    print(f"  Gas & imports        : {verdict['gas_plus_imports_pct']}%  "
          f"({verdict['gas_mw'] + verdict['net_import_mw']} MW)")
    print(f"    of which gas       : {verdict['gas_pct']}%  ({verdict['gas_mw']} MW)")
    print(f"    of which imports   : {verdict['import_pct']}%  ({verdict['net_import_mw']} MW)")
    print(f"  Total supply         : {verdict['supply_mw']} MW")
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
