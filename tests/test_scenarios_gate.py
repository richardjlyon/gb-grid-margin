import pytest
from engine import scenarios
from engine.guards import GuardError

def _payload(**over):
    base = {"panels": ["reliability", "price", "solar"], "markers": [{"index": 0, "label": "L"}],
            "frames": [{"firm_pct": 48.0, "demand_mw": 33000, "price_gbp_mwh": 77.0, "solar_cf_pct": 20.0}]}
    return {**base, **over}

def test_guard_ok():
    scenarios.guard_payload(_payload())

def test_guard_rejects_empty_frames():
    with pytest.raises(GuardError):
        scenarios.guard_payload(_payload(frames=[]))

def test_guard_rejects_price_panel_without_price():
    f = [{"firm_pct": 48.0, "demand_mw": 33000, "price_gbp_mwh": None, "solar_cf_pct": 20.0}]
    with pytest.raises(GuardError):
        scenarios.guard_payload(_payload(frames=f))

def test_guard_rejects_marker_out_of_range():
    with pytest.raises(GuardError):
        scenarios.guard_payload(_payload(markers=[{"index": 9, "label": "L"}]))
