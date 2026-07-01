from pathlib import Path

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


def test_generate_pages_writes_page_and_index(tmp_path):
    payload = {"slug": "demo", "title": "Anatomy of an emergency", "event_date": "2026-06-24",
               "category": "import-squeeze", "basis": "national", "generated_utc": "x",
               "hero": {"kicker": "24 June 2026", "dek": "d", "body_md": "b", "attributed_figures": []},
               "commentary": [], "panels": ["reliability"], "sources": [], "frames": [], "markers": []}
    site = tmp_path / "site"; (site / "data").mkdir(parents=True)
    paths = scenarios.generate_pages([payload], site=site)
    page = site / "post-mortem" / "demo.html"
    index = site / "post-mortem" / "index.html"
    assert page in paths and page.exists() and index.exists()
    html = page.read_text()
    assert 'class="masthead"' in html and "postmortem.js" in html
    assert 'href="../methodology.html"' in html  # relativised nav
    assert "Anatomy of an emergency" in html
    # shared-chrome head assets must be relativised for the /post-mortem/ subfolder
    assert 'href="../style.css"' in html
    assert 'href="../fonts.css"' in html
    assert 'href="../favicon.svg"' in html
    assert 'href="../fonts/space-grotesk-latin.woff2"' in html
    assert 'href="style.css"' not in html
    assert 'href="fonts.css"' not in html
    assert 'href="favicon.svg"' not in html

    index_html = index.read_text()
    assert 'href="../style.css"' in index_html
    assert 'href="../fonts.css"' in index_html
    assert 'href="../favicon.svg"' in index_html
    assert 'href="../fonts/space-grotesk-latin.woff2"' in index_html
    assert 'href="style.css"' not in index_html
    assert 'href="fonts.css"' not in index_html
    assert 'href="favicon.svg"' not in index_html


def test_build_all_returns_named_payloads(tmp_path):
    fh, emb, pr, ns, caps = __import__("tests.test_snapshot", fromlist=["_stores"])._stores()
    site = tmp_path / "site"; (site / "data").mkdir(parents=True)
    named = scenarios.build_all(fh, emb, pr, ns, caps, "2026-07-01T00:00:00Z", site=site)
    names = [n for n, _ in named]
    # 8 Jan 2025 is fully covered and renders; 24 June 2026 is skipped (embedded not yet published).
    assert "scenario_8-january-2025-costliest-day" in names
    assert "scenario_24-june-2026-emergency" not in names
    assert (site / "post-mortem" / "8-january-2025-costliest-day.html").exists()


def test_index_links_to_postmortem():
    html = open("site/index.html").read()
    assert "post-mortem/8-january-2025-costliest-day" in html
    assert "Going further" in html
