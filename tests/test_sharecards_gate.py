"""Independent recompute: assert each card figure equals a value derived straight
from site/data/*.json, by a path that does NOT reuse the builders' formatting."""
import json
from pathlib import Path

from engine import sharecards

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "site" / "data"


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


def test_recent_lull_figure_traces_to_source():
    cards, _ = sharecards.load_cards(DATA)
    c = next(c for c in cards if c["slug"] == "recent-lull")
    wu = _load("wind_unreliability.json")
    latest3 = [l for l in wu["lulls"] if l["days"] >= 3][-1]
    assert c["figure"] == f"{latest3['days']} days"
    assert c["caveat"] and "combined" in c["caveat"].lower()
