"""Grid Gauge share cards (Stage 8): sourced 1200x630 OG PNGs + unfurl stubs,
built from the same site JSON the dashboard reads so a card can never disagree
with the site. Visual system: Ink (default) / Instrument (gauge & stripe) /
Alarm (active warning only)."""
from __future__ import annotations

import hashlib
import html as _html
import json
import math
import re
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
SITE_URL = "https://gridgauge.co.uk"
CARD_W, CARD_H = 1200, 630


def cf_to_ink(cf: float) -> str:
    """Dark ink at cf=0 → pale grey at cf>=0.5, linear in between (mirrors the
    stripe's calm=dark / windy=pale reading)."""
    t = max(0.0, min(1.0, cf / 0.5))
    a, b = (0x15, 0x18, 0x1c), (0xd7, 0xdb, 0xdf)
    rgb = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return "#%02x%02x%02x" % rgb


def _arc_point(cx: float, cy: float, r: float, frac: float) -> tuple[float, float]:
    """Point on the top half-dial; frac 0 = left (180°), 1 = right (0°)."""
    ang = math.pi * (1 - frac)
    return cx + r * math.cos(ang), cy - r * math.sin(ang)


def gauge_svg(firm_pct: float) -> str:
    cx, cy, r, w = 260.0, 280.0, 200.0, 40.0
    f = max(0.0, min(1.0, firm_pct / 100.0))
    lx, ly = _arc_point(cx, cy, r, 0.0)
    bx, by = _arc_point(cx, cy, r, f)
    rx, ry = _arc_point(cx, cy, r, 1.0)
    nx, ny = _arc_point(cx, cy, r - 20, f)
    arc = f"A {r} {r} 0 0 1"
    return (
        f'<svg viewBox="0 0 520 300" width="520" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M {lx:.1f} {ly:.1f} {arc} {bx:.1f} {by:.1f}" fill="none" stroke="#1f9d57" stroke-width="{w}"/>'
        f'<path d="M {bx:.1f} {by:.1f} {arc} {rx:.1f} {ry:.1f}" fill="none" stroke="#d6121f" stroke-width="{w}"/>'
        f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="#fff" stroke-width="6" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="11" fill="#fff"/>'
        f'</svg>'
    )


def stripe_svg(days: list[dict], width: int = 1040, height: int = 300) -> str:
    """Downsample daily cf to <=520 columns (darkest-wins, like the live canvas)
    and emit one rect per column; pale = windy, dark = calm."""
    n = len(days) or 1
    cols = min(520, n)
    cw = width / cols
    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" xmlns="http://www.w3.org/2000/svg">']
    for c in range(cols):
        i0 = (c * n) // cols
        i1 = max(i0 + 1, ((c + 1) * n) // cols)
        lo = min(days[i].get("cf", 1.0) for i in range(i0, min(i1, n)))
        parts.append(f'<rect x="{c * cw:.2f}" y="0" width="{cw:.2f}" height="{height}" fill="{cf_to_ink(lo)}"/>')
    parts.append("</svg>")
    return "".join(parts)
