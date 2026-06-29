"""Provenance gate — the promise made machine-checkable.

Every figure documented on the methodology page must trace to a registry unit, and every registry
unit must be documented — no bare figure ships, no stale card lingers. The homepage's per-section
"Sources & method →" links must resolve to a generated card group. Mirrors the share-card
source-trace gate ethos: a build that drifts from the registry fails here.

Reads the SHIPPED files (site/methodology.html is engine-generated; site/app.js references sections),
so a registry change that wasn't rebuilt/committed is caught.
"""

import re
from pathlib import Path

from engine import sources

METHODOLOGY = Path("site/methodology.html")
APP_JS = Path("site/app.js")


def _registry_ids() -> set[str]:
    return set(sources.REGISTRY)


def test_methodology_documents_exactly_the_registry():
    html = METHODOLOGY.read_text()
    page_ids = set(re.findall(r'data-unit="([^"]+)"', html))
    registry_ids = _registry_ids()
    missing = registry_ids - page_ids
    stale = page_ids - registry_ids
    assert not missing, f"registry units with no methodology card (rebuild the page): {sorted(missing)}"
    assert not stale, f"methodology cards for non-registry units (stale, rebuild): {sorted(stale)}"


def test_every_card_section_group_is_present():
    html = METHODOLOGY.read_text()
    for section in {u["section"] for u in sources.REGISTRY.values()}:
        assert f'id="src-group-{section}"' in html, f"no generated card group for section {section!r}"


def test_homepage_section_links_resolve_to_card_groups():
    app = APP_JS.read_text()
    html = METHODOLOGY.read_text()
    sections = set(re.findall(r"entryFooter\('([^']+)'", app))
    assert sections, "no entryFooter('…') calls found in app.js — front-page links missing"
    for section in sections:
        assert section in sources.ALLOWED_SECTIONS, f"app.js references unknown section {section!r}"
        assert f'id="src-group-{section}"' in html, \
            f"front-page link #src-group-{section} has no target on the methodology page"


def test_no_orphan_legacy_source_constants_on_homepage():
    # The cut replaced per-figure source strings with section links; the old constants must be gone.
    app = APP_JS.read_text()
    for dead in ("WIND_GAUGE_SRC", "SOLAR_GAUGE_SRC"):
        assert dead not in app, f"{dead} should have been removed in the front-page cut"
