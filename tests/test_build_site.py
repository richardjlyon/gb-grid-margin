"""Build-writer tests — network-free (fetchers monkeypatched). Pin the provenance
block, the verdict==engine invariant, and the fail-safe fallback protection.
"""

import json
from datetime import datetime

import pytest

from engine import build_site, grid_engine
from engine.models import FuelInstRecord

SNAP = "2026-06-25T13:30:00Z"
MIX = {"CCGT": 6000, "WIND": 5000, "NUCLEAR": 3000, "BIOMASS": 2000,
       "INTFR": 1500, "OTHER": 500}
EMBEDDED = {"solar_mw": 8000, "wind_mw": 1000, "solar_capacity_mw": 22000,
            "wind_capacity_mw": 6400, "time": "2026-06-25T13:30Z"}
PVLIVE = {"solar_mw": 8200, "time": SNAP}   # within 10% of embedded solar
INDO = 18000                                 # indo + embedded(9000) == demand(27000)


@pytest.fixture
def patched(monkeypatch):
    records = [FuelInstRecord.model_validate(
        {"startTime": SNAP, "fuelType": k, "generation": v}) for k, v in MIX.items()]
    monkeypatch.setattr(grid_engine, "fetch_fuelinst", lambda: records)
    monkeypatch.setattr(grid_engine, "fetch_embedded_neso", lambda: dict(EMBEDDED))
    monkeypatch.setattr(grid_engine, "fetch_pvlive_solar", lambda: dict(PVLIVE))
    monkeypatch.setattr(grid_engine, "fetch_indo", lambda: INDO)


def test_build_writes_payload_with_full_provenance(patched, tmp_path):
    target = tmp_path / "latest.json"
    assert build_site.build(target) == 0
    data = json.loads(target.read_text())
    assert data["schema_version"] == 1
    p = data["provenance"]
    datetime.fromisoformat(p["build_time_utc"])            # parses as ISO datetime
    assert isinstance(p["embedded_age_min"], (int, float))
    assert p["solar_capacity_mw"] == 22000                 # live trap denominators present
    assert p["wind_capacity_mw"] == 6400
    assert p["indo"] == INDO


def test_build_verdict_equals_engine(patched, tmp_path):
    target = tmp_path / "latest.json"
    build_site.build(target)
    v = json.loads(target.read_text())["verdict"]
    expected = grid_engine.compute_verdict(MIX, EMBEDDED)
    for k in expected:
        if k == "snapshot":
            continue
        assert v[k] == expected[k]                          # build adds no math


def test_failed_build_leaves_fallback_byte_identical(patched, monkeypatch, tmp_path):
    target = tmp_path / "latest.json"
    seed = '{"seed":"known-good"}\n'
    target.write_text(seed)
    # Force the cross-check guard to trip: PV_Live far from the NESO solar figure.
    monkeypatch.setattr(grid_engine, "fetch_pvlive_solar", lambda: {"solar_mw": 1000, "time": SNAP})
    assert build_site.build(target) == 1
    assert target.read_text() == seed                       # os.replace never ran


def test_failed_build_leaves_no_temp_file(patched, monkeypatch, tmp_path):
    target = tmp_path / "latest.json"
    monkeypatch.setattr(grid_engine, "fetch_indo",
                        lambda: (_ for _ in ()).throw(RuntimeError("feed down")))
    assert build_site.build(target) == 1
    assert list(tmp_path.glob(".latest-*.tmp")) == []
