"""Single-source the shared page chrome — masthead/nav, footer, and the head font/asset block —
across every static page under site/.

Each page hand-authored these regions, so they DRIFTED: the front page called the same link
"Sources & Method" while the others said "Methodology", the footer repo link read "Github" on one
page and "Source & data" on the rest, and three different Google-Fonts URLs were in flight. This
module owns the canonical markup and rewrites each page's chrome from it, so the chrome cannot drift
again. Same idea (and the same `_atomic_write`) as engine/methodology.py.

Regions are matched by their stable structural anchors — no hand-placed markers needed:
  - head assets : the run from the googleapis preconnect through the favicon <link>
  - header      : <header class="masthead"> … </header>  (plus an optional preceding skip link)
  - footer      : <footer class="footer"> … </footer>
  - main        : the opening <main …> tag gains id="main" (skip-link target)
Per-page state — the active nav link's aria-current — is derived from the file name.

Idempotent: re-running replaces canonical with canonical. Wired into engine.derived.build; can also
be run standalone via `python -m engine.chrome build`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from engine.build_site import _atomic_write

SITE = Path("site")

# The six pages that share the chrome. (validate.html is a dev harness; the /s/ unfurl stubs and the
# share cards are generated elsewhere.)
PAGES = ["index.html", "methodology.html", "about.html", "import.html", "wind.html", "share.html"]

# Pages that own a primary-nav entry get aria-current; the home page and the detail pages do not.
ACTIVE = {"methodology.html": "methodology", "about.html": "about", "share.html": "share"}

# Fonts are self-hosted (site/fonts/*.woff2 + site/fonts.css), not fetched from Google — one fewer
# third-party round-trip and no per-visitor request to Google. The two above-the-fold faces (the
# Space Grotesk display and the Newsreader body) are preloaded; fonts.css declares all of them.
ASSETS = (
    '<!-- chrome:fonts -->\n'
    '        <link rel="preload" href="fonts/space-grotesk-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
    '        <link rel="preload" href="fonts/newsreader-latin.woff2" as="font" type="font/woff2" crossorigin>\n'
    '        <link rel="stylesheet" href="fonts.css">\n'
    '        <link rel="stylesheet" href="style.css">\n'
    '        <link rel="icon" type="image/svg+xml" href="favicon.svg">'
)

FOOTER = (
    '<footer class="footer">\n'
    '            <div class="container">\n'
    '                <p class="links">Made by <a href="https://theenergytrap.org">Richard Lyon</a> · '
    '<a href="methodology.html">Methodology &amp; Sources</a> · '
    '<a href="share.html">Share cards</a> · '
    '<a href="about.html">About this site</a> · '
    '<a href="https://github.com/richardjlyon/gb-grid-margin">Github</a></p>\n'
    '                <p class="trace">Every figure traces to Elexon, NESO and DUKES. No modelled numbers.</p>\n'
    '            </div>\n'
    '        </footer>'
)


def _header(page: str) -> str:
    active = ACTIVE.get(page)

    def cur(slug: str) -> str:
        return ' aria-current="page"' if slug == active else ""

    nav = (
        '<nav aria-label="Primary">'
        f'<a href="methodology.html"{cur("methodology")}>Methodology</a>'
        f'<a href="share.html"{cur("share")}>Share</a>'
        f'<a href="about.html"{cur("about")}>About</a>'
        '<span class="live-dot" id="live-dot" aria-live="polite" hidden></span>'
        "</nav>"
    )
    return (
        '<a class="skip-link" href="#main">Skip to content</a>\n'
        '        <header class="masthead">\n'
        '            <div class="container masthead-inner">\n'
        '                <div>\n'
        '                    <p class="brand"><a href="/">'
        '<span class="brand-tick" aria-hidden="true"></span>GB Grid Margin</a></p>\n'
        '                    <span class="masthead-snapshot" id="clockstrip"></span>\n'
        '                </div>\n'
        f'                {nav}\n'
        '            </div>\n'
        '        </header>'
    )


# Region anchors. Each MUST match exactly once per page — a zero or multiple match means the page
# structure moved and the chrome would silently stop being maintained, so we fail loudly.
_ASSETS_RE = re.compile(
    # matches the current self-hosted block (starts at the marker) OR the legacy Google block
    # (starts at the googleapis preconnect), through the favicon link — so migration + re-runs both work
    r'(?:<!-- chrome:fonts -->|<link rel="preconnect" href="https://fonts\.googleapis\.com").*?'
    r'href="favicon\.svg"[^>]*>',
    re.DOTALL,
)
_HEADER_RE = re.compile(
    r'(?:<a class="skip-link"[^>]*>.*?</a>\s*)?<header class="masthead">.*?</header>',
    re.DOTALL,
)
_FOOTER_RE = re.compile(r'<footer class="footer">.*?</footer>', re.DOTALL)
_MAIN_RE = re.compile(r'<main\b(?![^>]*\bid=)')


def _sub_once(pattern: re.Pattern, repl: str, html: str, what: str, page: str) -> str:
    n = len(pattern.findall(html))
    if n != 1:
        raise ValueError(f"{page}: expected exactly one {what} region, found {n}")
    # escape backslashes so the canonical markup is inserted literally (no regex backreferences)
    return pattern.sub(repl.replace("\\", "\\\\"), html, count=1)


def assemble(html: str, page: str) -> str:
    """Rewrite the chrome regions of one page from the canonical markup. Idempotent."""
    html = _sub_once(_ASSETS_RE, ASSETS, html, "head-assets", page)
    html = _sub_once(_HEADER_RE, _header(page), html, "header", page)
    html = _sub_once(_FOOTER_RE, FOOTER, html, "footer", page)
    # main id="main" is the skip-link target; add it only if absent (idempotent).
    if _MAIN_RE.search(html):
        html = _MAIN_RE.sub('<main id="main"', html, count=1)
    return html


def build(site: Path = SITE) -> None:
    """Regenerate the shared chrome across every page in PAGES."""
    for page in PAGES:
        path = site / page
        html = path.read_text()
        out = assemble(html, page)
        if out != html:
            _atomic_write(path, out)
            print(f"chrome: rewrote {page}")
        else:
            print(f"chrome: {page} already current")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    else:
        print("usage: python -m engine.chrome build", file=sys.stderr)
        sys.exit(2)
