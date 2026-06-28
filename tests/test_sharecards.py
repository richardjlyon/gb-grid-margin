from pathlib import Path
from engine import sharecards


def test_module_constants():
    assert sharecards.SITE_URL == "https://gridmargin.co.uk"
    assert sharecards.CARD_W == 1200 and sharecards.CARD_H == 630
    assert (sharecards.TEMPLATES / "fonts").is_dir()


def test_gauge_svg_has_green_red_and_needle():
    svg = sharecards.gauge_svg(83.0, "green")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "#1f9d57" in svg and "#d6121f" in svg     # green firm arc + red remainder
    assert svg.count("<path") >= 2 and "<line" in svg  # two arcs + needle


import json


def _write_data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "latest.json").write_text(json.dumps({
        "verdict": {"snapshot": "2026-06-25T23:35:00Z", "firm_pct": 74.7,
                    "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}))
    (d / "wind_unreliability.json").write_text(json.dumps({
        "generated_utc": "2026-06-25T21:39:53.7+00:00",
        "lulls": [
            {"start": "2025-10-12", "end": "2025-10-14", "days": 3, "min_cf": 0.0393},
        ],
        "summary": {
            "counts": {"ge_1d": 1, "ge_3d": 1, "ge_7d": 0, "ge_14d": 0},
            "record_lull": {"start": "2016-06-03", "end": "2016-06-19", "days": 17,
                            "min_cf": 0.05, "min_cf_date": "2016-06-10", "severe": False},
            "lowest_day": {"date": "2016-01-19", "cf": 0.0087},
            "worst_lull_by_year": {},
            "mean_cf": 0.2231,
            "below_10pct_days": 13,
            "below_5pct_days": 1,
        }}))
    return d


def test_gas_vs_wind_headline_adapts():
    fig, lab = sharecards.gas_vs_wind_headline(14294, 11413)
    assert fig == "1.3× more" and "gas fleet out-produces" in lab.lower()
    fig2, lab2 = sharecards.gas_vs_wind_headline(5000, 9000)
    assert "wind" in lab2.lower() and "out-produces" in lab2.lower()


def test_load_cards_builds_the_catalogue(tmp_path):
    cards, asof = sharecards.load_cards(_write_data(tmp_path))
    by = {c["slug"]: c for c in cards}
    assert set(by) == {"live-balance", "recent-lull"}
    # firm_pct=74.7 → green band → figure is firm share rounded
    assert by["live-balance"]["figure"] == "75%"           # int(74.7 + 0.5) = 75
    assert by["live-balance"]["svg"].startswith("<svg")
    assert by["recent-lull"]["figure"] == "3 days"
    assert "combined" in (by["recent-lull"]["caveat"] or "").lower()


def test_warning_card_alarm_when_in_force():
    c = sharecards.warning_card({"in_force": True, "type": "EMN",
        "type_label": "Electricity Margin Notice",
        "window": {"from": "19:00", "to": "22:00", "date": "26/06/2026"}})
    assert c["slug"] == "warning" and c["theme"] == "alarm" and c["kind"] == "warning"
    assert "Electricity Margin Notice" in c["label"]
    assert "19:00" in c["label"]


def test_warning_card_calm_when_clear():
    c = sharecards.warning_card({"in_force": False})
    assert c["theme"] == "ink"
    assert "no" in c["figure"].lower() or "clear" in c["figure"].lower()


def test_warning_card_gated_off_by_default(monkeypatch):
    """Launch default: a static warning card is suppressed (a withdrawn notice would
    otherwise read 'in force' forever). Returns no card to add to the build."""
    monkeypatch.setattr(sharecards, "SERVE_WARNING_CARD", False)
    assert sharecards.warning_cards({"in_force": False}) == []


def test_warning_card_served_when_enabled(monkeypatch):
    """Once the refresh cron is proven, flipping the flag re-includes the live card."""
    monkeypatch.setattr(sharecards, "SERVE_WARNING_CARD", True)
    cards = sharecards.warning_cards({"in_force": False})
    assert len(cards) == 1 and cards[0]["slug"] == "warning"


def test_compose_fills_tokens_and_marks_accent():
    card = {"slug": "x", "theme": "ink", "template": "stat",
            "figure": "75% firm", "label": "L", "stamp": "S", "caveat": None, "svg": None}
    html = sharecards.compose(card)
    assert "{{" not in html
    assert "75% firm" in html and 'class="ink"' in html


def test_compose_instrument_injects_svg():
    card = {"slug": "g", "theme": "ink", "template": "instrument",
            "figure": "75% firm", "label": "L", "stamp": "S", "caveat": None,
            "svg": "<svg>GAUGE</svg>"}
    html = sharecards.compose(card)
    assert "<svg>GAUGE</svg>" in html and "{{" not in html


def test_content_hashes(tmp_path):
    (tmp_path / "a.png").write_bytes(b"hello")
    out = sharecards.content_hashes(tmp_path)
    assert out["a"] == __import__("hashlib").sha256(b"hello").hexdigest()[:10]


def test_write_manifest_and_stubs(tmp_path):
    cards = [{"slug": "firm-now", "figure": "75% firm", "label": "L", "kind": "live",
              "theme": "ink", "stamp": "S", "caveat": None}]
    sharecards.write_manifest(cards, tmp_path, "26 June 2026", {"firm-now": "abc123"})
    man = json.loads((tmp_path / "cards.json").read_text())
    assert man["cards"][0]["png"] == "/share/firm-now.png?v=abc123"
    sharecards.write_stubs(cards, tmp_path, "26 June 2026", {"firm-now": "abc123"})
    stub = (tmp_path / "firm-now.html").read_text()
    assert 'twitter:card" content="summary_large_image"' in stub
    assert "/share/firm-now.png?v=abc123" in stub
    assert 'og:image:width" content="1200"' in stub


import struct


def _png_size(path):
    b = path.read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", b[16:24])
    return w, h


def test_warning_card_article_by_notice_type():
    """Article must agree with the type_label's initial vowel sound (I2 gate)."""
    emn = sharecards.warning_card({"in_force": True, "type": "EMN",
        "type_label": "Electricity Margin Notice", "window": None})
    assert emn["label"].startswith("An Electricity Margin Notice")

    cmn = sharecards.warning_card({"in_force": True, "type": "CMN",
        "type_label": "Capacity Market Notice", "window": None})
    assert cmn["label"].startswith("A Capacity Market Notice")

    nism = sharecards.warning_card({"in_force": True, "type": "NISM",
        "type_label": "Notice of Insufficient System Margin", "window": None})
    assert nism["label"].startswith("A Notice of Insufficient System Margin")


def test_render_writes_1200x630_pngs(tmp_path):
    cards = [
        {"slug": "stat", "theme": "ink", "template": "stat", "figure": "75% firm",
         "label": "L", "stamp": "S", "caveat": None, "svg": None},
        {"slug": "inst", "theme": "ink", "template": "instrument", "figure": "75% firm",
         "label": "L", "stamp": "S", "caveat": None, "svg": sharecards.gauge_svg(75, "green")},
    ]
    sharecards.render(cards, tmp_path)
    for slug in ("stat", "inst"):
        p = tmp_path / f"{slug}.png"
        assert p.exists() and p.stat().st_size > 0
        assert _png_size(p) == (1200, 630)
