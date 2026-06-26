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


LOWER_BOUND = "Conservative lower bound — transmission-metered wind ÷ total installed (DUKES 6.2)."
DUKES_BASIS = "Wind+solar output ÷ DUKES 6.2 installed capacity (UK, end-2024)."


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


# Sanity envelope for the card's published wind+solar capacity denominator (GW).
_CAPACITY_MIN_GW, _CAPACITY_MAX_GW = 1.0, 500.0


def guard_card_inputs(latest: dict, nameplate: dict, counters: dict,
                      records: dict, stripe: dict) -> None:
    """Stage 9: fail loudly before a card figure is built from the source JSON.

    The cards are screenshotted into shareable images, so a corrupt or out-of-range
    figure must abort the build rather than become a wrong card. Validates the live
    verdict figures, the capacity denominator, the counters' nesting, the record CF
    and the stripe mean. Raises GuardError on any breach.
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

    yc = counters["years"][str(counters["latest_year"])]
    b10, b5 = yc["below_10pct"], yc["below_5pct"]
    require(0 <= b5 <= b10, f"counters: below_5pct {b5} not within [0, below_10pct {b10}]")

    low = records["lowest_cf_day"]
    require(low is not None, "records: missing lowest_cf_day (empty store?)")
    check_cf_range(low["date"], low["cf"])
    require(records["longest_sub10pct_run"]["days"] >= 0,
            "records: negative longest sub-10% run length")

    check_finite("stripe mean_cf", stripe["mean_cf"])
    require(0.0 <= stripe["mean_cf"] <= 1.0, f"stripe mean_cf out of range: {stripe['mean_cf']}")
    require(len(stripe["days"]) > 0, "stripe has no days")


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


def load_cards(data_dir: Path | str) -> tuple[list[dict], str]:
    data = Path(data_dir)
    latest = json.loads((data / "latest.json").read_text())["verdict"]
    nameplate = json.loads((data / "nameplate.json").read_text())
    counters = json.loads((data / "counters.json").read_text())
    records = json.loads((data / "records.json").read_text())
    stripe = json.loads((data / "stripe.json").read_text())

    guard_card_inputs(latest, nameplate, counters, records, stripe)

    snap = latest["snapshot"]
    live_stamp = _stamp_live(snap)
    settled_rebuilt = _rebuilt(stripe.get("generated_utc"))
    records_rebuilt = _rebuilt(records.get("generated_utc"))
    counters_rebuilt = _rebuilt(counters.get("generated_utc"))
    cards: list[dict] = []

    # --- LIVE ---
    firm = latest["firm_pct"]
    cards.append({
        "slug": "firm-now", "kind": "live", "theme": "ink", "template": "instrument",
        "figure": f"{round(firm)}% firm",
        "label": "of Britain's grid is firm power right now — gas, nuclear, biomass. "
                 "The rest is weather & imports.",
        "stamp": live_stamp, "caveat": None, "svg": gauge_svg(firm)})

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
    cards.append({
        "slug": "wind-stripe", "kind": "settled", "theme": "ink", "template": "instrument",
        "figure": f"{stripe['mean_cf'] * 100:.0f}% mean",
        "label": "Each column is one day's wind since 2016. The wind rarely blows above "
                 "a fraction of its capacity.",
        "stamp": f"Elexon FUELHH · since 2016{settled_rebuilt}", "caveat": LOWER_BOUND,
        "svg": stripe_svg(stripe["days"])})

    yr = counters["latest_year"]
    yc = counters["years"][str(yr)]
    part = " (so far)" if yr in counters.get("partial_years", []) else ""
    cards.append({
        "slug": "days-below-10", "kind": "settled", "theme": "ink", "template": "stat",
        "figure": f"{yc['below_10pct']} days",
        "label": f"in {yr}{part}, Britain's wind ran below a tenth of its installed capacity.",
        "stamp": f"Elexon FUELHH · {yr}{counters_rebuilt}", "caveat": LOWER_BOUND, "svg": None})

    low = records["lowest_cf_day"]
    cards.append({
        "slug": "lowest-day", "kind": "settled", "theme": "ink", "template": "stat",
        "figure": f"{low['cf'] * 100:.1f}%",
        "label": f"of capacity — the wind fleet's worst day on record, {low['date']}.",
        "stamp": f"Elexon FUELHH · all-time{records_rebuilt}", "caveat": LOWER_BOUND, "svg": None})

    run = records["longest_sub10pct_run"]
    cards.append({
        "slug": "longest-calm", "kind": "settled", "theme": "ink", "template": "stat",
        "figure": f"{run['days']} days",
        "label": f"the longest run wind stayed below 10% of capacity — {run['start']} to {run['end']}.",
        "stamp": f"Elexon FUELHH · all-time{records_rebuilt}", "caveat": LOWER_BOUND, "svg": None})

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


STUB_TEMPLATE = """<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>{title} — Grid Gauge</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Grid Gauge">
<meta property="og:url" content="{stub_url}">
<meta property="og:image" content="{image_url}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{site_url}/">
<meta http-equiv="refresh" content="0;url={target}">
</head><body>
<p>{figure} — {label} (as of {asof}) — <a href="{target}">Grid Gauge</a>.</p>
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
    cards.append(warning_card(wmod.parse_active_warnings(wmod.fetch_active_warnings())))
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
