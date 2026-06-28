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
