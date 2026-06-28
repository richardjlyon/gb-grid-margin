from engine import sharecards


def test_firm_band_cuts_lock_to_reliability_ramp():
    # parity with site/render.js RELIABILITY_RAMP = { lo: 0.40, hi: 0.65 }
    assert sharecards.RELIABILITY_RAMP_LO == 0.40
    assert sharecards.RELIABILITY_RAMP_HI == 0.65
    assert sharecards.firm_band(39.9) == "red"
    assert sharecards.firm_band(40.0) == "amber"
    assert sharecards.firm_band(64.9) == "amber"
    assert sharecards.firm_band(65.0) == "green"
    assert sharecards.firm_band(100.0) == "green"
    assert sharecards.firm_band(0.0) == "red"


def test_gauge_palette_per_band():
    # amber → ink needle; red → maroon unreliable arc + white needle; green → white needle
    amber = sharecards.gauge_svg(50.0, "amber")
    assert "#1a1205" in amber          # ink needle/hub on light amber
    assert "#15803d" in amber          # deep-green firm arc
    assert "#c20f1a" in amber          # deep-red unreliable arc
    red = sharecards.gauge_svg(35.0, "red")
    assert "#7d0a10" in red            # maroon unreliable arc stays visible on red fill
    assert "#ffffff" in red  # white needle
    green = sharecards.gauge_svg(70.0, "green")
    assert "#ffffff" in green             # white needle on green fill


def test_gauge_needle_fraction_tracks_firm_pct():
    # needle endpoint must move right as firm rises (frac 0=left .. 1=right)
    import re
    def needle_x(svg):
        m = re.search(r'<line x1="[\d.]+" y1="[\d.]+" x2="([\d.]+)"', svg)
        assert m is not None, f"No <line> found in SVG: {svg[:200]}"
        return float(m.group(1))
    assert needle_x(sharecards.gauge_svg(20.0, "red")) < needle_x(sharecards.gauge_svg(80.0, "green"))
