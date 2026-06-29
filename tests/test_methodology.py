"""Methodology source-card generation — tests.

engine/methodology.py renders the provenance registry into scannable source cards and injects
them between markers in site/methodology.html, so the page's source-of-truth cards cannot drift
from the registry the rest of the site reads.
"""

import pytest

from engine import methodology, sources

GENERATED = "2026-06-29T00:00:00+00:00"
PAYLOAD = sources.build_payload(GENERATED)


def test_render_cards_has_a_card_per_unit():
    html = methodology.render_cards(PAYLOAD)
    for uid in PAYLOAD["units"]:
        assert f'data-unit="{uid}"' in html, f"no card for {uid}"


def test_render_cards_groups_by_section_in_order():
    html = methodology.render_cards(PAYLOAD)
    # All four section headings present, and in the canonical order.
    positions = [html.index(title) for title in methodology.SECTION_TITLES.values()]
    assert positions == sorted(positions)


def test_render_cards_links_every_feed():
    html = methodology.render_cards(PAYLOAD)
    # Each feed url appears as an href.
    for u in PAYLOAD["units"].values():
        for feed in u["feeds"]:
            assert f'href="{feed["url"]}"' in html


def test_render_cards_shows_cadence_tag():
    html = methodology.render_cards(PAYLOAD)
    assert "settled" in html and "live" in html


def test_inject_replaces_between_markers():
    page = f"BEFORE\n{methodology.MARKER_START}\nOLD\n{methodology.MARKER_END}\nAFTER"
    out = methodology.inject(page, "NEW")
    assert "OLD" not in out
    assert "NEW" in out
    assert out.startswith("BEFORE")
    assert out.endswith("AFTER")


def test_inject_is_idempotent():
    page = f"x\n{methodology.MARKER_START}\nOLD\n{methodology.MARKER_END}\ny"
    once = methodology.inject(page, "NEW")
    twice = methodology.inject(once, "NEW")
    assert once == twice


def test_inject_raises_without_markers():
    with pytest.raises(ValueError):
        methodology.inject("no markers here", "NEW")
