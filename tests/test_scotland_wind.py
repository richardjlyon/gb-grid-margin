"""Scotland detail (engine/scotland_wind.py): zone assignment, calm counting, and the
switch-off rule (a farm paid to switch off is not counted as becalmed)."""

from engine import scotland_wind as sw


def _reg(bmu, fuel, tlf, gsp=None, cap=100):
    return {"elexonBmUnit": bmu, "fuelType": fuel, "transmissionLossFactor": tlf,
            "gspGroupId": gsp, "generationCapacity": str(cap)}


def test_zone_comes_from_gsp_or_from_the_loss_factor_it_shares():
    reg = [_reg("E_EMB-1", "OTHER", "-0.03", "_P"),       # embedded unit fixes -0.03 -> _P
           _reg("E_EMB-2", "OTHER", "0.01", "_C"),
           _reg("T_HILL-1", "WIND", "-0.03", None, 200),   # zone by loss factor
           _reg("E_DIST-1", "WIND", "0.5", "_N", 50),      # zone given directly
           _reg("T_LOND-1", "WIND", "0.01", None, 300)]    # English by loss factor
    assert sw.scottish_wind_units(reg) == {"T_HILL-1": 200.0, "E_DIST-1": 50.0}


def _row(d, sp, metered, fpn, fleet=1000, firm=500):
    return {"settlement_date": d, "settlement_period": sp, "metered_mw": metered,
            "fpn_mw": fpn, "firm_mw": firm, "fleet_mw": fleet}


def test_switched_off_half_hours_are_not_calm():
    rows = [_row("2026-01-01", 1, 20, 20),     # calm: low metered AND low plan
            _row("2026-01-01", 2, 20, 600),    # switched off: low metered, high plan
            _row("2026-01-01", 3, 30, 40),
            _row("2026-01-01", 4, 700, 700)]
    spells = sw.calm_spells(rows)
    assert [(s["start_sp"], s["end_sp"], s["hours"]) for s in spells] == [(1, 1, 0.5), (3, 3, 0.5)]


def test_year_stats_report_metered_and_available_separately():
    rows = [_row("2026-01-01", i, 50, 50 if i % 2 else 450) for i in range(1, 49)]
    y = sw.year_stats(rows)
    assert y["metered_mean_cf"] == 0.05
    assert y["mean_cf"] == 0.25
    assert y["hours_below_10pct"] == 12.0


def test_part_settled_days_are_left_out_of_the_daily_series():
    rows = [_row("2026-01-01", i, 500, 500) for i in range(1, 49)] + \
           [_row("2026-01-02", i, 0, 0) for i in range(1, 10)]
    assert [d["date"] for d in sw.daily_series(rows)] == ["2026-01-01"]


def test_rest_of_britain_excludes_scotland():
    days = [{"date": "2026-01-01", "cf": 0.05, "mean_mw": 50, "fleet_mw": 1000}]
    gb = [{"date": "2026-01-01", "mean_mw": 1050, "capacity_gw": 3.0}]
    ov = sw.gb_overlap(days, gb)
    assert ov["rest_mean_cf_on_those_days"] == 0.5     # (1050-50)/(3000-1000)


# ------------------------------------------------------------------ fetch_month, offline
def test_fetch_month_keeps_latest_run_splits_firm_and_time_weights_fpn(monkeypatch):
    """Latest settlement run wins (DF over II), Torness/Peterhead go to firm_mw not wind, and an
    FPN segment covering half the half-hour counts half."""
    from datetime import date
    met = [
        {"bmUnit": "T_HILL-1", "settlementDate": "2026-01-01", "settlementPeriod": 1,
         "settlementRunType": "II", "quantity": 10.0},
        {"bmUnit": "T_HILL-1", "settlementDate": "2026-01-01", "settlementPeriod": 1,
         "settlementRunType": "DF", "quantity": 40.0},      # 40 MWh in a half-hour = 80 MW
        {"bmUnit": "T_HILL-1", "settlementDate": "2026-01-01", "settlementPeriod": 1,
         "settlementRunType": "SF", "quantity": 25.0},
    ]
    firm = [{"bmUnit": "T_TORN-1", "settlementDate": "2026-01-01", "settlementPeriod": 1,
             "settlementRunType": "SF", "quantity": 300.0}]
    pn = [{"bmUnit": "T_HILL-1", "settlementDate": "2026-01-01", "settlementPeriod": 1,
           "timeFrom": "2026-01-01T00:00:00Z", "timeTo": "2026-01-01T00:15:00Z",
           "levelFrom": 100, "levelTo": 100},
          {"bmUnit": "T_HILL-1", "settlementDate": "2026-01-01", "settlementPeriod": 1,
           "timeFrom": "2026-01-01T00:00:00Z", "timeTo": "2026-01-01T00:15:00Z",
           "levelFrom": 100, "levelTo": 100}]                 # duplicate segment: counted once
    monkeypatch.setattr(sw, "_metered", lambda m, units: firm if units == sw.FIRM_UNITS else met)
    monkeypatch.setattr(sw, "_pn", lambda m, units: pn)
    rows = sw.fetch_month((date(2026, 1, 1), date(2026, 2, 1)), {"T_HILL-1": 200.0})
    assert rows == [{"settlement_date": "2026-01-01", "settlement_period": 1, "metered_mw": 80,
                     "fpn_mw": 50, "firm_mw": 600, "fleet_mw": 200}]


def test_calm_needs_both_metered_and_planned_low_at_the_boundary():
    """10% is the line: 99 MW of a 1,000 MW fleet is calm, 100 MW is not — on either measure."""
    assert sw._cf(_row("d", 1, 99, 0)) < sw.BELOW_10PCT
    assert not sw._cf(_row("d", 1, 100, 0)) < sw.BELOW_10PCT
    assert not sw._cf(_row("d", 1, 0, 100)) < sw.BELOW_10PCT


def test_no_wind_units_outside_scotland_and_no_non_wind_units():
    reg = [_reg("T_TORN-1", "NUCLEAR", "-0.03", "_P", 600),       # Scottish but not wind
           _reg("T_EAST-1", "WIND", "0.02", "_A", 400),           # wind, East England
           _reg("T_SOUTH-1", "WIND", "-0.02", "_N", 90)]          # wind, South Scotland
    assert sw.scottish_wind_units(reg) == {"T_SOUTH-1": 90.0}


# ------------------------------------------------------------------ the page
def test_scotland_page_is_linked_once_from_the_home_wind_entry():
    from pathlib import Path
    app = Path("site/app.js").read_text()
    assert app.count("href: 'scotland.html'") == 1
    home_wind = app[app.index("${entryFooter('wind', ["):]
    assert "scotland.html" in home_wind[:400]


def test_scotland_page_states_its_limits_and_names_no_party():
    from pathlib import Path
    text = Path("site/scotland.html").read_text() + Path("site/app.js").read_text()
    for must in ("not metered by Elexon", "no half-hourly figure for Scottish demand",
                 "switch-offs are not counted as calm", "subsidyclock.co.uk/scotland"):
        assert must in text, must
    lowered = text.lower()
    for banned in ("reform", "massey", "snp", "labour", "conservative"):
        assert banned not in lowered, banned
