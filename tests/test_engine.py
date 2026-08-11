"""Methodology tests — pin the denominator formula and the build-time guards.

These characterise the existing engine logic so a refactor (or a feed change) cannot
silently move a published figure. Inputs are synthetic round numbers so the expected
shares can be computed by hand.
"""

import pytest

from engine.grid_engine import (
    aligned_refs,
    compute_verdict,
    embedded_in_window,
    latest_snapshot,
    sanity_check,
    snapshot_at,
    validate_snapshot,
)
from engine.models import EmbeddedRow, FuelInstRecord

# A synthetic snapshot. National demand works out to exactly 28_300 MW:
#   wind 5000 (trans) + gas 6000 + nuclear 3000 + biomass 2000 + other 600
#   + net imports 700 + embedded solar 10_000 + embedded wind 1000 = 28_300
MIX = {
    "CCGT": 6000, "OCGT": 0,
    "WIND": 5000,
    "NUCLEAR": 3000,
    "BIOMASS": 2000,
    "INTFR": 1000, "INTIRL": -300,   # net interconnector imports = 700
    "OTHER": 500, "NPSHYD": 100,     # other transmission generation = 600
    "PS": -800,                      # pumped-storage pumping — demand, excluded
}
EMBEDDED = {"solar_mw": 10000, "wind_mw": 1000, "time": "2026-06-25T13:30Z"}


def _verdict():
    return compute_verdict(MIX, EMBEDDED)


def test_firm_and_notfirm_partition_demand():
    """Firm (dispatchable, weather-independent) vs weather & imports — the reliability cut.

    Firm = gas + nuclear + biomass + other firm fuels (hydro etc.); weather & imports =
    wind + solar + net interconnector imports (the sources that fail together in a
    synoptic calm). The two buckets partition national demand exactly.
    """
    v = _verdict()
    assert v["firm_mw"] == 6000 + 3000 + 2000 + 600          # gas+nuclear+biomass+other
    assert v["notfirm_mw"] == 6000 + 10000 + 700             # wind+solar+net imports
    assert v["firm_mw"] + v["notfirm_mw"] == v["national_demand_mw"]
    assert v["firm_pct"] == 41.0
    assert v["notfirm_pct"] == 59.0
    assert round(v["firm_pct"] + v["notfirm_pct"], 1) == 100.0


def test_latest_snapshot_picks_most_recent_and_builds_mix():
    records = [
        FuelInstRecord.model_validate(
            {"startTime": "2026-06-25T13:25:00Z", "fuelType": "CCGT", "generation": 100}),
        FuelInstRecord.model_validate(
            {"startTime": "2026-06-25T13:30:00Z", "fuelType": "CCGT", "generation": 200}),
        FuelInstRecord.model_validate(
            {"startTime": "2026-06-25T13:30:00Z", "fuelType": "WIND", "generation": 50}),
    ]
    snapshot, mix = latest_snapshot(records)
    assert snapshot == "2026-06-25T13:30:00Z"
    assert mix == {"CCGT": 200, "WIND": 50}


def test_snapshot_at_picks_bucket_nearest_anchor():
    from datetime import datetime

    records = [
        FuelInstRecord.model_validate(
            {"startTime": "2026-06-25T13:25:00Z", "fuelType": "CCGT", "generation": 100}),
        FuelInstRecord.model_validate(
            {"startTime": "2026-06-25T13:30:00Z", "fuelType": "CCGT", "generation": 200}),
    ]
    anchor = datetime.fromisoformat("2026-06-25T13:26:00Z")
    snapshot, mix = snapshot_at(records, anchor)
    assert snapshot == "2026-06-25T13:25:00Z"
    assert mix == {"CCGT": 100}


def _embedded_row(time_gmt, solar=10000, wind=1000):
    return EmbeddedRow.model_validate({
        "DATE_GMT": "2026-06-25T00:00:00", "TIME_GMT": time_gmt,
        "EMBEDDED_SOLAR_FORECAST": solar, "EMBEDDED_WIND_FORECAST": wind,
        "EMBEDDED_SOLAR_CAPACITY": 22000, "EMBEDDED_WIND_CAPACITY": 6400,
    })


def test_aligned_refs_aligns_both_references():
    records = [FuelInstRecord.model_validate(
        {"startTime": "2026-06-25T13:15:00Z", "fuelType": k, "generation": v})
        for k, v in MIX.items()]
    neso_solar, recon_demand, recon_emb = aligned_refs(
        records, [_embedded_row("13:00")],
        pvlive_time="2026-06-25T13:00:00Z",
        indo_start="2026-06-25T13:00:00Z")  # midpoint 13:15 → the one bucket, exactly
    assert neso_solar == 10000
    assert recon_emb["time"] == "2026-06-25T13:00Z"
    assert recon_demand == 28300  # same mix + embedded as _verdict()


def test_aligned_refs_returns_none_when_data_cannot_align():
    # Nearest bucket and embedded row are hours from the references → both checks skip.
    records = [FuelInstRecord.model_validate(
        {"startTime": "2026-06-25T13:15:00Z", "fuelType": "CCGT", "generation": 100})]
    neso_solar, recon_demand, recon_emb = aligned_refs(
        records, [_embedded_row("13:00")],
        pvlive_time="2026-06-25T18:00:00Z",
        indo_start="2026-06-25T18:00:00Z")
    assert neso_solar is None
    assert recon_demand is None
    assert recon_emb is None


def test_national_demand_is_supply_reconstruction():
    assert _verdict()["national_demand_mw"] == 28300


def test_wind_is_transmission_plus_embedded():
    assert _verdict()["wind_mw"] == 6000


def test_net_imports_net_off_exports():
    assert _verdict()["net_import_mw"] == 700


def test_pumped_storage_pumping_excluded_from_demand():
    # PS is -800; if it leaked into the denominator the total would not be 28_300.
    assert _verdict()["national_demand_mw"] == 28300
    assert "PS" not in {"wind", "solar", "gas"}  # sanity: no PS numerator


def test_other_is_remaining_positive_transmission_generation():
    assert _verdict()["other_mw"] == 600


def test_lowercase_interconnector_counts_as_net_import_not_other():
    # Elexon could emit a lowercase INT* code; it must net into imports, never `other`.
    mix = {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000,
           "intfr": 700, "OTHER": 500}
    v = compute_verdict(mix, {"solar_mw": 0, "wind_mw": 0, "time": "x"})
    assert v["net_import_mw"] == 700
    assert v["other_mw"] == 500


# --- snapshot-completeness guard (mirrored in the browser) ---

_COMPLETE = {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "INTFR": 700}


def test_validate_snapshot_accepts_complete_bucket():
    assert validate_snapshot(_COMPLETE, demand=20000) is True


def test_validate_snapshot_rejects_missing_core_fuel():
    assert validate_snapshot({"WIND": 5000, "NUCLEAR": 3000, "INTFR": 700},
                             demand=20000) is False


def test_validate_snapshot_rejects_no_interconnector():
    assert validate_snapshot({"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000},
                             demand=20000) is False


def test_validate_snapshot_rejects_below_demand_floor():
    assert validate_snapshot(_COMPLETE, demand=10000) is False


# --- embedded-freshness guard (mirrored in the browser) ---

def test_embedded_in_window_accepts_within_30min():
    assert embedded_in_window("2026-06-25T14:00Z", "2026-06-25T13:40:00Z") is True


def test_embedded_in_window_rejects_beyond_30min():
    assert embedded_in_window("2026-06-25T14:30Z", "2026-06-25T13:40:00Z") is False


def test_embedded_in_window_fail_closed_on_bad_timestamp():
    assert embedded_in_window("garbage", "2026-06-25T13:40:00Z") is False


def test_shares_sum_to_one_hundred():
    v = _verdict()
    total = (v["wind_pct"] + v["solar_pct"] + v["gas_pct"] + v["import_pct"]
             + round(v["nuclear_mw"] / v["national_demand_mw"] * 100, 1)
             + round(v["biomass_mw"] / v["national_demand_mw"] * 100, 1)
             + round(v["other_mw"] / v["national_demand_mw"] * 100, 1))
    assert total == pytest.approx(100, abs=0.3)


# Heavy-export night (real shape: 2026-06-25 23:30Z, GB exporting ~4.55 GW).
MIX_EXPORT = {
    "CCGT": 12000, "WIND": 10000, "NUCLEAR": 5000, "BIOMASS": 2000, "OTHER": 1000,
    "INTFR": -3000, "INTNED": -1553,          # net interconnector flow = -4553 (export)
}
EMB_EXPORT = {"solar_mw": 0, "wind_mw": 1320, "time": "2026-06-25T23:30Z"}


def test_reconcile_against_indo_survives_heavy_export():
    """Regression for the export false-alarm (reconcile-guard-export-bug).

    On an export night the supply reconstruction computes *national* demand (the INDO
    basis). Reconciling against INDO is export-neutral. The retired ITSDO reference
    counted the export volume (+ station load + PS pumping) as demand, diverging ~20%
    and tripping the guard on good data.
    """
    v = compute_verdict(MIX_EXPORT, EMB_EXPORT)
    assert v["national_demand_mw"] == 26767
    # INDO (national demand) reconciles cleanly.
    sanity_check(v, pvlive_solar=0, neso_solar_at_pvlive=None, indo=25447,
                 recon_demand_mw=v["national_demand_mw"], recon_embedded=EMB_EXPORT)
    assert v["reconcile_residual_pct"] == 0.0
    # A transmission-demand (ITSDO) magnitude reference — national demand + the 4.55 GW
    # export + station load + PS pumping — would still trip the 12% guard. That mismatch
    # was the bug; INDO removes it.
    v2 = compute_verdict(MIX_EXPORT, EMB_EXPORT)
    with pytest.raises(AssertionError, match="reconciliation"):
        sanity_check(v2, pvlive_solar=0, neso_solar_at_pvlive=None, indo=33000,
                     recon_demand_mw=v2["national_demand_mw"], recon_embedded=EMB_EXPORT)


def test_sanity_check_passes_for_consistent_inputs():
    v = _verdict()
    # PV_Live close to NESO solar; INDO + embedded close to the denominator.
    indo = 28300 - EMBEDDED["solar_mw"] - EMBEDDED["wind_mw"]  # = 17_300
    sanity_check(v, pvlive_solar=10200, neso_solar_at_pvlive=EMBEDDED["solar_mw"],
                 indo=indo, recon_demand_mw=v["national_demand_mw"], recon_embedded=EMBEDDED)


def test_sanity_check_trips_on_solar_crosscheck_divergence():
    v = _verdict()
    with pytest.raises(AssertionError, match="cross-check"):
        sanity_check(v, pvlive_solar=5000, neso_solar_at_pvlive=EMBEDDED["solar_mw"],
                     indo=17300, recon_demand_mw=v["national_demand_mw"],
                     recon_embedded=EMBEDDED)


def test_sanity_check_trips_on_demand_reconciliation_divergence():
    v = _verdict()
    with pytest.raises(AssertionError, match="reconciliation"):
        sanity_check(v, pvlive_solar=10000, neso_solar_at_pvlive=10000, indo=5000,
                     recon_demand_mw=v["national_demand_mw"], recon_embedded=EMBEDDED)


def test_sanity_check_solar_floor_ignores_dawn_noise():
    """Below the MW floor the relative solar check must not bind: a 39 MW dawn gap is
    18% of a 217 MW reading but headline-irrelevant on a ~22 GW fleet."""
    v = _verdict()
    sanity_check(v, pvlive_solar=217, neso_solar_at_pvlive=256, indo=17300,
                 recon_demand_mw=v["national_demand_mw"], recon_embedded=EMBEDDED)


def test_sanity_check_skips_checks_it_cannot_time_align():
    """A reference that can't be time-aligned must be SKIPPED, not compared across a
    ramp — the Aug 2026 four-day fallback outage was now-vs-lagged comparisons."""
    v = _verdict()
    # Wildly divergent pvlive/indo values, but both refs arrive as None → no trip.
    sanity_check(v, pvlive_solar=99999, neso_solar_at_pvlive=None, indo=1,
                 recon_demand_mw=None, recon_embedded=None)
    assert v["reconcile_residual_pct"] is None
