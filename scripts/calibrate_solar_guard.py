"""Measure the real NESO-embedded-forecast vs PV_Live-outturn divergence.

The build guard asserts these two agree within 10%. But NESO's
EMBEDDED_SOLAR_FORECAST is a *forecast* and PV_Live is a *measured outturn*, so
the guard is policing forecast error, not feed integrity. This measures the
actual half-hourly divergence over a long window so any new tolerance is set
from the distribution rather than picked.

Only half-hours above the guard's own floor (1000 MW) count, since below that
the guard is skipped. The window comes from the embedded store's own extent,
because that store lags the live feed by ~3 weeks.
"""
from __future__ import annotations

import statistics
from datetime import date

from engine import embedded_history as eh
from engine import grid_engine as ge

FLOOR = ge.SOLAR_CROSSCHECK_FLOOR_MW

store = eh.read_store()
store_days = sorted({str(r["settlement_date"]) for r in store})
START = date.fromisoformat(store_days[0])
END = date.fromisoformat(store_days[-1])
print(f"embedded store: {len(store)} half-hours, {START} .. {END}")
print(f"floor {FLOOR} MW, current tolerance {ge.SOLAR_CROSSCHECK_TOL:.0%}\n")

pv_by_time: dict[str, float] = {}
# Fetch in yearly slices: one long request times out.
cur = START
while cur <= END:
    stop = min(date(cur.year, 12, 31), END)
    series = eh.fetch_pvlive(cur, stop)
    for t, v in series.rows():
        pv_by_time[str(t)[:16].replace(" ", "T")] = v
    cur = date(stop.year + 1, 1, 1)
print(f"PV_Live half-hours fetched: {len(pv_by_time)}")

diffs: list[float] = []
signed: list[float] = []
midday: list[float] = []
for r in store:
    key = str(r["period_start_utc"])[:16]
    pvv = pv_by_time.get(key)
    if pvv is None or pvv < FLOOR:
        continue
    neso = float(r["embedded_solar_mw"])
    d = abs(neso - pvv) / pvv * 100
    diffs.append(d)
    signed.append((neso - pvv) / pvv * 100)
    if 10 <= int(key[11:13]) < 13:
        midday.append(d)

print(f"paired half-hours above floor: {len(diffs)}")
if not diffs:
    raise SystemExit("no overlap — cannot calibrate")

diffs.sort()


def pct(p: float) -> float:
    return diffs[min(len(diffs) - 1, int(len(diffs) * p / 100))]


print("\nabsolute divergence |NESO-PVLive|/PVLive, percent:")
print(f"  mean   {statistics.mean(diffs):6.1f}")
print(f"  median {pct(50):6.1f}")
for p in (75, 90, 95, 99, 99.5):
    print(f"  p{p:<5} {pct(p):6.1f}")
print(f"  max    {diffs[-1]:6.1f}")
print(f"\nsigned mean (bias): {statistics.mean(signed):+.1f}%")

print("\nshare of half-hours that would TRIP a given tolerance:")
for tol in (10, 15, 20, 25, 30, 40, 50, 60):
    trip = sum(1 for d in diffs if d > tol) / len(diffs) * 100
    print(f"  tol {tol:3d}%  ->  {trip:6.2f}% of half-hours trip")

# The guard fires on ONE half-hour (the build's snapshot), so a build's daily
# failure chance is the trip rate in the window the cron actually lands in.
if midday:
    midday.sort()
    print("\nrestricted to 10:00-13:00 UTC (where the daily cron lands):")
    print(f"  n={len(midday)}  median {midday[len(midday)//2]:.1f}  "
          f"p95 {midday[int(len(midday)*0.95)]:.1f}  max {midday[-1]:.1f}")
    for tol in (10, 20, 25, 30, 40, 50):
        trip = sum(1 for d in midday if d > tol) / len(midday) * 100
        print(f"  tol {tol:3d}%  ->  {trip:6.2f}% of midday half-hours trip")
