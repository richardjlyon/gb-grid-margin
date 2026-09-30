"""Grid Gauge — live data engine (v1).

Pulls the latest FUELINST snapshot from Elexon's BMRS Insights API plus the NESO
embedded solar/wind estimate, and computes the live headline numbers: the verdict
pair and the capacity-trap share, as shares of national demand.

No modelled figures. Every number traces to Elexon or NESO:
- transmission generation + interconnector flows: Elexon FUELINST (5-min).
- embedded solar + embedded wind: NESO embedded forecast (the figure NESO nets
  off national demand; CORS-open, so the live browser layer can fetch it too).
- demand reconciliation: Elexon demand outturn (INDO — national demand).

Two build-time guards defend the published figures (see sanity_check):
- cross-check: NESO embedded solar must agree with Sheffield Solar PV_Live (the
  independent GB outturn series) within tolerance. PV_Live is server-side only —
  it sends no CORS header, so it cannot be the live figure, only the auditor.
- reconciliation: the supply-side denominator must agree with Elexon INDO +
  embedded within tolerance.

Denominator = national demand, defined as:
    national_demand = positive transmission generation (excl. interconnectors and
                      pumped storage)
                    + net interconnector imports (sum of all INT*, exports net off)
                    + embedded solar
                    + embedded wind
Pumped-storage pumping (negative PS) is demand, not supply, so it is excluded.
Shares sum to 100% by construction. See engine/NOTES.md.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

from engine.models import (
    DemandOutturnRow,
    EmbeddedRow,
    FuelInstRecord,
    PvLiveResponse,
)

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
NESO = "https://api.neso.energy/api/3/action"
PVLIVE = "https://api.solar.sheffield.ac.uk/pvlive/api/v4"

# NESO embedded solar/wind forecast — live (rolling) resource.
NESO_EMBEDDED_RID = "db6c038f-98af-4570-ab60-24d71ebd0ae5"

# Fuel-type groupings within FUELINST.
GAS = {"CCGT", "OCGT"}
WIND = {"WIND"}
# Interconnectors are INT*; pumped storage is PS — both handled specially below.

# Build-time guard tolerances.
SOLAR_CROSSCHECK_TOL = 0.10   # NESO vs PV_Live solar — tight; tests the embedded feed
# Below this PV_Live reading the relative check does not bind: at dawn/dusk solar is a
# few hundred MW on a ~22 GW fleet, where forecast-vs-outturn error routinely exceeds
# 10% while the absolute gap is headline-irrelevant noise (2026-08-11: NESO 256 vs
# PV_Live 217 = 18% = 39 MW). The tripwire targets a zeroed/doubled/wrong-unit feed,
# which only distorts published figures once solar is material.
SOLAR_CROSSCHECK_FLOOR_MW = 1000
# Reconciliation is loose by design. The supply reconstruction runs ~0.5-1 GW above
# INDO (transmission losses + FUELINST's 5-min snapshot vs INDO's 30-min settlement
# average); that offset is roughly demand-independent, so as a fraction it grows when
# demand is low (a winter night). INDO (national demand) is the right reference, NOT
# ITSDO: ITSDO additionally counts interconnector exports, station load and PS pumping
# as demand, so it diverged from this national-demand reconstruction by the export
# volume on an export night and false-alarmed (engine/NOTES.md §3). This guard exists
# to catch a gross feed failure (zeroed/doubled/wrong-unit), not to certify accuracy —
# the headline-moving solar figure is policed separately by the tight PV_Live
# cross-check. The residual is reported (reconcile_residual_pct) rather than hidden.
RECONCILE_TOL = 0.12          # denominator vs INDO + embedded

# Snapshot/embedded preconditions — mirrored byte-for-byte in site/verdict.js so the
# browser refuses a structurally-valid-but-incomplete feed exactly as the build does.
REQUIRED_FUELS = {"CCGT", "WIND", "NUCLEAR"}   # must be present in a complete FUELINST bucket
DEMAND_FLOOR_MW = 15000        # a plausible-floor; below this the bucket is partial
EMBEDDED_WINDOW_MIN = 30       # embedded estimate must be within this of the snapshot


def validate_snapshot(mix: dict[str, int], demand: int) -> bool:
    """True only if the FUELINST bucket looks complete (not a partial publish)."""
    if not REQUIRED_FUELS <= mix.keys():
        return False
    if not any(k.upper().startswith("INT") for k in mix):
        return False
    return demand >= DEMAND_FLOOR_MW


def embedded_in_window(embedded_time: str, snapshot_time: str) -> bool:
    """True if the embedded estimate is within EMBEDDED_WINDOW_MIN of the snapshot.

    Fail-closed: an unparseable timestamp returns False (treated as stale), never fresh.
    """
    try:
        emb = datetime.fromisoformat(embedded_time)
        snap = datetime.fromisoformat(snapshot_time)
    except ValueError:
        return False
    return abs((emb - snap).total_seconds()) <= EMBEDDED_WINDOW_MIN * 60


def _get_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "grid-gauge/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# --- Elexon FUELINST -------------------------------------------------------

def fetch_fuelinst(minutes: int = 180) -> list[FuelInstRecord]:
    """Return FUELINST records published in the last `minutes` minutes.

    180 (mirroring site/live.js FUELINST_WINDOW_MIN) so the window also holds the bucket
    at the INDO period's midpoint — INDO publishes ~30-60 min behind real time, and the
    reconciliation must compare like times (see sanity_check).
    """
    now = datetime.now(timezone.utc)
    frm = now.replace(second=0, microsecond=0)
    frm = frm.fromtimestamp(now.timestamp() - minutes * 60, timezone.utc)
    fmt = "%Y-%m-%dT%H:%MZ"
    url = (f"{BASE}/datasets/FUELINST/stream"
           f"?publishDateTimeFrom={frm.strftime(fmt)}"
           f"&publishDateTimeTo={now.strftime(fmt)}")
    data = _get_json(url)
    assert isinstance(data, list), "FUELINST stream did not return a list"
    return [FuelInstRecord.model_validate(r) for r in data]


def latest_snapshot(records: list[FuelInstRecord]) -> tuple[str, dict[str, int]]:
    """Collapse records to the single most recent 5-min snapshot: {fuelType: MW}."""
    if not records:
        raise RuntimeError("FUELINST returned no records")
    latest = max(r.start_time for r in records)
    mix = {r.fuel_type: r.generation for r in records if r.start_time == latest}
    return latest, mix


def snapshot_at(records: list[FuelInstRecord], anchor: datetime) -> tuple[str, dict[str, int]]:
    """Collapse records to the 5-min snapshot nearest `anchor`: (time, {fuelType: MW}).

    Mirrored in site/verdict.js snapshotAt — the reconciliation guard on both sides
    reconstructs demand at the reference's own time, not at "now".
    """
    if not records:
        raise RuntimeError("FUELINST returned no records")
    nearest = min(
        (r.start_time for r in records),
        key=lambda t: abs(datetime.fromisoformat(t) - anchor))
    mix = {r.fuel_type: r.generation for r in records if r.start_time == nearest}
    return nearest, mix


# --- NESO embedded solar/wind ----------------------------------------------

def fetch_embedded_rows() -> list[EmbeddedRow]:
    """Return the full NESO embedded forecast horizon, one fetch.

    limit=1000 + explicit sort, mirroring site/live.js: limit=100 with no sort relied on
    NESO keeping _id=1 pinned to ~now, and a late republish silently dropped the row
    nearest the anchor.
    """
    url = (f"{NESO}/datastore_search"
           f"?resource_id={NESO_EMBEDDED_RID}&limit=1000&sort=_id")
    payload = _get_json(url)
    assert isinstance(payload, dict), "NESO datastore_search did not return an object"
    raw = payload["result"]["records"]
    if not raw:
        raise RuntimeError("NESO embedded forecast returned no records")
    return [EmbeddedRow.model_validate(r) for r in raw]


def pick_embedded(rows: list[EmbeddedRow], at: datetime) -> dict:
    """Return the embedded estimate nearest `at`: {time, solar, wind, *_capacity}."""
    row = min(rows, key=lambda r: abs((r.when() - at).total_seconds()))
    return {
        "time": f"{row.date_gmt[:10]}T{row.time_gmt}Z",
        "solar_mw": row.solar_mw,
        "wind_mw": row.wind_mw,
        "solar_capacity_mw": row.solar_capacity_mw,
        "wind_capacity_mw": row.wind_capacity_mw,
    }


# --- Sheffield Solar PV_Live (cross-check only) -----------------------------

def fetch_pvlive_solar() -> dict:
    """Return the latest national PV_Live outturn: {generation_mw, time}."""
    data = _get_json(f"{PVLIVE}/gsp/0")
    assert isinstance(data, dict), "PV_Live did not return an object"
    resp = PvLiveResponse.model_validate(data)
    return {"time": resp.time(), "solar_mw": resp.solar_mw()}


# --- Elexon demand (reconciliation only) ------------------------------------

def fetch_indo() -> tuple[int, str]:
    """Return the latest Initial (National) Demand Outturn: (MW, period startTime).

    Picks the most recent row carrying a non-null INDO — Elexon occasionally publishes
    a present-but-null demand for the very latest period, which must not abort the build.
    The startTime is needed because INDO lags real time by ~30-60 min: the reconciliation
    must compare it against a reconstruction for the SAME half-hour, not for "now".
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = (f"{BASE}/demand/outturn"
           f"?settlementDateFrom={today}&settlementDateTo={today}")
    payload = _get_json(url)
    assert isinstance(payload, dict), "demand/outturn did not return an object"
    rows = [DemandOutturnRow.model_validate(r) for r in payload["data"]]
    for row in reversed(rows):
        if row.indo is not None:
            return row.indo, row.start_time
    raise RuntimeError("demand/outturn returned no non-null INDO value")


# --- Verdict ----------------------------------------------------------------

def compute_verdict(mix: dict[str, int], embedded: dict) -> dict:
    """Compute live shares of national demand from FUELINST + embedded estimate."""
    solar = embedded["solar_mw"]
    embedded_wind = embedded["wind_mw"]

    trans_wind = sum(mix.get(f, 0) for f in WIND)
    wind = trans_wind + embedded_wind
    gas = sum(mix.get(f, 0) for f in GAS)
    net_imports = sum(v for k, v in mix.items() if k.upper().startswith("INT"))
    nuclear = mix.get("NUCLEAR", 0)
    biomass = mix.get("BIOMASS", 0)

    # Positive transmission generation excluding interconnectors and pumped storage.
    # INT* is matched case-insensitively so the JS port (toUpperCase) cannot diverge.
    other = sum(v for k, v in mix.items()
                if v > 0 and not k.upper().startswith("INT") and k != "PS"
                and k not in WIND | GAS | {"NUCLEAR", "BIOMASS"})

    # National demand = supply serving it. Pumped-storage pumping (negative PS) is
    # demand, so it is not in this sum; interconnector exports net off via net_imports.
    demand = (trans_wind + gas + nuclear + biomass + other
              + net_imports + solar + embedded_wind)

    def pct(x: int) -> float:
        return round(x / demand * 100, 1) if demand else 0.0

    # The reliability cut: firm, dispatchable, weather-independent generation Britain can
    # call on (gas + nuclear + biomass + other firm fuels) vs the sources that fall away
    # together in a synoptic calm (wind + solar + imports). These partition demand exactly.
    firm = gas + nuclear + biomass + other
    notfirm = wind + solar + net_imports

    return {
        "snapshot": None,        # filled by caller
        "embedded_time": embedded["time"],
        "national_demand_mw": demand,
        "wind_mw": wind,
        "solar_mw": solar,
        "gas_mw": gas,
        "net_import_mw": net_imports,
        "nuclear_mw": nuclear,
        "biomass_mw": biomass,
        "other_mw": other,
        "firm_mw": firm,
        "notfirm_mw": notfirm,
        "wind_pct": pct(wind),
        "solar_pct": pct(solar),
        "gas_pct": pct(gas),
        "import_pct": pct(net_imports),
        "nuclear_pct": pct(nuclear),
        "biomass_pct": pct(biomass),
        "other_pct": pct(other),
        "firm_pct": pct(firm),
        "notfirm_pct": pct(notfirm),
        "gas_plus_imports_pct": pct(gas + net_imports),
        "renewables_pct": pct(wind + solar),
        "solar_included": True,
    }


def sanity_check(v: dict, pvlive_solar: float, neso_solar_at_pvlive: float | None,
                 indo: int, recon_demand_mw: float | None, recon_embedded: dict | None) -> None:
    """Build-time guards: fail loudly if a published figure is implausible.

    Both external references (PV_Live, INDO) lag real time by ~30-60 min, so each is
    compared against OUR value for the reference's own timestamp — never against "now".
    Comparing now-vs-lagged tripped both guards every steep morning ramp (the Aug 2026
    four-day fallback outage). A reference that cannot be time-aligned arrives as None
    and that check is skipped: these are gross-feed-failure tripwires, not freshness
    gates — freshness is policed by embedded_in_window/validate_snapshot.
    """
    assert v["national_demand_mw"] > 0, "non-positive national demand"
    assert 0 <= v["wind_pct"] <= 100, f"wind_pct out of range: {v['wind_pct']}"
    assert v["gas_plus_imports_pct"] <= 100.0, "gas+imports over 100%"

    # Cross-check: NESO embedded solar vs Sheffield PV_Live, both at PV_Live's timestamp.
    if pvlive_solar >= SOLAR_CROSSCHECK_FLOOR_MW and neso_solar_at_pvlive is not None:
        diff = abs(neso_solar_at_pvlive - pvlive_solar) / pvlive_solar
        assert diff <= SOLAR_CROSSCHECK_TOL, (
            f"solar cross-check failed: NESO {neso_solar_at_pvlive} vs "
            f"PV_Live {pvlive_solar:.0f} ({diff:.1%} > {SOLAR_CROSSCHECK_TOL:.0%})")

    # Reconciliation: supply-side reconstruction vs Elexon INDO (national demand) +
    # embedded, all evaluated at the INDO period's midpoint. PARITY-LOCKED with
    # site/live.js tryLive.
    v["reconcile_residual_pct"] = None
    if recon_demand_mw is not None and recon_embedded is not None:
        expected = indo + recon_embedded["solar_mw"] + recon_embedded["wind_mw"]
        if expected > 0:
            diff = abs(recon_demand_mw - expected) / expected
            v["reconcile_residual_pct"] = round(diff * 100, 1)
            assert diff <= RECONCILE_TOL, (
                f"demand reconciliation failed: computed {recon_demand_mw} vs "
                f"INDO+embedded {expected} ({diff:.1%} > {RECONCILE_TOL:.0%})")


def aligned_refs(records: list[FuelInstRecord], embedded_rows: list[EmbeddedRow],
                 pvlive_time: str, indo_start: str) -> tuple[float | None, float | None, dict | None]:
    """Time-align the two external references for sanity_check.

    Returns (neso_solar_at_pvlive, recon_demand_mw, recon_embedded); None where the
    nearest available data is further than EMBEDDED_WINDOW_MIN from the reference's
    own time (that check is then skipped rather than compared across a ramp).
    """
    neso_solar = None
    emb_at_pvlive = pick_embedded(embedded_rows, datetime.fromisoformat(pvlive_time))
    if embedded_in_window(emb_at_pvlive["time"], pvlive_time):
        neso_solar = emb_at_pvlive["solar_mw"]

    recon_demand, recon_embedded = None, None
    mid = datetime.fromisoformat(indo_start) + timedelta(minutes=15)
    mid_iso = mid.strftime("%Y-%m-%dT%H:%M:%SZ")
    recon_time, recon_mix = snapshot_at(records, mid)
    emb_at_mid = pick_embedded(embedded_rows, mid)
    if embedded_in_window(recon_time, mid_iso) and embedded_in_window(emb_at_mid["time"], mid_iso):
        recon_embedded = emb_at_mid
        recon_demand = compute_verdict(recon_mix, emb_at_mid)["national_demand_mw"]
    return neso_solar, recon_demand, recon_embedded


def main() -> None:
    records = fetch_fuelinst()
    snapshot, mix = latest_snapshot(records)
    embedded_rows = fetch_embedded_rows()
    embedded = pick_embedded(embedded_rows, datetime.now(timezone.utc))
    pvlive = fetch_pvlive_solar()
    indo, indo_start = fetch_indo()

    verdict = compute_verdict(mix, embedded)
    verdict["snapshot"] = snapshot
    neso_solar, recon_demand, recon_embedded = aligned_refs(
        records, embedded_rows, pvlive["time"], indo_start)
    sanity_check(verdict, pvlive["solar_mw"], neso_solar, indo, recon_demand, recon_embedded)

    print(f"Snapshot: {snapshot}  (embedded {embedded['time']})")
    print(f"  Renewables (wind+solar): {verdict['renewables_pct']}%  "
          f"({verdict['wind_mw'] + verdict['solar_mw']} MW)")
    print(f"    of which wind        : {verdict['wind_pct']}%  ({verdict['wind_mw']} MW)")
    print(f"    of which solar       : {verdict['solar_pct']}%  ({verdict['solar_mw']} MW)")
    print(f"  Gas & imports          : {verdict['gas_plus_imports_pct']}%  "
          f"({verdict['gas_mw'] + verdict['net_import_mw']} MW)")
    print(f"    of which gas         : {verdict['gas_pct']}%  ({verdict['gas_mw']} MW)")
    print(f"    of which imports     : {verdict['import_pct']}%  ({verdict['net_import_mw']} MW)")
    print(f"  National demand        : {verdict['national_demand_mw']} MW")
    print(f"  [cross-check] PV_Live solar {pvlive['solar_mw']:.0f} MW @ {pvlive['time']}")
    print(f"  [reconcile]   INDO {indo} MW + embedded  "
          f"(residual {verdict['reconcile_residual_pct']}%)")
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
