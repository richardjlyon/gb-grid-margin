"""Stage 2 gate — the shipped nameplate must be dated, cited and arithmetically reconcile.

These tests pin the published capacity denominators so a bad edit (wrong total, missing
citation, de-rated figure slipped in) fails loudly.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.models import Nameplate

NAMEPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / "nameplate.json"


def test_shipped_nameplate_validates_and_reconciles():
    np = Nameplate.model_validate_json(NAMEPLATE_PATH.read_text())
    # Wind total is exactly its onshore + offshore parts (to rounding).
    assert np.wind_gw == pytest.approx(np.wind_onshore_gw + np.wind_offshore_gw, abs=0.02)
    assert np.wind_plus_solar_gw == pytest.approx(np.wind_gw + np.solar_gw, abs=0.02)
    # Dated and cited — the unimpeachable bar.
    assert np.as_of
    assert np.source
    assert np.source_url.startswith("http")


def test_capacity_trap_lands_in_single_digits_at_low_wind():
    np = Nameplate.model_validate_json(NAMEPLATE_PATH.read_text())
    # ~1,500 MW of wind output during a lull, as a share of nameplate.
    pct = 1500 / (np.wind_gw * 1000) * 100
    assert 0 < pct < 10


def test_nameplate_rejects_inconsistent_wind_total():
    with pytest.raises(ValidationError):
        Nameplate(
            as_of="2024-12-31",
            source="x",
            source_url="https://example.com",
            wind_onshore_gw=16.0,
            wind_offshore_gw=16.0,
            wind_gw=99.0,            # != 32.0
            solar_gw=18.0,
            wind_plus_solar_gw=117.0,
        )
