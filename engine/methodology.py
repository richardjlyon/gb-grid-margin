"""Generate the methodology page's source cards from the provenance registry.

The registry (engine/sources.py) is the single author of every figure's source + basis + caveats.
This module renders it into scannable, no-JS-safe source cards and injects them into
`site/methodology.html` between two markers, so the page's source-of-truth cards are GENERATED and
cannot drift from the registry the front page and share cards read. The hand-written conceptual
prose on the page (the reasoning — why imports sit with wind, why the mean not the median) stays as
framing above and around the generated region.

Wired into `engine.derived.build`; can also be run standalone via `build()`.
"""

from __future__ import annotations

from pathlib import Path

from engine.build_site import _atomic_write

METHODOLOGY_PATH = Path("site/methodology.html")

MARKER_START = "<!-- GENERATED:sources:START — engine/methodology.py owns this region, do not hand-edit -->"
MARKER_END = "<!-- GENERATED:sources:END -->"

# The four provenance sections, in page order, with their display headings. Keyed by the registry
# `section` field; the first three map to the homepage §01/§02/§03 links.
SECTION_TITLES = {
    "reliability": "Reliability — the firm share (§01)",
    "wind": "Wind (§02)",
    "solar": "Solar (§02)",
    "imports": "Imports (§03)",
    "warnings": "Grid warnings",
}


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _card(uid: str, u: dict) -> str:
    feeds = ", ".join(
        f'<a href="{_esc(f["url"])}" rel="noopener">{_esc(f["name"])}</a>' for f in u["feeds"])
    caveats = ""
    if u["caveats"]:
        items = "".join(f"<li>{_esc(c)}</li>" for c in u["caveats"])
        caveats = f'\n      <ul class="source-card__caveats">{items}</ul>'
    return (
        f'    <article class="source-card" data-unit="{_esc(uid)}" id="src-{_esc(uid)}">\n'
        f'      <div class="source-card__head">'
        f'<h3>{_esc(u["label"])}</h3>'
        f'<span class="cadence cadence--{_esc(u["cadence"])}">{_esc(u["cadence"])}</span></div>\n'
        f'      <p class="source-card__feeds"><span class="k">Feeds</span> {feeds}</p>\n'
        f'      <p class="source-card__basis"><span class="k">Basis</span> {_esc(u["basis"])}</p>'
        f'{caveats}\n'
        f'      <p class="source-card__more">'
        f'<a href="#{_esc(u["method_anchor"])}">→ full method</a></p>\n'
        f'    </article>'
    )


def render_cards(payload: dict) -> str:
    """The grouped source cards as a static HTML string (no surrounding markers)."""
    units = payload["units"]
    groups: list[str] = []
    for section, title in SECTION_TITLES.items():
        cards = [_card(uid, u) for uid, u in units.items() if u["section"] == section]
        if not cards:
            continue
        inner = "\n".join(cards)
        groups.append(
            f'  <section class="source-group" id="src-group-{section}">\n'
            f'    <h2>{title}</h2>\n{inner}\n  </section>')
    return "\n".join(groups)


def inject(html: str, generated: str) -> str:
    """Replace the content between MARKER_START and MARKER_END with `generated`. Idempotent."""
    s = html.find(MARKER_START)
    e = html.find(MARKER_END)
    if s == -1 or e == -1 or e < s:
        raise ValueError("methodology source markers not found in page")
    before = html[: s + len(MARKER_START)]
    after = html[e:]
    return f"{before}\n{generated}\n  {after}"


def build(payload: dict, path: Path = METHODOLOGY_PATH) -> None:
    """Regenerate the source-card region of site/methodology.html from the registry."""
    html = path.read_text()
    _atomic_write(path, inject(html, render_cards(payload)))
