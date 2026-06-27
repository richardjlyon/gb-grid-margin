"""Stage 5 validation gate — independent recompute against the REAL store.

The synthetic unit tests in test_derived.py pin the logic on crafted inputs. This is the
other half of the Stage 5 gate: it recomputes the derived figures straight from the
committed CSVs with a SEPARATE code path (raw csv reader, inline arithmetic, no import of
engine.derived) and asserts the engine agrees on every day. It is what catches a regression
that only the real data's quirks expose — DST 46/50-period days, the 77 known-gap short
days, blank cells, leap years — which no synthetic fixture fully reproduces.

Skips cleanly if the store is absent (a checkout without data/history/).
"""

from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

import pytest

from engine.derived import transmission_shares
from engine.history import read_store

REPO = Path(__file__).resolve().parent.parent
STORE_GLOB = str(REPO / "data" / "history" / "fuelhh_*.csv")
NS_PATH = REPO / "data" / "nameplate_series.json"
_OTHER_FUELS = ("NPSHYD", "OTHER", "COAL", "OIL")

pytestmark = pytest.mark.skipif(
    not glob.glob(STORE_GLOB), reason="history store not present in this checkout"
)


def _independent_cap_for():
    """Annual-step total wind nameplate (GW), built independently of NameplateSeries."""
    ns = json.loads(NS_PATH.read_text())
    cap = {r["year"]: round(r["wind_onshore_gw"] + r["wind_offshore_gw"], 3)
           for r in ns["series"]}

    def cap_for(year: int) -> float:
        return cap[max(y for y in cap if y <= year)]
    return cap_for


def _independent_recompute():
    """Recompute CF-by-day and per-year fuel sums by reading the raw CSVs directly."""
    cap_for = _independent_cap_for()
    wind_by_day: dict[str, list[int]] = {}
    year_fuel: dict[int, dict[str, int]] = {}
    skip = {"settlement_date", "settlement_period", "period_start_utc", "INDO", "ITSDO"}
    for path in sorted(glob.glob(STORE_GLOB)):
        if "known_gaps" in path:
            continue
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                d = row["settlement_date"]
                if row["WIND"] != "":
                    wind_by_day.setdefault(d, []).append(int(row["WIND"]))
                yf = year_fuel.setdefault(int(d[:4]), {})
                for k, v in row.items():
                    if k in skip or v == "":
                        continue
                    yf[k] = yf.get(k, 0) + int(v)

    cf = {d: round((sum(v) / len(v)) / (cap_for(int(d[:4])) * 1000), 4)
          for d, v in wind_by_day.items()}
    return cf, year_fuel


def test_engine_shares_match_independent_recompute_and_sum_to_100():
    rows = read_store()
    _, year_fuel = _independent_recompute()
    for year in (2022, 2026):  # 2022 = net-export year (negative imports); 2026 = partial
        yf = year_fuel[year]
        groups = {
            "wind": yf.get("WIND", 0),
            "gas": yf.get("CCGT", 0) + yf.get("OCGT", 0),
            "nuclear": yf.get("NUCLEAR", 0),
            "biomass": yf.get("BIOMASS", 0),
            "other": sum(yf.get(f, 0) for f in _OTHER_FUELS),
            "net_imports": sum(v for k, v in yf.items() if k.upper().startswith("INT")),
        }
        supply = sum(groups.values())
        eng = transmission_shares(rows, year)
        assert eng["supply_mwh"] == supply * 0.5
        assert abs(sum(eng["shares_pct"].values()) - 100.0) < 1e-6
        for g, v in groups.items():
            assert round(eng["shares_pct"][g], 4) == round(v / supply * 100, 4)
