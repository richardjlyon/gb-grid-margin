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


def _mk(firm, snap="2026-06-27T15:10:00Z"):
    return {"firm_pct": firm, "snapshot": snap}


def test_live_balance_red_leads_with_unreliable():
    c = sharecards.live_balance_card(_mk(35.4))
    assert c["band"] == "red"
    assert c["figure"] == "65%"                       # round(100-35.4) = red-arc length
    assert "leaned on weather and imports" in c["label"]
    assert c["svg"]                                    # has a gauge
    assert c["stamp"] == "live snapshot · 27 Jun 2026, 15:10"


def test_live_balance_green_leads_with_firm():
    c = sharecards.live_balance_card(_mk(70.0))
    assert c["band"] == "green"
    assert c["figure"] == "70%"                        # round(firm) = green-arc length
    assert "ran on firm power" in c["label"]


def test_live_balance_amber_neutral_framing():
    c = sharecards.live_balance_card(_mk(50.0))
    assert c["band"] == "amber"
    assert c["figure"] == "50%"
    assert "depended on weather and imports" in c["label"]


def test_live_balance_figure_matches_gauge_firm():
    # gauge built from the same firm_pct as the headline (invariant)
    c = sharecards.live_balance_card(_mk(35.4))
    assert sharecards.gauge_svg(35.4, "red") == c["svg"]


def test_recent_lull_picks_latest_3day_run():
    wu = {
        "lulls": [
            {"start": "2024-11-03", "end": "2024-11-05", "days": 3, "min_cf": 0.0451},
            {"start": "2025-10-12", "end": "2025-10-14", "days": 3, "min_cf": 0.0393},
            {"start": "2026-05-04", "end": "2026-05-04", "days": 1, "min_cf": 0.0972},  # too short
        ],
        "summary": {"counts": {"ge_3d": 45}},
    }
    c = sharecards.recent_lull_card(wu)
    assert c["band"] == "red"
    assert c["svg"] is None
    assert c["figure"] == "3 days"
    assert "12" in c["label"] and "14 Oct 2025" in c["label"]   # the latest >=3-day run
    assert "3.9% of capacity" in c["label"]                      # min_cf 0.0393
    assert "45" in c["label"]                                    # ge_3d context


def test_fmt_span_same_month_and_cross_month():
    assert sharecards._fmt_span("2025-10-12", "2025-10-14") == "12–14 Oct 2025"
    assert sharecards._fmt_span("2025-08-29", "2025-09-02") == "29 Aug – 2 Sep 2025"
