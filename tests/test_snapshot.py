from engine import snapshot
from engine.grid_engine import compute_verdict
from engine.models import NameplateSeries

# A synthetic half-hour: transmission wind 2000, gas 9000, nuclear 3000, biomass 1000,
# net imports = INTFR 1000 + INTNED 500 = 1500; embedded solar 4000, embedded wind 800.
FUELHH = {"settlement_date": "2026-06-24", "settlement_period": 24,
          "period_start_utc": "2026-06-24T10:30:00Z",
          "WIND": 2000, "CCGT": 9000, "OCGT": 0, "NUCLEAR": 3000, "BIOMASS": 1000,
          "NPSHYD": 100, "OTHER": 200, "PS": -500, "COAL": 0, "OIL": 0,
          "INTFR": 1000, "INTNED": 500}
EMB = {"settlement_date": "2026-06-24", "settlement_period": 24,
       "period_start_utc": "2026-06-24T10:30:00Z",
       "embedded_solar_mw": 4000, "embedded_wind_mw": 800,
       "embedded_solar_capacity_mw": 16000}
NS = NameplateSeries.model_validate_json(open("data/nameplate_series.json").read())
CAPS = {"INTFR": 2000, "INTNED": 1000}  # both legs reporting -> active cap 3000

def test_frame_matches_compute_verdict():
    mix = {c: (FUELHH.get(c) or 0) for c in __import__("engine.reliability", fromlist=["_MIX_COLUMNS"])._MIX_COLUMNS}
    v = compute_verdict(mix, {"solar_mw": 4000, "wind_mw": 800, "time": EMB["period_start_utc"]})
    f = snapshot.extract_frame(FUELHH, EMB, NS, CAPS, price=77.0)
    assert f["firm_mw"] == v["firm_mw"]
    assert f["notfirm_mw"] == v["notfirm_mw"]
    assert f["demand_mw"] == v["national_demand_mw"]
    assert f["net_import_mw"] == 1500
    assert f["firm_pct"] == v["firm_pct"]
    # import CF = max(1500,0)/3000 = 0.5 -> 50.0%
    assert f["import_cf_pct"] == 50.0
    assert f["price_gbp_mwh"] == 77.0
    assert f["t"] == "2026-06-24T10:30:00Z" and f["sp"] == 24
