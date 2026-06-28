"""Grid Margin share cards (Stage 8): sourced 1200x630 OG PNGs + unfurl stubs,
built from the same site JSON the dashboard reads so a card can never disagree
with the site. Visual system: Ink (default) / Instrument (gauge & stripe) /
Alarm (active warning only)."""
from __future__ import annotations

import hashlib
import html as _html
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

from engine.guards import (
    GuardError,
    check_cf_range,
    check_finite,
    require,
)

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
SITE_URL = "https://gridmargin.co.uk"
CARD_W, CARD_H = 1200, 630


def _arc_point(cx: float, cy: float, r: float, frac: float) -> tuple[float, float]:
    """Point on the top half-dial; frac 0 = left (180°), 1 = right (0°)."""
    ang = math.pi * (1 - frac)
    return cx + r * math.cos(ang), cy - r * math.sin(ang)


# Per-band gauge palette: (firm_arc, unreliable_arc, needle/hub)
_GAUGE_PALETTE = {
    "green":    ("#1f9d57", "#d6121f", "#ffffff"),
    "red":      ("#2bb56a", "#7d0a10", "#ffffff"),  # maroon stays visible on red fill
    "amber":    ("#15803d", "#c20f1a", "#1a1205"),  # ink needle on light amber
    "charcoal": ("#1f9d57", "#d6121f", "#ffffff"),  # hero illustrative gauge
}


def gauge_svg(firm_pct: float, band: str) -> str:
    """Half-dial icon. Green firm arc (left→needle), unreliable arc (needle→right),
    needle at the firm fraction. Colours flip per background band for legibility."""
    firm_col, unrel_col, needle = _GAUGE_PALETTE[band]
    cx, cy, r, w = 150.0, 150.0, 120.0, 22.0
    f = max(0.0, min(1.0, firm_pct / 100.0))
    lx, ly = _arc_point(cx, cy, r, 0.0)
    bx, by = _arc_point(cx, cy, r, f)
    rx, ry = _arc_point(cx, cy, r, 1.0)
    nx, ny = _arc_point(cx, cy, r - 12, f)
    arc = f"A {r} {r} 0 0 1"
    return (
        f'<svg viewBox="0 0 300 170" width="300" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M {lx:.1f} {ly:.1f} {arc} {bx:.1f} {by:.1f}" fill="none" stroke="{firm_col}" stroke-width="{w}" stroke-linecap="round"/>'
        f'<path d="M {bx:.1f} {by:.1f} {arc} {rx:.1f} {ry:.1f}" fill="none" stroke="{unrel_col}" stroke-width="{w}" stroke-linecap="round"/>'
        f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="{needle}" stroke-width="7" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="10" fill="{needle}"/>'
        f'</svg>'
    )


COMBINED_BASIS = "Combined transmission + embedded wind ÷ DUKES 6.2 installed capacity — a true load factor."
DUKES_BASIS = "Wind+solar output ÷ DUKES 6.2 installed capacity (UK, end-2024)."

# --- reliability stripe ramp (parity-locked to site/render.js) ---------------
RELIABILITY_RAMP_LO, RELIABILITY_RAMP_HI = 0.40, 0.65   # mirror site/render.js RELIABILITY_RAMP
_REL_PAPER, _REL_RED, _REL_GAP = (251, 251, 249), (214, 18, 31), (232, 232, 230)


def firm_band(firm_pct: float) -> str:
    """Green/amber/red band for the live card, cut at the dashboard gauge's ramp."""
    if firm_pct < RELIABILITY_RAMP_LO * 100:
        return "red"
    if firm_pct < RELIABILITY_RAMP_HI * 100:
        return "amber"
    return "green"


def reliable_share_to_color(s: float | None) -> tuple[int, int, int]:
    """Firm share -> RGB, identical to site/render.js reliableShareToColor (parity-locked).

    Uses int(x + 0.5) rather than round(x) to match JS Math.round half-up semantics
    (Python round() uses banker's rounding; JS Math.round() always rounds half-up).
    Channel values are always non-negative here so int(x + 0.5) == Math.round(x).
    """
    if s is None:
        return _REL_GAP
    t = max(0.0, min(1.0, (RELIABILITY_RAMP_HI - s) / (RELIABILITY_RAMP_HI - RELIABILITY_RAMP_LO)))
    r, g, b = (int(_REL_PAPER[k] + (_REL_RED[k] - _REL_PAPER[k]) * t + 0.5) for k in range(3))
    return (r, g, b)


def reliability_stripe_svg(values: list[float | None], width: int = 1040, height: int = 300) -> str:
    """Pack the half-hourly firm-share series into `width` columns (mean each), one rect per column."""
    n = len(values)
    rects = []
    for c in range(width):
        i0 = (c * n) // width
        i1 = max(i0 + 1, ((c + 1) * n) // width)
        vs = [values[i] for i in range(i0, min(i1, n)) if values[i] is not None]
        r, g, b = reliable_share_to_color(sum(vs) / len(vs) if vs else None)
        rects.append(f'<rect x="{c}" y="0" width="1" height="{height}" fill="rgb({r},{g},{b})"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'preserveAspectRatio="none">{"".join(rects)}</svg>')


def _fmt_gw(mw: float) -> str:
    return f"{mw / 1000:.1f} GW"


def _stamp_live(snapshot: str) -> str:
    d = datetime.fromisoformat(snapshot.replace("Z", "+00:00"))
    return f"as of {d.strftime('%d %b %H:%M')} UTC"


def _rebuilt(generated_utc: str | None) -> str:
    """' · rebuilt 25 Jun 2026' from a generated_utc ISO stamp, or '' if absent.

    Threaded onto the settled-card stamps so a shared settled card carries the date
    its underlying figure was last derived — not just a static 'since 2016'.
    """
    if not generated_utc:
        return ""
    try:
        d = datetime.fromisoformat(generated_utc.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f" · rebuilt {d.strftime('%d %b %Y')}"


def _issued(issued_at: str | None) -> str:
    """' · issued 24 Jun 15:30 UTC' from a SYSWARN publishTime, or '' if absent."""
    if not issued_at:
        return ""
    try:
        d = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f" · issued {d.strftime('%d %b %H:%M')} UTC"


def _stamp_snapshot(snapshot: str) -> str:
    """'live snapshot · 27 Jun 2026, 15:10' from a verdict snapshot ISO stamp (UTC)."""
    d = datetime.fromisoformat(snapshot.replace("Z", "+00:00"))
    return f"live snapshot · {d.strftime('%d %b %Y, %H:%M')}"


# Sanity envelope for the card's published wind+solar capacity denominator (GW).
_CAPACITY_MIN_GW, _CAPACITY_MAX_GW = 1.0, 500.0


def guard_card_inputs(latest: dict, nameplate: dict, wu: dict) -> None:
    """Stage 9: fail loudly before a card figure is built from the source JSON.

    The cards are screenshotted into shareable images, so a corrupt or out-of-range
    figure must abort the build rather than become a wrong card. Validates the live
    verdict figures, the capacity denominator, and the wind_unreliability summary.
    Raises GuardError on any breach.
    """
    snap = latest.get("snapshot")
    require(isinstance(snap, str) and snap, "verdict snapshot missing or not a string")
    try:
        datetime.fromisoformat(snap.replace("Z", "+00:00"))
    except ValueError:
        raise GuardError(f"verdict snapshot is not a valid ISO timestamp: {snap!r}")

    firm = latest["firm_pct"]
    check_finite("firm_pct", firm)
    require(0.0 <= firm <= 100.0, f"firm_pct out of range: {firm}")
    for k in ("wind_mw", "solar_mw", "gas_mw"):
        check_finite(k, latest[k])
        require(latest[k] >= 0, f"{k} is negative: {latest[k]}")

    cap = nameplate["wind_plus_solar_gw"]
    check_finite("wind_plus_solar_gw", cap)
    require(_CAPACITY_MIN_GW <= cap <= _CAPACITY_MAX_GW,
            f"nameplate wind_plus_solar_gw {cap} GW outside sane envelope "
            f"[{_CAPACITY_MIN_GW}, {_CAPACITY_MAX_GW}]")

    s = wu["summary"]
    require(s["record_lull"] is not None and s["record_lull"]["days"] >= 0,
            "wu: missing or invalid record_lull (empty store?)")
    low = s["lowest_day"]
    require(low is not None, "wu: missing lowest_day (empty store?)")
    check_cf_range(low["date"], low["cf"])
    check_finite("wu mean_cf", s["mean_cf"])
    require(0.0 <= s["mean_cf"] <= 1.0, f"wu mean_cf out of range: {s['mean_cf']}")
    require(0 <= s["below_5pct_days"] <= s["below_10pct_days"],
            f"wu: below_5pct_days {s['below_5pct_days']} not within "
            f"[0, below_10pct_days {s['below_10pct_days']}]")


def gas_vs_wind_headline(gas_mw: float, wind_mw: float) -> tuple[str, str]:
    """Adaptive, never a false claim: states whichever source actually leads."""
    if gas_mw >= wind_mw:
        mult = gas_mw / wind_mw if wind_mw else 0.0
        fig = f"{mult:.1f}× more"
        lab = (f"the gas fleet out-produces every wind farm in Britain right now — "
               f"{_fmt_gw(gas_mw)} of gas against {_fmt_gw(wind_mw)} of wind.")
    else:
        mult = wind_mw / gas_mw if gas_mw else 0.0
        fig = f"{mult:.1f}× more"
        lab = (f"wind out-produces the whole gas fleet right now — "
               f"{_fmt_gw(wind_mw)} of wind against {_fmt_gw(gas_mw)} of gas.")
    return fig, lab


def live_balance_card(latest: dict) -> dict:
    """The flagship live card. Background band + adaptive framing from the live firm
    share; gauge and headline both derive from the same firm_pct (invariant)."""
    firm = latest["firm_pct"]
    band = firm_band(firm)
    if band == "green":
        figure = f"{int(firm + 0.5)}%"
        label = ("of Britain's grid ran on firm power — gas, nuclear and "
                 "biomass that answer on demand.")
    elif band == "red":
        figure = f"{int(100 - firm + 0.5)}%"
        label = ("of Britain's grid leaned on weather and imports — wind, "
                 "solar and interconnectors that fall away together.")
    else:  # amber
        figure = f"{int(firm + 0.5)}%"
        label = ("of Britain's grid was firm power — the rest depended on "
                 "weather and imports, in roughly equal measure.")
    return {
        "slug": "live-balance", "kind": "live", "band": band, "template": "card",
        "figure": figure, "label": label,
        "stamp": _stamp_snapshot(latest["snapshot"]),
        "caveat": None, "svg": gauge_svg(firm, band)}


def _fmt_span(start: str, end: str) -> str:
    """'12–14 Oct 2025' (same month) or '29 Aug – 2 Sep 2025' (cross-month)."""
    a = datetime.fromisoformat(start)
    b = datetime.fromisoformat(end)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {b.strftime('%b %Y')}"
    return f"{a.day} {a.strftime('%b')} – {b.day} {b.strftime('%b %Y')}"


def recent_lull_card(wu: dict) -> dict:
    """The most recent >=3-day wind lull (combined-basis CF < 10%). Intrinsically red;
    no gauge (a day count is not a share)."""
    runs = [l for l in wu["lulls"] if l["days"] >= 3]
    if not runs:
        raise GuardError("wu: no >=3-day wind lull in the store (empty/early?)")
    lull = runs[-1]                                   # lulls are start-ascending
    count = wu["summary"]["counts"]["ge_3d"]
    return {
        "slug": "recent-lull", "kind": "settled", "band": "red", "template": "card",
        "figure": f"{lull['days']} days",
        "label": (f"the most recent wind lull — {_fmt_span(lull['start'], lull['end'])}, "
                  f"when wind fell as low as {lull['min_cf'] * 100:.1f}% of capacity. "
                  f"Britain has had {count} such spells since 2016."),
        "stamp": "most recent ≥3-day wind lull · combined basis",
        "caveat": COMBINED_BASIS, "svg": None}


def load_cards(data_dir: Path | str) -> tuple[list[dict], str]:
    data = Path(data_dir)
    latest = json.loads((data / "latest.json").read_text())["verdict"]
    nameplate = json.loads((data / "nameplate.json").read_text())
    wu = json.loads((data / "wind_unreliability.json").read_text())

    guard_card_inputs(latest, nameplate, wu)

    snap = latest["snapshot"]
    live_stamp = _stamp_live(snap)
    settled_rebuilt = _rebuilt(wu.get("generated_utc"))
    cards: list[dict] = []

    # --- LIVE ---
    firm = latest["firm_pct"]
    unreliable = int(100 - firm + 0.5)  # half-up to match JS Math.round; see §89–90 comment above
    cards.append({
        "slug": "firm-now", "kind": "live", "theme": "ink", "template": "instrument",
        "figure": f"{unreliable}% unreliable",
        "label": "of Britain's grid is weather-dependent or imported right now — wind, "
                 "solar and interconnectors that fall away together. The rest is firm: "
                 "gas, nuclear, biomass.",
        "stamp": live_stamp, "caveat": None, "svg": gauge_svg(firm, firm_band(firm))})

    built_gw = nameplate["wind_plus_solar_gw"]
    delivering = latest["wind_mw"] + latest["solar_mw"]
    share = delivering / (built_gw * 1000) * 100
    cards.append({
        "slug": "capacity-trap", "kind": "live", "theme": "ink", "template": "stat",
        "figure": f"{share:.0f}% of capacity",
        "label": f"Britain has built {built_gw:.1f} GW of wind & solar. Right now the "
                 f"whole fleet is delivering {_fmt_gw(delivering)}.",
        "stamp": live_stamp, "caveat": DUKES_BASIS, "svg": None})

    fig, lab = gas_vs_wind_headline(latest["gas_mw"], latest["wind_mw"])
    cards.append({
        "slug": "gas-vs-wind", "kind": "live", "theme": "ink", "template": "stat",
        "figure": fig, "label": lab, "stamp": live_stamp, "caveat": None, "svg": None})

    # --- SETTLED ---
    s = wu["summary"]
    cards.append({
        "slug": "wind-stripe", "kind": "settled", "theme": "ink", "template": "stat",
        "figure": f"{s['mean_cf'] * 100:.0f}% mean",
        "label": "Britain's wind has averaged that share of its installed capacity since 2016 — "
                 "combined transmission and embedded output.",
        "stamp": f"Elexon FUELHH + NESO embedded · since 2016{settled_rebuilt}",
        "caveat": COMBINED_BASIS, "svg": None})

    rel = json.loads((data / "reliability_year.json").read_text())
    rel_nn = [v for v in rel["values"] if v is not None]
    rel_mean_unreliable = round((1 - sum(rel_nn) / len(rel_nn)) * 100)
    cards.append({
        "slug": "reliability-stripe", "kind": "settled", "theme": "ink", "template": "instrument",
        "figure": f"{rel_mean_unreliable}% mean unreliable",
        "label": "Every half-hour of the last year: red where Britain leaned on weather and "
                 "imports, pale where firm power carried demand.",
        "stamp": f"Elexon FUELHH + NESO embedded · last 12 months{settled_rebuilt}",
        "caveat": "Reliable share can exceed 100% on net-export half-hours; the scale saturates at 40% firm.",
        "svg": reliability_stripe_svg(rel["values"])})

    cards.append({
        "slug": "days-below-10", "kind": "settled", "theme": "ink", "template": "stat",
        "figure": f"{s['below_10pct_days']} days",
        "label": "since 2016, Britain's wind ran below a tenth of its installed capacity.",
        "stamp": f"Elexon FUELHH + NESO embedded · since 2016{settled_rebuilt}",
        "caveat": COMBINED_BASIS, "svg": None})

    cards.append({
        "slug": "lowest-day", "kind": "settled", "theme": "ink", "template": "stat",
        "figure": f"{s['lowest_day']['cf'] * 100:.1f}%",
        "label": f"of capacity — the wind fleet's worst day on record, {s['lowest_day']['date']}.",
        "stamp": f"Elexon FUELHH + NESO embedded · all-time{settled_rebuilt}",
        "caveat": COMBINED_BASIS, "svg": None})

    cards.append({
        "slug": "longest-calm", "kind": "settled", "theme": "ink", "template": "stat",
        "figure": f"{s['record_lull']['days']} days",
        "label": f"the longest run wind stayed below a tenth of capacity — "
                 f"{s['record_lull']['start']} to {s['record_lull']['end']}.",
        "stamp": f"Elexon FUELHH + NESO embedded · all-time{settled_rebuilt}",
        "caveat": COMBINED_BASIS, "svg": None})

    asof = datetime.fromisoformat(snap.replace("Z", "+00:00")).strftime("%d %B %Y")
    return cards, asof


def warning_card(state: dict) -> dict:
    # NOTE: this card is a static build-time snapshot.  It MUST NOT be served
    # publicly without the Stage 10 refresh cadence wired — a withdrawn notice
    # would otherwise keep reading "in force" (a stale false alarm, contrary to
    # the project's honesty bargain).
    if state.get("in_force"):
        win = state.get("window")
        wtxt = (f" covering {win['from']}–{win['to']}, {win['date']}" if win else "")
        art = "An" if state["type_label"][:1].upper() in "AEIOU" else "A"
        return {"slug": "warning", "kind": "warning", "theme": "alarm", "template": "stat",
                "figure": "Margin notice",
                "label": f"{art} {state['type_label']} is in force in Britain{wtxt}.",
                "stamp": f"Live · Elexon SYSWARN{_issued(state.get('issued_at'))}",
                "caveat": None, "svg": None}
    return {"slug": "warning", "kind": "warning", "theme": "ink", "template": "stat",
            "figure": "All clear",
            "label": "No grid margin warning is in force in Britain right now.",
            "stamp": "Live · Elexon SYSWARN", "caveat": None, "svg": None}


# Gate: the warning card is a static build-time snapshot of a binary in-force/clear state.
# A withdrawn notice would keep a stored "in force" card reading as a stale false alarm
# (and a stored "all clear" card a false negative once a notice fires), so it stays OFF
# until the deploy refresh cadence is proven to rebuild it frequently. Flip to True then.
SERVE_WARNING_CARD = False


def warning_cards(state: dict) -> list[dict]:
    """The warning card wrapped in a list, or [] when gated off — the build splices this
    into the catalogue so the gate is a single source of truth."""
    return [warning_card(state)] if SERVE_WARNING_CARD else []


STUB_TEMPLATE = """<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>{title} — Grid Margin</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Grid Margin">
<meta property="og:url" content="{stub_url}">
<meta property="og:image" content="{image_url}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{site_url}/">
<meta http-equiv="refresh" content="0;url={target}">
</head><body>
<p>{figure} — {label} (as of {asof}) — <a href="{target}">Grid Margin</a>.</p>
<script>location.replace({target_js});</script>
</body></html>
"""


def compose(card: dict) -> str:
    name = "sharecard-instrument.html" if card["template"] == "instrument" else "sharecard-stat.html"
    html = (TEMPLATES / name).read_text()
    html = (html
            .replace("{{THEME}}", card.get("theme", "ink"))
            .replace("{{FIGURE}}", card["figure"])
            .replace("{{LABEL}}", card["label"])
            .replace("{{STAMP}}", card.get("stamp", ""))
            .replace("{{CAVEAT}}", card.get("caveat") or "")
            .replace("{{SVG}}", card.get("svg") or ""))
    if "{{" in html:
        raise ValueError(f"unfilled token in card {card['slug']}")
    return html


def content_hashes(share_dir: Path | str) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(Path(share_dir).glob("*.png")):
        out[p.stem] = hashlib.sha256(p.read_bytes()).hexdigest()[:10]
    return out


def write_manifest(cards: list[dict], out_dir: Path | str, asof: str,
                   versions: dict[str, str]) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {"asof": asof, "cards": [{
        "slug": c["slug"], "figure": c["figure"], "label": c["label"],
        "kind": c["kind"], "png": f"/share/{c['slug']}.png?v={versions.get(c['slug'], '')}",
    } for c in cards]}
    (out / "cards.json").write_text(json.dumps(payload, indent=2) + "\n")


def write_stubs(cards: list[dict], out_dir: Path | str, asof: str,
                versions: dict[str, str]) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = f"{SITE_URL}/"
    for c in cards:
        html = STUB_TEMPLATE.format(
            title=_html.escape(f"{c['figure']} — {c['label']}"),
            description=_html.escape(f"As of {asof}. Every figure traces to Elexon, NESO & DUKES."),
            stub_url=f"{SITE_URL}/s/{c['slug']}",
            image_url=f"{SITE_URL}/share/{c['slug']}.png?v={versions.get(c['slug'], '')}",
            site_url=SITE_URL, target=target, target_js=json.dumps(target),
            figure=_html.escape(c["figure"]), label=_html.escape(c["label"]), asof=asof)
        (out / f"{c['slug']}.html").write_text(html)


def render(cards: list[dict], out_dir: Path | str) -> None:
    """Screenshot one 1200x630 PNG per card. Chromium loads a composed copy of
    the template from a temp dir (file:// so the vendored fonts resolve)."""
    import shutil
    import tempfile

    from playwright.sync_api import sync_playwright

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        shutil.copytree(TEMPLATES / "fonts", tmp / "fonts")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": CARD_W, "height": CARD_H})
            for card in cards:
                src = tmp / f"{card['slug']}.html"
                src.write_text(compose(card))
                page.goto(src.as_uri(), wait_until="networkidle")
                page.evaluate("() => document.fonts.ready")
                page.evaluate("() => window.__fitLabel && window.__fitLabel()")
                page.screenshot(path=str(out / f"{card['slug']}.png"))
            browser.close()


def stamp_index_og(index_path: Path | str, version: str) -> None:
    """Stamp the homepage og:image (firm-now hero) with the content-hash token."""
    index = Path(index_path)
    base = f"{SITE_URL}/share/firm-now.png"
    pattern = re.compile(rf'(<meta property="og:image" content="){re.escape(base)}(?:\?[^"]*)?(">)')
    html, n = pattern.subn(rf'\g<1>{base}?v={version}\g<2>', index.read_text())
    if n != 1:
        raise ValueError(f"expected exactly one firm-now og:image in {index}, found {n}")
    index.write_text(html)


def build(data_dir: Path | str = REPO / "site" / "data",
          site_dir: Path | str = REPO / "site") -> int:
    """Build the full card set: render PNGs, write cards.json + /s/ stubs.
    A render failure leaves existing PNGs in place (warn, don't clobber)."""
    from engine import warnings as wmod

    site = Path(site_dir)
    share_dir = site / "share"
    stub_dir = site / "s"
    try:
        cards, asof = load_cards(data_dir)
    except (GuardError, FileNotFoundError, KeyError, ValueError) as e:
        print(f"card build failed ({type(e).__name__}): {e}", file=sys.stderr)
        return 1
    # Only hit the live SYSWARN feed when the card is actually served (gate authority is
    # warning_cards; the {} keeps the build offline-safe and fast while gated off).
    state = (wmod.parse_active_warnings(wmod.fetch_active_warnings())
             if SERVE_WARNING_CARD else {})
    cards += warning_cards(state)
    try:
        render(cards, share_dir)
    except Exception as e:  # keep last-good PNGs
        print(f"::warning:: card render failed ({type(e).__name__}): {e}", file=sys.stderr)
    versions = content_hashes(share_dir)
    write_manifest(cards, share_dir, asof, versions)
    write_stubs(cards, stub_dir, asof, versions)
    if "firm-now" in versions:
        stamp_index_og(site / "index.html", versions["firm-now"])
    print(f"built {len(cards)} cards → {share_dir}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "build":
        print("usage: python -m engine.sharecards build", file=sys.stderr)
        return 2
    return build()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
