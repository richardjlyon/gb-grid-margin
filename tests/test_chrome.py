"""Shared page chrome — tests.

engine/chrome.py owns the masthead/nav, footer and head-asset block and rewrites them into every
page from one canonical source, so the chrome cannot drift across pages again (the bug it fixes: the
front page said "Sources & Method" while the others said "Methodology", and three different
Google-Fonts URLs were in flight). These tests lock that single-sourcing in.
"""

import re
from pathlib import Path

import pytest

from engine import chrome

SITE = Path("site")
PAGES = chrome.PAGES

_HEADER = re.compile(r"<header class=\"masthead\">.*?</header>", re.DOTALL)
_FOOTER = re.compile(r"<footer class=\"footer\">.*?</footer>", re.DOTALL)
_ASSETS = re.compile(
    r"<!-- chrome:fonts -->.*?href=\"favicon\.svg\"[^>]*>",
    re.DOTALL,
)


def _read(page):
    return (SITE / page).read_text()


def _strip_aria_current(header):
    return header.replace(' aria-current="page"', "")


def test_every_page_built_with_canonical_chrome():
    """The on-disk pages match what the assembler would produce (build was run / stays in sync)."""
    for page in PAGES:
        html = _read(page)
        assert chrome.assemble(html, page) == html, f"{page} chrome is stale — run engine.chrome build"


def test_assemble_is_idempotent():
    for page in PAGES:
        once = chrome.assemble(_read(page), page)
        twice = chrome.assemble(once, page)
        assert once == twice, f"{page} assemble not idempotent"


def test_header_identical_across_pages_modulo_active_link():
    headers = {p: _strip_aria_current(_HEADER.search(_read(p)).group(0)) for p in PAGES}
    distinct = set(headers.values())
    assert len(distinct) == 1, f"masthead drifted across pages: {headers.keys()}"


def test_footer_identical_across_pages():
    footers = {_FOOTER.search(_read(p)).group(0) for p in PAGES}
    assert len(footers) == 1, "footer drifted across pages"


def test_one_font_url_across_pages():
    blocks = {_ASSETS.search(_read(p)).group(0) for p in PAGES}
    assert len(blocks) == 1, "head asset/font block drifted across pages"


def test_fonts_are_self_hosted():
    # No page may reach out to Google Fonts; every face must resolve from the local fonts.css.
    css = (SITE / "fonts.css").read_text()
    assert "fonts.googleapis.com" not in css and "fonts.gstatic.com" not in css
    for page in PAGES:
        html = _read(page)
        assert "fonts.googleapis.com" not in html, f"{page} still links Google Fonts"
        assert 'href="fonts.css"' in html, f"{page} not linking the self-hosted fonts.css"
    for face in re.findall(r"url\((fonts/[^)]+)\)", css):
        assert (SITE / face).exists(), f"fonts.css references missing file {face}"


def test_active_nav_state_is_per_page():
    # The three pages with a nav entry mark themselves current; the rest carry no aria-current.
    for page, slug in chrome.ACTIVE.items():
        header = _HEADER.search(_read(page)).group(0)
        assert f'href="{slug}.html" aria-current="page"' in header, f"{page} missing aria-current"
    for page in set(PAGES) - set(chrome.ACTIVE):
        assert 'aria-current="page"' not in _HEADER.search(_read(page)).group(0)


def test_drift_artifacts_gone():
    for page in PAGES:
        html = _read(page)
        assert "Sources &amp; Method" not in html, f"{page} still carries the old nav label"


def test_every_page_has_exactly_one_h1_and_a_skip_target():
    for page in PAGES:
        html = _read(page)
        assert len(re.findall(r"<h1[ >]", html)) == 1, f"{page} must have exactly one <h1>"
        assert '<a class="skip-link" href="#main">' in html, f"{page} missing skip link"
        assert '<main id="main"' in html, f"{page} <main> missing id for the skip target"


def test_assemble_fails_loudly_on_missing_region():
    with pytest.raises(ValueError):
        chrome.assemble("<html><body>no chrome here</body></html>", "index.html")
