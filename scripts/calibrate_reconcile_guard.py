"""Measure the real gap between the supply-side demand rebuild and Elexon INDO.

The build guard (sanity_check) and its browser twin (site/live.js) rebuild national
demand from FUELINST and compare it with INDO + embedded. The guard exists to catch a
GROSS feed fault (zeroed, doubled or wrong-unit), each a ~100% error, not to certify
accuracy. A fixed 12% tolerance tripped on 2026-11-09 03:50Z (15.0%) because the normal
gap is structural and grows as demand falls overnight. This measures that gap over the
whole settled store so any tolerance is set from the distribution rather than picked.

Each half-hour is rebuilt exactly as compute_verdict does (positive transmission
generation excluding interconnectors and pumped storage, plus net interconnector flow,
plus embedded solar and wind) and compared with INDO + the same embedded figures, as
sanity_check does. The settled store holds half-hour averages; the live guard reads one
5-min snapshot, which adds a little noise on top of what this measures.

Run: uv run python -m scripts.calibrate_reconcile_guard
"""
from __future__ import annotations

from engine import embedded_history as eh
from engine import grid_engine as ge
from engine import history as fh

fuel = fh.read_store()
emb = {str(r["period_start_utc"]): r for r in eh.read_store()}
print(f"settled store: {len(fuel)} half-hours; embedded store: {len(emb)}")
print(f"current tolerance {ge.RECONCILE_TOL:.0%}\n")

FUELS = ("BIOMASS", "CCGT", "COAL", "NPSHYD", "NUCLEAR", "OCGT", "OIL", "OTHER", "PS", "WIND")


def rebuild(row: dict, scale: float = 1.0, drop: str | None = None) -> float:
    mix = {k: float(v) * scale for k, v in row.items()
           if (k in FUELS or k.upper().startswith("INT")) and v not in (None, "")}
    if drop:
        mix.pop(drop, None)
    gen = sum(v for k, v in mix.items() if v > 0 and k != "PS" and not k.upper().startswith("INT"))
    return gen + sum(v for k, v in mix.items() if k.upper().startswith("INT"))


gaps: list[float] = []
signed: list[float] = []
by_hour: dict[int, list[float]] = {}
by_year: dict[str, list[float]] = {}
worst: list[tuple[float, str]] = []
for r in fuel:
    key = str(r["period_start_utc"])
    e = emb.get(key)
    indo = r.get("INDO")
    if e is None or indo in (None, "") or float(indo) <= 0:
        continue
    embedded = float(e["embedded_solar_mw"] or 0) + float(e["embedded_wind_mw"] or 0)
    expected = float(indo) + embedded
    got = rebuild(r) + embedded
    d = abs(got - expected) / expected * 100
    gaps.append(d)
    signed.append((got - expected) / expected * 100)
    by_hour.setdefault(int(key[11:13]), []).append(d)
    by_year.setdefault(key[:4], []).append(d)
    worst.append((d, key))

if not gaps:
    raise SystemExit("no overlap - cannot calibrate")
n = len(gaps)
gaps_sorted = sorted(gaps)


def pct(xs: list[float], p: float) -> float:
    return xs[min(len(xs) - 1, int(len(xs) * p / 100))]


print(f"paired half-hours: {n}")
print("absolute gap |rebuild - INDO| / (INDO + embedded), percent:")
print(f"  median {pct(gaps_sorted, 50):6.1f}")
for p in (90, 95, 99, 99.9, 99.99):
    print(f"  p{p:<6} {pct(gaps_sorted, p):6.1f}")
print(f"  max     {gaps_sorted[-1]:6.1f}")
print(f"signed mean (bias): {sum(signed) / n:+.1f}%  (rebuild runs above INDO)")

print("\nby hour of day (UTC): p99 / max")
for h in sorted(by_hour):
    xs = sorted(by_hour[h])
    print(f"  {h:02d}:00  {pct(xs, 99):5.1f} / {xs[-1]:5.1f}")

print("\nby year: p99 / max (the gap has grown as storage and exports grew)")
for y in sorted(by_year):
    xs = sorted(by_year[y])
    print(f"  {y}  {pct(xs, 99):5.1f} / {xs[-1]:5.1f}")

print("\nworst 10 half-hours:")
for d, k in sorted(worst, reverse=True)[:10]:
    print(f"  {k}  {d:5.1f}%")

print("\nshare of half-hours that would TRIP a given tolerance:")
for tol in (12, 15, 20, 25, 30, 33, 35, 40, 50):
    trip = sum(1 for d in gaps if d > tol) / n * 100
    print(f"  tol {tol:3d}%  ->  {trip:7.3f}% trip")

# The normal gap is one-sided: on ordinary nights (pumping, exports, little wind) the
# rebuild runs ABOVE INDO, to +20.4% by 2026-03-24 03:30Z. Every half-hour more than
# ~18% BELOW INDO in the store is a hole in the settled data (CCGT or WIND zeroed) -
# exactly the fault the guard exists for.
print("\nlargest gap ABOVE INDO (normal nights) and largest BELOW (store holes):")
print(f"  above  {max(signed):+6.1f}%")
print(f"  below  {min(signed):+6.1f}%")

# What the guard is for: the smallest gap each gross fault produces when injected into
# a CLEAN half-hour (one the old 12% tolerance already passed). Half-hours that are
# themselves store holes are left out: doubling a zeroed feed changes nothing. On a clean
# half-hour all three faults miss by about the transmission share of demand, which is
# smallest on a sunny summer weekend when embedded solar is large.
print("\nsmallest gap each gross fault produces on clean half-hours "
      "(it must stay ABOVE the tolerance):")
faults = {
    "zeroed FUELINST": dict(scale=0.0),
    "doubled FUELINST": dict(scale=2.0),
    "wrong unit (GW not MW)": dict(scale=0.001),
}
for name, kw in faults.items():
    low, at = 1e9, ""
    for r in fuel:
        e = emb.get(str(r["period_start_utc"]))
        indo = r.get("INDO")
        if e is None or indo in (None, "") or float(indo) <= 0:
            continue
        embedded = float(e["embedded_solar_mw"] or 0) + float(e["embedded_wind_mw"] or 0)
        expected = float(indo) + embedded
        if abs(rebuild(r) + embedded - expected) / expected > 0.12:
            continue
        g = abs(rebuild(r, **kw) + embedded - expected) / expected * 100
        if g < low:
            low, at = g, str(r["period_start_utc"])
    print(f"  {name:24s} min {low:6.1f}%  ({at})")
