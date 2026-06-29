"""Provenance registry — contract + guard tests (Stage: provenance registry).

The registry (engine/sources.py) is the SINGLE author of every figure's source +
basis + caveats. These tests pin its shape so the methodology generator, the
front-page links and the provenance gate can all rely on it, and so a malformed
unit fails the build loudly rather than shipping a bare figure.
"""

import pytest

from engine import sources
from engine.guards import GuardError

GENERATED = "2026-06-29T00:00:00+00:00"

# The stable IDs the rest of the site references. If one is renamed, the methodology
# generator and the provenance gate must move with it — so the rename is deliberate.
EXPECTED_IDS = {
    "verdict", "reliability-carpet",
    "wind-dial", "wind-carpet", "solar-dial", "solar-carpet", "wind-unreliability",
    "import-power", "import-cost",
    "overcast", "warnings", "lamps-computed",
}


def test_build_payload_has_generated_and_units():
    p = sources.build_payload(GENERATED)
    assert p["generated_utc"] == GENERATED
    assert set(p["units"]) == EXPECTED_IDS


def test_every_unit_is_well_formed():
    p = sources.build_payload(GENERATED)
    for uid, u in p["units"].items():
        assert u["label"], f"{uid} missing label"
        assert u["basis"], f"{uid} missing basis"
        assert u["section"] in sources.ALLOWED_SECTIONS, f"{uid} bad section {u['section']!r}"
        assert u["cadence"] in sources.ALLOWED_CADENCES, f"{uid} bad cadence {u['cadence']!r}"
        assert u["feeds"], f"{uid} has no feeds"
        for feed in u["feeds"]:
            assert feed["name"], f"{uid} feed missing name"
            assert feed["url"].startswith("http"), f"{uid} feed url not a url: {feed['url']!r}"
        assert isinstance(u["caveats"], list), f"{uid} caveats not a list"


def test_every_section_is_represented():
    p = sources.build_payload(GENERATED)
    seen = {u["section"] for u in p["units"].values()}
    assert seen == sources.ALLOWED_SECTIONS


def test_guard_passes_on_real_registry():
    sources.guard_payload(sources.build_payload(GENERATED))   # must not raise


def test_guard_rejects_missing_basis():
    p = sources.build_payload(GENERATED)
    p["units"]["verdict"]["basis"] = ""
    with pytest.raises(GuardError):
        sources.guard_payload(p)


def test_guard_rejects_bad_section():
    p = sources.build_payload(GENERATED)
    p["units"]["verdict"]["section"] = "nonsense"
    with pytest.raises(GuardError):
        sources.guard_payload(p)


def test_guard_rejects_bad_cadence():
    p = sources.build_payload(GENERATED)
    p["units"]["verdict"]["cadence"] = "hourly"
    with pytest.raises(GuardError):
        sources.guard_payload(p)


def test_guard_rejects_empty_feeds():
    p = sources.build_payload(GENERATED)
    p["units"]["verdict"]["feeds"] = []
    with pytest.raises(GuardError):
        sources.guard_payload(p)


def test_guard_rejects_feed_without_url():
    p = sources.build_payload(GENERATED)
    p["units"]["verdict"]["feeds"] = [{"name": "Elexon", "url": ""}]
    with pytest.raises(GuardError):
        sources.guard_payload(p)
