"""Independent recompute: assert each card figure equals a value derived straight
from the source JSON, by a path that does NOT reuse the builders' formatting.

Reads fixed snapshots in tests/fixtures/sharecards/, not the committed live
site/data/, so the suite does not change with the weather (aios-harness#149)."""
import json
from pathlib import Path

import pytest

from engine import sharecards
from engine.guards import GuardError

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "sharecards"
DATA = FIXTURES / "ordinary"      # real live snapshot, 13 Nov 2026 13:35Z, firm 49.1%
EXPORTING = FIXTURES / "exporting"  # real live snapshot, 7 Nov 2026 03:45Z: Britain exporting


def _load(name):
    return json.loads((DATA / name).read_text())


def test_load_cards_is_the_v09_set():
    cards, _ = sharecards.load_cards(DATA)
    assert [c["slug"] for c in cards] == ["live-balance", "recent-lull"]


def test_live_balance_figure_traces_to_firm_pct():
    cards, _ = sharecards.load_cards(DATA)
    c = next(c for c in cards if c["slug"] == "live-balance")
    firm = _load("latest.json")["verdict"]["firm_pct"]
    expected = (f"{int(firm + 0.5)}%" if firm >= sharecards.RELIABILITY_RAMP_LO * 100
                else f"{int(100 - firm + 0.5)}%")
    assert c["figure"] == expected
    assert c["figure"] == "49%"           # 49.1% sits in the amber band: the firm share is the figure


def test_recent_lull_figure_traces_to_source():
    cards, _ = sharecards.load_cards(DATA)
    c = next(c for c in cards if c["slug"] == "recent-lull")
    wu = _load("wind_unreliability.json")
    latest3 = [l for l in wu["lulls"] if l["days"] >= 3][-1]
    assert c["figure"] == f"{latest3['days']} days"
    assert c["caveat"] and "combined" in c["caveat"].lower()


def test_exporting_snapshot_has_firm_share_over_100():
    # The real 7 Nov 2026 03:45Z reading: firm generation exceeded national demand
    # because Britain was exporting. Figures as published in /data/latest.json.
    v = json.loads((EXPORTING / "latest.json").read_text())["verdict"]
    assert (v["firm_mw"], v["national_demand_mw"], v["net_import_mw"]) == (27803, 26894, -2074)
    assert v["firm_pct"] == 103.4


def test_card_guard_refuses_an_exporting_snapshot_until_ruled():
    # Today's behaviour, pinned honestly: the share-card guard refuses a firm share
    # over 100%, so no live card is built in an exporting hour and the previous one
    # stays up. How such an hour is shown waits for Richard's ruling (aios-harness#149);
    # when it is made, this test is replaced by tests of the ruled behaviour.
    with pytest.raises(GuardError, match=r"firm_pct out of range: 103\.4"):
        sharecards.load_cards(EXPORTING)
