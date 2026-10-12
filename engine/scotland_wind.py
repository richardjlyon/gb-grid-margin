"""Grid Margin — Scottish wind, and its absence (scotland.html).

Measured output of every transmission-connected wind farm in Scotland, half-hourly, from
Elexon's settlement meter data (B1610), alongside what the same farms told the grid they
would generate (their Final Physical Notification, FPN). The gap between the two in a windy
half-hour is wind the grid paid to switch off; in a calm half-hour there is no gap, which is
what lets the page separate "no wind" from "switched off".

Which farms are Scottish: Elexon publishes a transmission loss factor for every unit, set per
grid zone, and fills the zone itself (gspGroupId) only for embedded units. A unit's zone is the
zone whose embedded units share its loss factor; _P (North Scotland) and _N (South Scotland)
are Scotland. No hand-kept list.

Store: data/history/scotland_wind_YYYY.csv, one row per settlement half-hour.
    metered_mw   B1610 metered output, latest settlement run, summed over Scottish wind units
    fpn_mw       FPN, time-weighted mean over the half-hour, same units
    firm_mw      B1610 metered output of Torness (2 units) + Peterhead
    fleet_mw     registered capacity of the Scottish wind units that generated in that month

    uv run python -m engine.scotland_wind backfill     # 2019-03 (B1610's start) to now
    uv run python -m engine.scotland_wind update       # re-fetch the last 4 months
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

from engine import widestore
from engine.guards import require
from engine.wind_unreliability import BELOW_5PCT, BELOW_10PCT, carpet_matrix, lull_episodes

API = "https://data.elexon.co.uk/bmrs/api/v1"
REGISTER_URL = API + "/reference/bmunits/all"
B1610_URL = API + "/datasets/B1610/stream"
PN_URL = API + "/datasets/PN/stream"
SCOTTISH_ZONES = {"_P", "_N"}
FIRM_UNITS = ["T_TORN-1", "T_TORN-2", "T_PEHE-1"]   # Torness nuclear, Peterhead gas
EDGE = date(2019, 3, 1)                             # first month B1610 carries
HISTORY_DIR = Path("data/history")
PREFIX = "scotland_wind"
COLUMNS = ["settlement_date", "settlement_period", "metered_mw", "fpn_mw", "firm_mw", "fleet_mw"]
_TEXT = {"settlement_date"}
_RUN_RANK = {"II": 0, "SF": 1, "R1": 2, "R2": 3, "R3": 4, "RF": 5, "DF": 6}
_BATCH = 40
WINTER_MONTHS = {"12", "01", "02"}
PEAK_PERIODS = range(33, 39)                        # 16:00–19:00 local


# ------------------------------------------------------------------ fetch
def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "gridmargin.co.uk"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def scottish_wind_units(register: list[dict]) -> dict[str, float]:
    """elexonBmUnit -> registered capacity (MW) for every WIND unit in a Scottish zone."""
    by_tlf: dict[str, Counter] = defaultdict(Counter)
    for u in register:
        if u.get("gspGroupId") and u.get("transmissionLossFactor") is not None:
            by_tlf[u["transmissionLossFactor"]][u["gspGroupId"]] += 1
    tlf_zone = {t: c.most_common(1)[0][0] for t, c in by_tlf.items()}
    out = {}
    for u in register:
        bmu = u.get("elexonBmUnit")
        if not bmu or u.get("fuelType") != "WIND":
            continue
        zone = u.get("gspGroupId") or tlf_zone.get(u.get("transmissionLossFactor"))
        if zone in SCOTTISH_ZONES:
            out[bmu] = float(u.get("generationCapacity") or 0)
    return out


def _months(start: date, end: date) -> list[tuple[date, date]]:
    out, d = [], start.replace(day=1)
    while d < end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        out.append((d, min(nxt, end)))
        d = nxt
    return out


def _q(units: list[str]) -> str:
    return "&".join(f"bmUnit={u}" for u in units)


def _metered(month: tuple[date, date], units: list[str]) -> list[dict]:
    a, z = month
    return _get(f"{B1610_URL}?from={a}T00:00Z&to={z}T00:00Z&{_q(units)}")


def _pn(month: tuple[date, date], units: list[str]) -> list[dict]:
    a, z = month
    return _get(f"{PN_URL}?from={a}T00:00Z&to={z}T00:00Z&{_q(units)}")


def fetch_month(month: tuple[date, date], caps: dict[str, float]) -> list[dict]:
    """One calendar month of store rows (all its half-hours that B1610 has settled)."""
    wind = sorted(caps)
    batches = [wind[i:i + _BATCH] for i in range(0, len(wind), _BATCH)]
    with cf.ThreadPoolExecutor(6) as ex:
        met = list(ex.map(lambda b: _metered(month, b), batches + [FIRM_UNITS]))
        pns = list(ex.map(lambda b: _pn(month, b), batches))

    best: dict[tuple, tuple[int, float]] = {}
    for rows in met:
        for r in rows:
            k = (r["bmUnit"], r["settlementDate"], r["settlementPeriod"])
            rank = _RUN_RANK.get(r["settlementRunType"], -1)
            if k not in best or rank > best[k][0]:
                best[k] = (rank, float(r["quantity"]))
    metered, firm = defaultdict(float), defaultdict(float)
    active: set[str] = set()
    for (bmu, d, sp), (_, mwh) in best.items():
        if bmu in FIRM_UNITS:
            firm[(d, sp)] += mwh * 2
        else:
            metered[(d, sp)] += mwh * 2
            if mwh > 0.5:
                active.add(bmu)
    fleet = round(sum(caps[u] for u in active))

    fpn: dict[tuple, float] = defaultdict(float)
    seen = set()
    for rows in pns:
        for r in rows:
            k = (r["bmUnit"], r["timeFrom"], r["timeTo"])
            if k in seen:
                continue
            seen.add(k)
            t0 = datetime.fromisoformat(r["timeFrom"].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(r["timeTo"].replace("Z", "+00:00"))
            frac = (t1 - t0).total_seconds() / 1800
            fpn[(r["settlementDate"], r["settlementPeriod"])] += (r["levelFrom"] + r["levelTo"]) / 2 * frac

    return [{"settlement_date": d, "settlement_period": sp,
             "metered_mw": round(metered[(d, sp)]), "fpn_mw": round(fpn.get((d, sp), 0.0)),
             "firm_mw": round(firm.get((d, sp), 0.0)), "fleet_mw": fleet}
            for (d, sp) in sorted(metered)]


def _path_for(settlement_date: str) -> Path:
    return HISTORY_DIR / f"{PREFIX}_{settlement_date[:4]}.csv"


def _write(rows: list[dict]) -> int:
    # "update": recent months are re-fetched while settlement runs (II -> SF -> R1...) land
    return widestore.append_rows(rows, COLUMNS, _TEXT, _path_for, on_revision="update")


def run_fetch(start: date, end: date) -> int:
    caps = scottish_wind_units(_get(REGISTER_URL))
    require(len(caps) > 100, f"only {len(caps)} Scottish wind units found in the register")
    total = 0
    for m in _months(start, end):
        rows = fetch_month(m, caps)
        _write(rows)
        total += len(rows)
        print(f"  {m[0]:%Y-%m}: {len(rows)} half-hours, fleet {rows[-1]['fleet_mw'] if rows else 0} MW")
    print(f"[ok] {total} half-hours written, {len(caps)} Scottish wind units")
    return 0


def read_store() -> list[dict]:
    return widestore.read_store(HISTORY_DIR, f"{PREFIX}_*.csv", COLUMNS, _TEXT)


# ------------------------------------------------------------------ analysis
def _avail(r: dict) -> float:
    """What the wind allowed: the larger of what was metered and what the farms planned (FPN).
    A farm paid to switch off meters little but planned a lot, so this keeps the grid's
    switch-off instructions from being counted as calm."""
    return max(0.0, r["metered_mw"], r["fpn_mw"])


def _cf(r: dict) -> float:
    return min(1.0, _avail(r) / r["fleet_mw"]) if r["fleet_mw"] else 0.0


def daily_series(rows: list[dict]) -> list[dict]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[r["settlement_date"]].append(r)
    out = []
    for d in sorted(by_day):
        rs = by_day[d]
        if len(rs) < 46:          # a part-settled edge day would read as a false calm
            continue
        fleet = rs[-1]["fleet_mw"]
        out.append({"date": d, "cf": round(mean(_cf(r) for r in rs), 4),
                    "mean_mw": round(mean(_avail(r) for r in rs)), "fleet_mw": fleet})
    return out


def calm_spells(rows: list[dict], threshold: float = BELOW_10PCT) -> list[dict]:
    """Maximal runs of consecutive half-hours with output below `threshold` of the fleet."""
    out, run = [], []

    def flush():
        if run:
            out.append({"start": run[0]["settlement_date"], "start_sp": run[0]["settlement_period"],
                        "end": run[-1]["settlement_date"], "end_sp": run[-1]["settlement_period"],
                        "hours": len(run) / 2,
                        "mean_mw": round(mean(_avail(r) for r in run)),
                        "fleet_mw": run[-1]["fleet_mw"],
                        "min_mw": min(r["metered_mw"] for r in run),
                        "fpn_mean_mw": round(mean(r["fpn_mw"] for r in run)),
                        "firm_mean_mw": round(mean(r["firm_mw"] for r in run))})

    for r in rows:
        if _cf(r) < threshold:
            run.append(r)
        else:
            flush()
            run = []
    flush()
    return out


def _window(rows: list[dict], days: int) -> list[dict]:
    end = date.fromisoformat(rows[-1]["settlement_date"])
    start = (end - timedelta(days=days - 1)).isoformat()
    return [r for r in rows if r["settlement_date"] >= start]


def year_stats(rows: list[dict]) -> dict:
    n = len(rows)
    cfs = [_cf(r) for r in rows]
    spells = calm_spells(rows)
    longest = max(spells, key=lambda s: s["hours"]) if spells else None
    low = min(rows, key=_avail)
    calm = [r for r, c in zip(rows, cfs) if c < BELOW_10PCT]
    return {
        "from": rows[0]["settlement_date"], "to": rows[-1]["settlement_date"],
        "half_hours": n,
        "fleet_mw": rows[-1]["fleet_mw"],
        "mean_mw": round(mean(r["metered_mw"] for r in rows)),
        "metered_mean_cf": round(mean(max(0.0, r["metered_mw"]) / r["fleet_mw"] for r in rows), 4),
        "mean_cf": round(mean(cfs), 4),          # on what the wind allowed (metered or planned)
        "hours_below_10pct": sum(c < BELOW_10PCT for c in cfs) / 2,
        "hours_below_5pct": sum(c < BELOW_5PCT for c in cfs) / 2,
        "share_below_10pct": round(sum(c < BELOW_10PCT for c in cfs) / n, 4),
        "spells_24h_plus": sum(s["hours"] >= 24 for s in spells),
        "longest_calm": longest,
        "avail_mean_mw": round(mean(_avail(r) for r in rows)),
        "lowest": {"date": low["settlement_date"], "sp": low["settlement_period"],
                   "mw": round(_avail(low)), "fleet_mw": low["fleet_mw"]},
        # in a calm, what the farms had told the grid they would make: if this is also low,
        # the calm was the weather, not the grid switching farms off
        "calm_fpn_mean_mw": round(mean(r["fpn_mw"] for r in calm)) if calm else None,
        "calm_metered_mean_mw": round(mean(r["metered_mw"] for r in calm)) if calm else None,
        "calm_firm_mean_mw": round(mean(r["firm_mw"] for r in calm)) if calm else None,
    }


def winter_peak(rows: list[dict]) -> list[dict]:
    """Per winter (Dec–Feb, labelled by its January), output at 4–7pm: the hours of
    highest demand. Share of those half-hours below 10%, and the 5th-percentile output."""
    by_w: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        mo = r["settlement_date"][5:7]
        if mo in WINTER_MONTHS and r["settlement_period"] in PEAK_PERIODS:
            y = int(r["settlement_date"][:4]) + (1 if mo == "12" else 0)
            by_w[str(y)].append(r)
    out = []
    for w in sorted(by_w):
        rs = by_w[w]
        if len(rs) < 80 * 6:      # a winter needs most of its 90 evenings to be shown
            continue
        mws = sorted(round(_avail(r)) for r in rs)
        out.append({"winter": f"{int(w) - 1}–{w[2:]}", "half_hours": len(rs),
                    "share_below_10pct": round(sum(_cf(r) < BELOW_10PCT for r in rs) / len(rs), 4),
                    "p5_mw": mws[int(0.05 * len(mws))], "median_mw": mws[len(mws) // 2],
                    "fleet_mw": rs[-1]["fleet_mw"]})
    return out


def gb_overlap(days: list[dict], gb_days: list[dict]) -> dict | None:
    """On the days Scottish wind averaged under 10%, how wind in the REST of Britain fared:
    (GB wind output − Scottish output) ÷ (GB wind capacity − Scottish capacity). Subtracting
    Scotland stops the comparison from partly measuring Scotland against itself."""
    gb = {d["date"]: d for d in gb_days}
    rest: dict[str, float] = {}
    for d in days:
        g = gb.get(d["date"])
        if not g:
            continue
        cap = g["capacity_gw"] * 1000 - d["fleet_mw"]
        if cap > 0:
            rest[d["date"]] = max(0.0, g["mean_mw"] - d["mean_mw"]) / cap
    calm = [d["date"] for d in days if d["cf"] < BELOW_10PCT and d["date"] in rest]
    if not calm:
        return None
    return {"scot_calm_days": len(calm),
            "rest_below_10pct": sum(rest[d] < BELOW_10PCT for d in calm),
            "rest_below_15pct": sum(rest[d] < 0.15 for d in calm),
            "rest_mean_cf_on_those_days": round(mean(rest[d] for d in calm), 4),
            "rest_mean_cf_all_days": round(mean(rest.values()), 4)}


# DESNZ Energy Trends regional table: Scottish wind generation (onshore + offshore), all farms,
# calendar 2025. Used only to state how much of Scottish wind Elexon's meters see.
OFFICIAL_SCOT_WIND_TWH = {2025: 30.9}
OFFICIAL_SOURCE = "DESNZ, Regional Renewable Statistics 2003-2025: Generation (Scotland, wind)"
OFFICIAL_URL = "https://www.gov.uk/government/statistics/regional-renewable-statistics"


def coverage(rows: list[dict]) -> dict | None:
    """Metered (B1610) Scottish wind for the latest calendar year with an official total, against
    that total. B1610 sees transmission-connected farms only, so it comes in short."""
    for year in sorted(OFFICIAL_SCOT_WIND_TWH, reverse=True):
        yr = [r for r in rows if r["settlement_date"].startswith(str(year))]
        if len(yr) < 17000:
            continue
        twh = sum(max(0.0, r["metered_mw"]) for r in yr) / 2 / 1e6
        off = OFFICIAL_SCOT_WIND_TWH[year]
        return {"year": year, "metered_twh": round(twh, 2), "official_twh": off,
                "shortfall": round(1 - twh / off, 3), "official_source": OFFICIAL_SOURCE,
                "official_url": OFFICIAL_URL}
    return None


_BASIS = (
    "Scottish wind = every transmission-connected wind unit in Elexon's register whose grid zone "
    "is North Scotland (_P) or South Scotland (_N); the zone comes from gspGroupId where Elexon "
    "fills it and otherwise from the unit's transmission loss factor, which Elexon sets per zone. "
    "Output = Elexon B1610 settlement meter data, latest settlement run. Capacity = registered "
    "capacity of the units that generated in the month. Planned output = Final Physical "
    "Notification (FPN). What the wind allowed = the larger of metered and planned output, so a "
    "farm paid to switch off is not counted as becalmed. A calm is a run of half-hours in which "
    "what the wind allowed stayed below 10% of capacity. Firm = metered Torness + Peterhead. "
    "Small distribution-connected wind is not metered by Elexon and is not included."
)
_SOURCE = "Elexon B1610 (settlement meter data) + PN (physical notifications) + BM unit register"


def build_payload(rows: list[dict], gb_days: list[dict], generated_utc: str) -> dict:
    rows = sorted(rows, key=lambda r: (r["settlement_date"], r["settlement_period"]))
    days = daily_series(rows)
    year = _window(rows, 365)
    lulls = lull_episodes(days)
    from engine.derived import partial_years
    return {
        "basis": _BASIS, "source": _SOURCE, "generated_utc": generated_utc,
        "range": {"from": days[0]["date"], "to": days[-1]["date"]},
        "partial_years": partial_years([d["date"] for d in days]),
        "thresholds": {"below_10pct": BELOW_10PCT, "below_5pct": BELOW_5PCT},
        "windy_anchor_cf": 0.45,
        "carpet": carpet_matrix(days),
        "lulls": lulls,
        "summary": {"record_lull": max(lulls, key=lambda l: l["days"]) if lulls else None,
                    "record_lull_ties": [l for l in lulls if lulls and l["days"] == max(x["days"] for x in lulls)],
                    "lulls_3d_plus": sum(l["days"] >= 3 for l in lulls),
                    "lulls_7d_plus": sum(l["days"] >= 7 for l in lulls)},
        "year": year_stats(year),
        "year_spells": sorted(calm_spells(year), key=lambda s: -s["hours"])[:10],
        "winter_peak": winter_peak(rows),
        "gb_overlap": gb_overlap(days, gb_days),
        "coverage": coverage(rows),
        "longest_calm_trace": _trace(rows, year_stats(year)["longest_calm"]),
    }


def _trace(rows: list[dict], spell: dict | None, pad_days: int = 2) -> list[dict]:
    """The half-hours around the year's longest calm, for the 'firm Scotland' chart."""
    if not spell:
        return []
    a = (date.fromisoformat(spell["start"]) - timedelta(days=pad_days)).isoformat()
    z = (date.fromisoformat(spell["end"]) + timedelta(days=pad_days)).isoformat()
    return [{"d": r["settlement_date"], "sp": r["settlement_period"], "w": round(_avail(r)),
             "f": r["firm_mw"], "cap": r["fleet_mw"]}
            for r in rows if a <= r["settlement_date"] <= z]


def guard_payload(p: dict) -> None:
    y = p["year"]
    require(y["half_hours"] >= 17000, f"trailing year has only {y['half_hours']} half-hours")
    require(8000 <= y["fleet_mw"] <= 30000, f"Scottish fleet {y['fleet_mw']} MW implausible")
    require(0.10 <= y["mean_cf"] <= 0.50, f"mean CF {y['mean_cf']} implausible")
    require(y["mean_cf"] >= y["metered_mean_cf"], "available output below metered — join error")
    for cells in p["carpet"]["rows"].values():
        for v in cells:
            require(v is None or 0.0 <= v <= 1.0, f"carpet cf {v} out of range")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    today = date.today()
    if args[:1] == ["backfill"]:
        return run_fetch(EDGE, today)
    if args[:1] == ["update"]:
        start = (today.replace(day=1) - timedelta(days=95)).replace(day=1)
        return run_fetch(start, today)
    print("usage: python -m engine.scotland_wind backfill|update", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
