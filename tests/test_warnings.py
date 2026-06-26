from engine import warnings as w

EMN_TEXT = ("ELECTRICITY MARGIN NOTICE\n"
            "from 19:00 hrs to 22:00 hrs on Friday   26/06/2026\n")


def test_classify_scarcity_only():
    assert w.classify_warning("ELECTRICITY MARGIN NOTICE") == "EMN"
    assert w.classify_warning("CAPACITY MARKET NOTICE") == "CMN"
    assert w.classify_warning("NOTICE OF INSUFFICIENT SYSTEM MARGIN") == "NISM"
    assert w.classify_warning("SO-SO TRADES") is None
    assert w.classify_warning("IT SYSTEMS OUTAGE") is None


def test_parse_window():
    assert w.parse_window(EMN_TEXT) == {"from": "19:00", "to": "22:00", "date": "26/06/2026"}
    assert w.parse_window("no window here") is None


def test_parse_active_warnings_empty_and_noise():
    assert w.parse_active_warnings([]) == {"in_force": False}
    noise = [{"warningType": "SO-SO TRADES", "warningText": "x", "publishTime": "t"}]
    assert w.parse_active_warnings(noise) == {"in_force": False}


def test_parse_active_warnings_emn_in_force():
    rows = [{"warningType": "ELECTRICITY MARGIN NOTICE", "warningText": EMN_TEXT,
             "publishTime": "2026-06-25T23:30:00Z"}]
    r = w.parse_active_warnings(rows)
    assert r["in_force"] and r["type"] == "EMN"
    assert r["type_label"] == "Electricity Margin Notice"
    assert r["window"] == {"from": "19:00", "to": "22:00", "date": "26/06/2026"}


def test_parse_active_warnings_severity_nism_over_emn():
    rows = [{"warningType": "ELECTRICITY MARGIN NOTICE", "warningText": "x", "publishTime": "2026-06-25T20:00:00Z"},
            {"warningType": "NOTICE OF INSUFFICIENT SYSTEM MARGIN", "warningText": "y", "publishTime": "2026-06-25T19:00:00Z"}]
    assert w.parse_active_warnings(rows)["type"] == "NISM"
