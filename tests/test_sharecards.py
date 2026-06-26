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
