# Engine notes — methodology decisions and known limitations

The points below are where the published numbers depend on a choice or an external input.
Each is documented so the figures can be checked and reproduced. Resolve each before the
figure it affects goes live.

## 1. Solar is not in FUELINST *(resolved 2026-06-25)*

FUELINST reports transmission-metered generation. Embedded solar is netted off national demand
and does not appear in it. At a summer midday this materially affects renewables' and gas/
imports' shares. Any figure that involves solar — the capacity-share, the verdict pair, the
"solar now" card — uses a real solar series, never a modelled one.

**Decision.** Embedded solar **and** embedded wind are taken from the **NESO embedded
forecast** (CKAN resource `db6c038f-98af-4570-ab60-24d71ebd0ae5` on `api.neso.energy`). This is
the figure NESO itself nets off national demand, so it is internally consistent with the demand
denominator (below). NESO sends `Access-Control-Allow-Origin: *`, so the live browser layer can
fetch it directly, exactly as it does Elexon.

**Cross-check.** The published NESO solar figure is asserted at build time against
**Sheffield Solar PV_Live** (`api.solar.sheffield.ac.uk`, national GSP id 0) — the independent
GB outturn series — and the build fails if they disagree by more than 10%. PV_Live sends no CORS
header, so it can only ever be the server-side auditor, never the live figure. This way the one
headline-moving estimate is policed by an independent source without being load-bearing in the
browser.

Embedded wind is added to transmission wind to give the published wind total.

## 2. Nameplate (installed-capacity) denominators *(resolved 2026-06-25)*

The capacity-share, the wind stripe and the low-output counter divide by installed wind (and
solar) capacity. `data/nameplate.json` is now sourced from **DUKES 2025, Table 6.2** (the
capacity table — *not* 6.1, which is the commodity balance), 2024 column, fetched from the
official `DUKES_6.2.xlsx` and verified cell-by-cell:

| Metric | GW (UK, end-2024) |
| --- | --- |
| Wind onshore | 16.166 |
| Wind offshore (incl. 0.08 floating) | 15.916 |
| **Wind total** | **32.082** |
| Solar PV | 18.28 |

These are **full installed (nameplate)** capacities — *not* DUKES's separate de-rated figures
(wind ×0.43, solar ×0.17); de-rated values must never be used as a capacity-factor denominator.
The shipped figures self-reconcile (`engine/models.py:Nameplate`) and are pinned by
`tests/test_nameplate.py`.

**Basis caveat (must stay visible).** These are **UK-wide** (DUKES has no GB-only split; the
small NI capacity makes the denominator a touch large, so a published share is mildly
conservative, never inflated). The figures are **end-2024**; per the decision, REPD/Energy
Trends refresh comes later (end-2025 provisional ET 6.1: wind 33.09 GW, solar 21.74 GW).

**Solar basis — do not mix.** This solar figure (18.28 GW, UK, end-2024, hybrid register basis)
is *not* the same basis as the live layer's solar capacity, which it inherits from NESO/PV_Live
(~22–23 GW, **GB**, **DC/MWp**, **2026** vintage). The ~4–5 GW gap is vintage + DC vs hybrid +
coverage + GB-vs-UK, none of them an error. A *static* end-2024 "% of capacity" uses this DUKES
denominator; any *live* solar capacity-share must use the live GB-DC denominator instead. The
methodology page must state which denominator powers which figure.

## 3. Verdict denominator definition *(resolved 2026-06-25)*

Every published share divides by **national demand**, reconstructed from the supply side:

```
national_demand =  positive transmission generation        (FUELINST, excl. INT* and PS)
                +  net interconnector imports               (sum of all INT*, exports net off)
                +  embedded solar                           (NESO)
                +  embedded wind                            (NESO)
```

Pumped-storage *pumping* (negative `PS`) is demand, not supply, so it is excluded from the sum;
interconnector exports (negative `INT*` legs) net off inside net imports. Shares therefore sum
to 100% by construction. Numerators: wind = transmission `WIND` + embedded wind; solar =
embedded solar; gas = `CCGT` + `OCGT`; imports = net `INT*`; nuclear; biomass; other = the
remaining positive transmission fuels (`NPSHYD`, `OTHER`, `COAL`, `OIL`).

**Reconciliation guard.** The build compares this denominator against an independent figure —
Elexon's Initial Transmission System Demand Outturn (ITSDO) plus the same embedded estimate —
and fails if they disagree by more than 12%. The tolerance is deliberately loose: the supply
reconstruction runs ~1.5–2 GW above ITSDO (transmission losses, plus FUELINST's 5-minute
snapshot against ITSDO's 30-minute settlement average), and that offset is roughly
demand-independent, so as a fraction it grows when demand is low. The guard's job is to catch a
gross feed failure (a zeroed, doubled or wrong-unit series), not to certify accuracy — the
accuracy of the one estimate that moves the headline (solar) is defended separately by the
PV_Live cross-check in #1. The actual residual is recorded each run (`reconcile_residual_pct`)
rather than hidden.

## 4. Interconnectors

Net flows are summed across all `INT*` fuel types; v1 reports the net figure. Per-country
attribution is a later addition.

## 5. Live layer — browser/engine parity *(Stage 3, 2026-06-25)*

The verdict is computed in two places: the build (`engine/grid_engine.py`) and the browser
(`site/verdict.js`). They must never contradict each other. The contract is pinned by golden
vectors (`tests/fixtures/verdict_vectors.json`, regenerated only by
`uv run python -m engine.build_site emit-vectors`) plus a 2,000-case fuzz comparison, run on
both sides under one `uv run pytest` and in CI (`.github/workflows/parity.yml`). Two subtleties
that bite a naive port and are now locked by tests: Python `round(x, 1)` is **round-half-to-even**
(`12.25 → 12.2`, not `12.3` — `site/verdict.js:roundHalfEven1` mirrors it), and `INT*` matching is
**case-insensitive** on both sides.

The browser **cannot** run the PV_Live cross-check (PV_Live sends no CORS header), so that guard
stays build-only; the browser instead mirrors the snapshot-completeness and embedded-freshness
guards and runs the ITSDO reconcile as a live tripwire (a breach forces fallback).

**Clock honesty.** Elexon does not expose its `Date` header via CORS, so there is no readable
server clock in the browser. The live layer therefore anchors everything on the FUELINST
**snapshot timestamp** (server-stamped), fetched with a future-buffered window so the true latest
snapshot is always captured regardless of the device clock — making the verdict numbers
clock-independent. The displayed "N min ago" is a device-clock convenience; when it disagrees
with the snapshot (data apparently from the future, or implausibly old for a just-fetched live
reading) the label degrades to "age uncertain", and the absolute UTC snapshot time is always
shown. Fallback (`site/data/latest.json`) is honest about being a last-good reading; a build
older than 12 h renders UNAVAILABLE with no numbers rather than a stale headline.

### Deferred low-severity findings (Stage 3 adversarial audit, 2026-06-25)

The audit's two ship-blockers (stale-snapshot-as-live; corrupt-fallback freeze) and all medium
findings are fixed and test-covered. Three LOW items were deliberately deferred — none can show a
wrong number as truth (worst case: an over-cautious label or a conservative UNAVAILABLE). Each is
anchored by a `TODO(stage3-audit Lx)` comment at the relevant line (`grep -rn "stage3-audit"`):

- **L2 — signed-zero parity** (`site/verdict.js:roundHalfEven1`). JS returns `+0` where Python
  yields `-0.0`. Only reachable with negative national demand, which the guards block three ways.
- **L5 — over-cautious skew label** (`site/live.js:relAge`). A device clock 3–20 min behind tags a
  fresh reading "age uncertain". Asymmetric tolerance (3 min future vs 20 min past); cosmetic.
- **L6 — forward-skew suppresses fresh fallback** (`site/live.js:buildFallback`). A device clock
  12 h+ fast makes a genuinely-fresh fallback read as >12 h old → UNAVAILABLE. Extreme and
  conservative (shows nothing, never a wrong number).
