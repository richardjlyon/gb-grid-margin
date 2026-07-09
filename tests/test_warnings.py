from datetime import datetime, timezone

from engine import warnings as w

EMN_TEXT = ("ELECTRICITY MARGIN NOTICE\n"
            "For the period:\n"
            "from 19:00 hrs to 22:00 hrs on Friday   26/06/2026\n")

# A clock inside the 19:00–22:00 (26/06) London window, and one after it.
WITHIN = datetime(2026, 6, 26, 20, 0, tzinfo=timezone.utc)   # London BST 21:00 → in force
AFTER = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)     # London BST 01:00 27/06 → expired

CMN_ACTIVE = ("Electricity Capacity Market Notice Currently Active\n"
              "Commencement time of notice : 18:00 on 26/06/2026")
CMN_CANCELLED = ("Electricity Capacity Market Notice Cancelled\n"
                 "The Capacity Market Notice originally active from 16:30 on 26/06/2026 has been cancelled")


def test_classify_scarcity_two_rungs_no_nism():
    assert w.classify_warning("ELECTRICITY MARGIN NOTICE") == "EMN"
    assert w.classify_warning("CAPACITY MARKET NOTICE") == "CMN"
    # NISM was retired in 2016 — no longer a rung, so its phrasing is unclassified noise.
    assert w.classify_warning("NOTICE OF INSUFFICIENT SYSTEM MARGIN") is None
    assert w.classify_warning("SO-SO TRADES") is None
    assert w.classify_warning("IT SYSTEMS OUTAGE") is None


def test_parse_window():
    assert w.parse_window(EMN_TEXT) == {"from": "19:00", "to": "22:00", "date": "26/06/2026"}
    assert w.parse_window("no window here") is None


def test_parse_active_warnings_empty_and_noise():
    assert w.parse_active_warnings([], WITHIN) == {"in_force": False}
    noise = [{"warningType": "SO-SO TRADES", "warningText": "x", "publishTime": "t"}]
    assert w.parse_active_warnings(noise, WITHIN) == {"in_force": False}


def test_parse_active_warnings_nism_is_noise():
    rows = [{"warningType": "NOTICE OF INSUFFICIENT SYSTEM MARGIN",
             "warningText": "from 17:00 hrs to 23:00 hrs on Friday   26/06/2026",
             "publishTime": "2026-06-26T17:00:00Z"}]
    assert w.parse_active_warnings(rows, WITHIN) == {"in_force": False}


def test_parse_active_warnings_emn_in_force():
    rows = [{"warningType": "ELECTRICITY MARGIN NOTICE", "warningText": EMN_TEXT,
             "publishTime": "2026-06-25T23:30:00Z"}]
    r = w.parse_active_warnings(rows, WITHIN)
    assert r["in_force"] and r["type"] == "EMN"
    assert r["type_label"] == "Electricity Margin Notice"
    assert r["window"] == {"from": "19:00", "to": "22:00", "date": "26/06/2026"}


def test_parse_active_warnings_emn_expired():
    rows = [{"warningType": "ELECTRICITY MARGIN NOTICE", "warningText": EMN_TEXT,
             "publishTime": "2026-06-25T23:30:00Z"}]
    assert w.parse_active_warnings(rows, AFTER) == {"in_force": False}


def test_parse_active_warnings_emn_cancellation():
    rows = [{"warningType": "ELECTRICITY MARGIN NOTICE",
             "warningText": "ELECTRICITY MARGIN NOTICE NOTIFICATION CANCELLATION — the notice "
                            "from 19:00 hrs to 22:00 hrs on Friday   26/06/2026 has been cancelled",
             "publishTime": "2026-06-26T21:00:00Z"}]
    assert w.parse_active_warnings(rows, WITHIN) == {"in_force": False}


def test_parse_active_warnings_cmn_active_and_cancelled():
    active = [{"warningType": "CAPACITY MARKET NOTICE", "warningText": CMN_ACTIVE,
               "publishTime": "2026-06-26T18:00:00Z"}]
    r = w.parse_active_warnings(active, WITHIN)
    assert r["in_force"] and r["type"] == "CMN" and r["window"] is None
    cancelled = [{"warningType": "CAPACITY MARKET NOTICE", "warningText": CMN_CANCELLED,
                  "publishTime": "2026-06-26T19:00:00Z"}]
    assert w.parse_active_warnings(cancelled, WITHIN) == {"in_force": False}


def test_parse_active_warnings_precedence_emn_over_cmn():
    # Editorial precedence (NESO does not rank the two): the EMN leads when both are in force.
    rows = [{"warningType": "ELECTRICITY MARGIN NOTICE", "warningText": EMN_TEXT,
             "publishTime": "2026-06-25T23:30:00Z"},
            {"warningType": "CAPACITY MARKET NOTICE", "warningText": CMN_ACTIVE,
             "publishTime": "2026-06-26T18:00:00Z"}]
    assert w.parse_active_warnings(rows, WITHIN)["type"] == "EMN"
