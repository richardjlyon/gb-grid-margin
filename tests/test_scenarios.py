import pytest
from engine import scenarios
from engine.guards import GuardError

GOOD = {"slug": "x", "title": "T", "category": "import-squeeze", "event_date": "2026-06-24",
        "window": {"from": "2026-06-24", "to": "2026-06-24"},
        "hero": {"kicker": "k", "dek": "d", "body_md": "b", "attributed_figures": []},
        "commentary": [{"period": 24, "marker": True, "label": "L", "text": "t"}],
        "panels": ["reliability", "wind", "solar", "imports", "price"], "basis": "national"}

def test_validate_ok():
    scenarios.validate_scenario(GOOD)  # no raise

def test_validate_rejects_missing_slug():
    bad = {k: v for k, v in GOOD.items() if k != "slug"}
    with pytest.raises(GuardError):
        scenarios.validate_scenario(bad)

def test_validate_rejects_bad_commentary_period():
    bad = {**GOOD, "commentary": [{"period": 99, "marker": True, "label": "L", "text": "t"}]}
    with pytest.raises(GuardError):
        scenarios.validate_scenario(bad)

def test_validate_rejects_missing_commentary_period():
    bad = {**GOOD, "commentary": [{"marker": True, "label": "L", "text": "t"}]}
    with pytest.raises(GuardError):
        scenarios.validate_scenario(bad)
