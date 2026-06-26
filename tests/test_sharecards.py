from pathlib import Path
from engine import sharecards


def test_module_constants():
    assert sharecards.SITE_URL == "https://gridgauge.co.uk"
    assert sharecards.CARD_W == 1200 and sharecards.CARD_H == 630
    assert (sharecards.TEMPLATES / "fonts").is_dir()


def test_cf_to_ink_dark_to_pale():
    assert sharecards.cf_to_ink(0.0).lower() == "#15181c"
    assert sharecards.cf_to_ink(0.6).lower() == "#d7dbdf"   # clamps at >=0.5
    mid = sharecards.cf_to_ink(0.25)
    assert mid.startswith("#") and len(mid) == 7 and mid.lower() not in ("#15181c", "#d7dbdf")


def test_gauge_svg_has_green_red_and_needle():
    svg = sharecards.gauge_svg(83.0)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "#1f9d57" in svg and "#d6121f" in svg     # green firm arc + red remainder
    assert svg.count("<path") >= 2 and "<line" in svg  # two arcs + needle


def test_stripe_svg_one_rect_per_bucket_and_clamps_columns():
    days = [{"cf": c / 100} for c in range(0, 400)]   # 400 days
    svg = sharecards.stripe_svg(days)
    assert svg.startswith("<svg")
    n = svg.count("<rect")
    assert 0 < n <= 520        # downsampled to at most 520 columns


import json


def _write_data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "latest.json").write_text(json.dumps({
        "verdict": {"snapshot": "2026-06-25T23:35:00Z", "firm_pct": 74.7,
                    "wind_mw": 11413, "solar_mw": 0, "gas_mw": 14294}}))
    (d / "nameplate.json").write_text(json.dumps({"wind_plus_solar_gw": 50.362}))
    (d / "counters.json").write_text(json.dumps({
        "latest_year": 2026, "partial_years": [2026],
        "years": {"2026": {"below_10pct": 13, "below_5pct": 1}}}))
    (d / "records.json").write_text(json.dumps({
        "lowest_cf_day": {"date": "2016-01-19", "cf": 0.0087},
        "longest_sub10pct_run": {"start": "2016-06-03", "end": "2016-06-19", "days": 17}}))
    (d / "stripe.json").write_text(json.dumps({
        "mean_cf": 0.2231, "days": [{"cf": 0.1}, {"cf": 0.3}]}))
    return d


def test_gas_vs_wind_headline_adapts():
    fig, lab = sharecards.gas_vs_wind_headline(14294, 11413)
    assert fig == "1.3× more" and "gas fleet out-produces" in lab.lower()
    fig2, lab2 = sharecards.gas_vs_wind_headline(5000, 9000)
    assert "wind" in lab2.lower() and "out-produces" in lab2.lower()


def test_load_cards_builds_the_catalogue(tmp_path):
    cards, asof = sharecards.load_cards(_write_data(tmp_path))
    by = {c["slug"]: c for c in cards}
    assert set(by) == {"firm-now", "capacity-trap", "gas-vs-wind",
                       "wind-stripe", "days-below-10", "lowest-day", "longest-calm"}
    assert by["firm-now"]["figure"] == "75% firm"          # rounded firm_pct
    assert by["firm-now"]["template"] == "instrument" and by["firm-now"]["svg"].startswith("<svg")
    assert by["wind-stripe"]["template"] == "instrument"
    assert by["days-below-10"]["figure"] == "13 days"
    assert by["lowest-day"]["figure"] == "0.9%"            # cf 0.0087 → 0.9%
    assert by["longest-calm"]["figure"] == "17 days"
    # honesty foot-lines present where required
    assert "lower bound" in (by["lowest-day"]["caveat"] or "").lower()
    assert "dukes" in (by["capacity-trap"]["caveat"] or "").lower()
    # all live cards carry a timestamp stamp; settled carry an as-of
    assert "UTC" in by["firm-now"]["stamp"]
