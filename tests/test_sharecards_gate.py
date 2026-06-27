"""Independent recompute: assert every card figure equals a value derived
straight from site/data/*.json, by a code path that does NOT import the card
builders' formatting. Catches any drift between a card and the dashboard."""
import json
from pathlib import Path

from engine import sharecards

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "site" / "data"


def _load(name):
    return json.loads((DATA / name).read_text())


def test_card_figures_trace_to_source():
    cards, _ = sharecards.load_cards(DATA)
    by = {c["slug"]: c for c in cards}

    v = _load("latest.json")["verdict"]
    assert by["firm-now"]["figure"] == f"{int(100 - v['firm_pct'] + 0.5)}% unreliable"

    np = _load("nameplate.json")
    share = (v["wind_mw"] + v["solar_mw"]) / (np["wind_plus_solar_gw"] * 1000) * 100
    assert by["capacity-trap"]["figure"] == f"{share:.0f}% of capacity"

    wu = _load("wind_unreliability.json")
    s = wu["summary"]
    assert by["wind-stripe"]["figure"] == f"{s['mean_cf'] * 100:.0f}% mean"
    assert by["days-below-10"]["figure"] == f"{s['below_10pct_days']} days"
    assert by["lowest-day"]["figure"] == f"{s['lowest_day']['cf'] * 100:.1f}%"
    assert by["longest-calm"]["figure"] == f"{s['record_lull']['days']} days"


def test_settled_cards_carry_combined_basis_caveat():
    cards, _ = sharecards.load_cards(DATA)
    for slug in ("wind-stripe", "days-below-10", "lowest-day", "longest-calm"):
        c = next(c for c in cards if c["slug"] == slug)
        assert "combined" in (c["caveat"] or "").lower()


def test_reliability_stripe_figure_traces_to_source():
    """Recompute 'N% mean unreliable' independently from reliability_year.json and
    assert it matches what load_cards produces. Catches any drift in the card figure."""
    cards, _ = sharecards.load_cards(DATA)
    by = {c["slug"]: c for c in cards}

    rel = _load("reliability_year.json")
    nn = [v for v in rel["values"] if v is not None]
    expected = f"{round((1 - sum(nn) / len(nn)) * 100)}% mean unreliable"
    assert by["reliability-stripe"]["figure"] == expected
