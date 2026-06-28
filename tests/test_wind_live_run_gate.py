"""Independent recompute gate: the shipped wind_live_run.json must match a from-scratch
recompute off the raw FUELHH store, so the live wind lamp can never drift from source."""
import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_wind_live_run_json_matches_raw_recompute():
    payload = json.loads((REPO / "site/data/wind_live_run.json").read_text())
    nameplate = json.loads((REPO / "site/data/nameplate.json").read_text())
    nameplate_mw = nameplate["wind_gw"] * 1000

    # recompute the daily transmission CF independently from the wide CSVs
    daily: dict[str, list[float]] = {}
    for csv_path in sorted((REPO / "data/history").glob("fuelhh_*.csv")):
        with csv_path.open() as f:
            for row in csv.DictReader(f):
                w = row.get("WIND")
                if w not in ("", None):
                    daily.setdefault(row["settlement_date"], []).append(float(w))
    series = [{"date": d, "cf_pct": round(sum(v) / len(v) / nameplate_mw * 100, 1)}
              for d, v in sorted(daily.items()) if v]

    # the JSON's recent tail and run figures must equal the recompute
    assert payload["recent"] == series[-40:]
    assert payload["as_of"] == series[-1]["date"]

    # recompute the trailing run independently
    from datetime import date
    run = 0
    prev = None
    for s in reversed(series):
        if s["cf_pct"] >= payload["threshold_pct"]:
            break
        if prev and (date.fromisoformat(prev) - date.fromisoformat(s["date"])).days != 1:
            break
        run += 1
        prev = s["date"]
    assert payload["current_run_days"] == run
