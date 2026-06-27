# tests/test_wind_unreliability_gate.py
"""Independent gate: recompute combined daily wind CF straight from the raw CSV store
(data/history/), sharing no code with engine.wind_unreliability, and assert the published
carpet cells + record lull match."""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "wind_unreliability.json"
HIST = ROOT / "data" / "history"
NAMEPLATE = ROOT / "data" / "nameplate_series.json"


def _wind_gw(year: int) -> float:
    """wind_onshore_gw + wind_offshore_gw, annual-step (most recent entry with year <= `year`)."""
    series = json.loads(NAMEPLATE.read_text())["series"]
    s = max((s for s in series if s["year"] <= year), key=lambda s: s["year"])
    return s["wind_onshore_gw"] + s["wind_offshore_gw"]


def _raw_combined_daily_cf(day: str):
    """mean over joined half-hours of (WIND + embedded_wind_mw) / (wind_gw*1000), from raw CSV."""
    y = day[:4]
    emb: dict[str, float] = {}
    with open(HIST / f"embedded_{y}.csv") as f:
        for r in csv.DictReader(f):
            if r["settlement_date"] == day:
                emb[r["settlement_period"]] = float(r["embedded_wind_mw"]) if r["embedded_wind_mw"] else 0.0
    vals = []
    with open(HIST / f"fuelhh_{y}.csv") as f:
        for r in csv.DictReader(f):
            if r["settlement_date"] != day or r["settlement_period"] not in emb:
                continue
            trans = float(r["WIND"]) if r["WIND"] else 0.0
            vals.append(trans + emb[r["settlement_period"]])
    if not vals:
        return None
    return round((sum(vals) / len(vals)) / (_wind_gw(int(y)) * 1000), 4)


def test_published_carpet_cells_match_raw_csv_recompute():
    payload = json.loads(DATA.read_text())
    doy, rows = payload["carpet"]["doy"], payload["carpet"]["rows"]
    # Sample: the record-low day (guaranteed present), a leap day, a midsummer and a midwinter day.
    samples = {payload["summary"]["lowest_day"]["date"], "2020-02-29", "2021-07-15", "2018-01-17"}
    checked = 0
    for day in samples:
        y, md = day[:4], day[5:]
        if y not in rows or md not in doy:
            continue
        published = rows[y][doy.index(md)]
        if published is None:
            continue
        assert _raw_combined_daily_cf(day) == published, f"{day}: raw != published {published}"
        checked += 1
    assert checked >= 2, "expected at least 2 sample days to verify"


def test_record_lull_matches_independent_run_finder():
    payload = json.loads(DATA.read_text())
    doy, rows = payload["carpet"]["doy"], payload["carpet"]["rows"]
    daily = []
    for y in payload["carpet"]["years"]:
        for i, md in enumerate(doy):
            cf = rows[str(y)][i]
            if cf is not None:
                daily.append((f"{y}-{md}", cf))
    daily.sort()
    best = cur = 0
    prev = None
    for d, cf in daily:
        adj = prev is not None and date.fromisoformat(d) - date.fromisoformat(prev) == timedelta(days=1)
        cur = cur + 1 if (cf < 0.10 and adj and cur) else (1 if cf < 0.10 else 0)
        best = max(best, cur)
        prev = d
    assert payload["summary"]["record_lull"]["days"] == best
