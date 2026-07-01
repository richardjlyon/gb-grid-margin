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


def test_real_scenarios_file_validates():
    ss = scenarios.load_scenarios()
    slugs = {s["slug"] for s in ss}
    assert "8-january-2025-costliest-day" in slugs
    assert "24-june-2026-emergency" in slugs
    for s in ss:
        scenarios.validate_scenario(s)


def test_resolve_payload_shapes_frames_and_markers():
    fh, emb, pr, ns, caps = __import__("tests.test_snapshot", fromlist=["_stores"])._stores()
    s = next(s for s in scenarios.load_scenarios() if s["slug"] == "8-january-2025-costliest-day")
    p = scenarios.resolve_payload(s, fuelhh_rows=fh, embedded_rows=emb, price_rows=pr,
                                  ns=ns, caps=caps, generated_utc="2026-07-01T00:00:00Z")
    assert len(p["frames"]) == 48
    assert p["basis"] == s["basis"]
    # markers point at the SP-matching frame index
    m0 = next(m for m in p["markers"] if "price spike" in m["label"])
    assert p["frames"][m0["index"]]["sp"] == 31
