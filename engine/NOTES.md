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

**Reconciliation guard — against INDO, not ITSDO.** The build compares this denominator against
an independent figure — Elexon's Initial (National) Demand Outturn, **INDO**, plus the same
embedded estimate — and fails if they disagree by more than 12%. INDO is the right reference
because the supply reconstruction above computes *national* demand. **ITSDO (transmission system
demand) is the wrong reference and was the source of a false alarm:** by Elexon's definition
`ITSDO = INDO + interconnector exports + station load + pump-storage pumping`, so on an export
night ITSDO runs above national demand by the export volume, and the guard tripped on perfectly
good data. Verified live 2026-06-25 23:30Z (GB exporting 4,553 MW): supply reconstruction 27,638 MW
vs ITSDO+embedded 34,605 (20.1% — false trip) but vs INDO+embedded 28,156 (1.8% — clean);
`ITSDO − INDO = 6,449` matched export + station + PS exactly. Pinned by
`tests/test_engine.py::test_reconcile_against_indo_survives_heavy_export` and a node case in
`site/live.test.mjs`. The tolerance is deliberately loose: the supply reconstruction runs ~0.5–1 GW
above INDO (transmission losses, plus FUELINST's 5-minute snapshot against the 30-minute settlement
average), and that offset is roughly demand-independent, so as a fraction it grows when demand is
low. The guard's job is to catch a gross feed failure (a zeroed, doubled or wrong-unit series), not
to certify accuracy — the accuracy of the one estimate that moves the headline (solar) is defended
separately by the PV_Live cross-check in #1. The actual residual is recorded each run
(`reconcile_residual_pct`) rather than hidden.

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
guards and runs the INDO reconcile as a live tripwire (a breach forces fallback).

**Clock honesty.** Elexon does not expose its `Date` header via CORS, so there is no readable
server clock in the browser. The live layer therefore anchors everything on the FUELINST
**snapshot timestamp** (server-stamped), fetched with a future-buffered window so the true latest
snapshot is always captured regardless of the device clock — making the verdict numbers
clock-independent. The displayed "N min ago" is a device-clock convenience; when it disagrees
with the snapshot (data apparently from the future, or implausibly old for a just-fetched live
reading) the label degrades to "age uncertain", and the absolute UTC snapshot time is always
shown. Fallback (`site/data/latest.json`) is honest about being a last-good reading; a build
older than 12 h renders UNAVAILABLE with no numbers rather than a stale headline.

**Fallback staleness ladder (the frozen-solar guard).** The fallback's *numbers* are gated on the
**snapshot** age, not the build age, because a stale headline that *looks* current is worse than
none: a midday 12 GW-solar reading rendered at 11 pm is a wrong number, not an old one. The ladder:
under `STALE_MIN` (60 min) the numbers show clean; from 60 min to `FALLBACK_NUMBERS_MAX_MIN`
(**120 min**, tunable) they still show but carry the "may be out of date" banner; **beyond
`FALLBACK_NUMBERS_MAX_MIN` the fallback goes number-free** ("Last good reading was N ago — too old
to show as current"), well before the 12 h build-age UNAVAILABLE cutoff. Pinned by
`site/live.test.mjs` ("fallback snapshot older than the 'now' window goes number-free"). The 120 min
value is a presentation knob, set so a solar-bearing headline can't drift across a large fraction of
a day; raise it only if a less twitchy fallback is wanted at the cost of showing older figures.

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

## 6. History pipeline — store, edge, gate *(Stage 4, 2026-06-25)*

`engine/history.py` pulls settled half-hourly **FUELHH** (generation by fuel type + signed
interconnector flows) and the **demand outturn** (INDO/ITSDO) from Elexon, into an append-only,
git-diffable CSV store under `data/history/` — the source of truth for every historical figure.
No modelled numbers: each value is a settled Elexon figure keyed to a settlement date and period.

**Clean-data edge — 2016-01-01, not 2009.** FUELHH on the modern Elexon Insights API returns an
empty array before **2016-01-01** (verified live, both directions). National demand
(`/demand/outturn`) starts later still, **2016-03-01**; the ~2-month gap carries fuel mix with
blank INDO/ITSDO. Pre-2016 exists only in NESO's *derived* historic-generation-mix CSV (modelled
embedded estimates) and is excluded from v1 to keep the store 100% settled-Elexon. Endpoints use
the `/stream` variants (`FUELHH/stream`, `demand/outturn/stream`) — the non-stream routes 400 on
any range over 7 days.

**Store format — wide CSV, one row per settlement half-hour** (`fuelhh_YYYY.csv`, one file per
settlement-date year, identical header). Columns: `settlement_date, settlement_period,
period_start_utc`, one MW column per fuel/interconnector code, then `INDO, ITSDO`. A **blank cell**
means the series did not exist that period (an interconnector before commissioning, BIOMASS before
2017, demand before 2016-03-01); **0** means present and zero — the distinction is preserved. Wide
(≈158k rows, ~20 MB) was chosen over long (≈2.7M rows, ~240 MB) for clone/diff weight. The fuel
roster is a fixed superset (10 fuels + 10 interconnectors as of 2026-06); a `fuelType` outside it
**fails the pivot loudly** so a feed change is noticed, never silently dropped. Parquet is deferred
(CSV is canonical; a columnar cache can be regenerated later if a stage proves slow).

**Validation gate — completeness by COUNT, not contiguity.** A UK settlement day holds 48
half-hours, except **46** on the spring clock-forward Sunday and **50** on the autumn clock-back
Sunday; `expected_periods()` derives this from `Europe/London` tzdata, not a hardcoded calendar.
The gate asserts each day's row count equals that DST-aware expectation and that no
`(date, period)` key repeats. It deliberately does **not** require periods to be a contiguous
`1..N` set: early Elexon days are occasionally numbered non-contiguously (e.g. 2016-03-27's 46
half-hours run 1..45, 48) yet are complete — count is the honest signal, numbering is not. The
wind spot-check (`daily_mwh`, Σ MW×0.5) reproduces Elexon's own daily total exactly.

**Known early-data holes — a frozen manifest.** Across the 2016-01-01→edge backfill (183,418
rows), **77 settlement days are genuinely short — 132 missing half-hours (0.072%)**, all Elexon
non-publications, not fetch errors (e.g. 2016-10-30 has 49 rows where 50 are due). They cluster in
2016–2022; 2024–2026 are pristine (zero gaps). We do not fabricate the missing half-hours. Instead
`data/history/known_gaps.csv` is a **frozen record** of each short day `(date, actual, expected,
shortfall, note)`. The gate (`validate`) **passes** when every incomplete day matches the manifest
and there are no duplicates, and **fails** on any *new or changed* gap — so a future append that
silently drops a half-hour is caught as a regression. The manifest is regenerated only by a
deliberate, reviewed re-baseline, never automatically (that would launder a real regression).

## 7. Historical nameplate — annual series, annual-step *(Stage 4, 2026-06-25)*

Historical capacity factors need installed capacity *as of each year*, not the single end-2024
anchor in `data/nameplate.json`. `data/nameplate_series.json` carries the **DUKES 2025 Table 6.2**
annual series 2009–2024 (onshore wind, offshore wind incl. floating, solar PV), independently
re-downloaded and reconciled — its 2024 row is byte-identical to the live anchor.

**Interpolation rule — annual-step.** Each year's published year-end value is held until the next.
Every denominator is therefore a verbatim, citable DUKES figure. **Linear interpolation is
rejected**: its in-between values appear in no published table and would breach the v1 "no modelled
figures" rule (`NameplateSeries` enforces this — `interpolation` must be `annual-step`). The honest
cost of annual-step is a small, monotonic timing bias (a year-end figure held across a year of
rising capacity makes late-year capacity-factor denominators run slightly low); it is disclosed in
the file's `basis_note`, not modelled away. A monthly capacity series, or labelled interpolation,
is a later-version question once modelled figures are explicitly permitted.

## 8. Derived series — CF basis, share basis, the cross-year artifact *(Stage 5, 2026-06-25)*

`engine/derived.py` computes the daily cards from the settled store + the annual nameplate
series: the wind stripe, the failure counters (<10%, <5%), the records, and the year-to-date
shares → `site/data/{stripe,counters,records,ytd_shares}.json`. No modelled figures; every value
is a settled Elexon figure over a published DUKES capacity. Each file carries its `basis` string
inline so a card cannot be lifted out of context and read on the wrong basis.

**Wind capacity factor — a conservative *lower bound* (Richard-confirmed).** FUELHH `WIND` is
transmission-metered only; it excludes the embedded (distribution-connected) wind NESO estimates
separately (the same series the live layer adds back). The denominator is **DUKES total UK wind**
nameplate (annual-step). A transmission-only numerator over a total-installed denominator makes the
daily CF a **lower bound** — the true output/total-installed ratio is higher because embedded wind
output is missing from the top. The bias direction (understatement) is fixed and disclosed; the CF
is never presented as the literal load factor. The alternative (sourcing a transmission-only annual
capacity series to match the numerator) was considered and deferred; this basis ships with the bias
made loud instead.

**Mean-power definition.** CF = mean(`WIND` MW over the day's *present* periods) / nameplate MW.
For a normal 48-period day this equals daily energy ÷ (capacity × 24 h); on a 46/50-period
clock-change day or a known-gap short day it **normalises** rather than penalising the day for
fewer half-hours — so a settlement hole never manufactures a phantom low-wind day. The stripe's
mean line and `per_year_mean_cf` are the equal-weight mean of the daily CFs (one weight per
column), matching what the eye reads off the stripe.

**The cross-year artifact — must stay disclosed.** The lower-bound understatement is **not
uniform across years**. In 2016 a large share of wind was embedded onshore (outside FUELHH), so
transmission-wind ÷ total-nameplate is heavily depressed (mean CF 0.15; 132 days < 10%). As
offshore — all transmission-metered — grew, the transmission share of total capacity rose and the
apparent CF climbs (2025: 0.244; 47 days < 10%). **This upward drift is largely a denominator-mix
artifact, not a real improvement in wind performance**, and the all-time records skew to the most
biased year (longest sub-10% run, 17 days, falls in 2016). The honest reading: the stripe shows
**within-year** daily variability ("the wind rarely blows") truthfully; **cross-year** comparison
of the level is confounded and must be annotated, never sold as a trend.

**YTD shares — transmission-system basis, *not* the national verdict (Richard-confirmed).** The
store is settled FUELHH only, with no embedded solar/wind, so a national-demand share (as the live
verdict uses) is impossible from settled data. `ytd_shares.json` is therefore a **transmission-
system mix**: settled generation + net interconnector flow over transmission supply, with
pumped-storage round-trip and embedded both excluded — internally consistent and 100%-summing, but
explicitly **not comparable** to the live national-demand verdict (the file says so, and flags that
embedded solar cannot appear in a settled-data share). Pinned by `tests/test_derived.py`.

**Validation gate.** Two layers: `tests/test_derived.py` pins the logic on synthetic inputs;
`tests/test_derived_gate.py` recomputes CF, counters, records and shares straight from the
committed CSVs via a separate code path (no `engine.derived` import) and asserts the engine agrees
on **every day** — the half that catches a regression only the real data's quirks (DST, the 77
known-gap days, blanks, leap years) would expose.

**Open for a later version.**
- *Transmission-matched denominator (the real fix for the lower bound).* Sourcing an annual
  transmission-connected wind capacity series (DUKES total − embedded, per year) to match the
  transmission-only numerator would remove both the understatement and the cross-year artifact.
  Considered and deferred here; the lower bound ships with the bias made loud instead.
- *Records grain.* `records.json` ships **all-time** extremes, which (per the artifact above) skew
  to the earliest, most-understated years. Whether Stage 6 surfaces per-year or rolling-window
  records instead — to avoid presenting a 2016-clustered figure as the headline — is an open
  presentation decision, not yet made.

## 9. Share cards *(Stage 8, 2026-06-26)*

`engine/sharecards.py` generates a set of 1200 × 630 OG PNG cards plus per-card unfurl stubs
(`site/s/<slug>.html`) from the same `site/data/*.json` the dashboard reads — `latest.json`,
`nameplate.json`, `counters.json`, `records.json` and `stripe.json`. Because the cards read the
published data files rather than recomputing from source, a card figure and the dashboard figure for
the same datum use structurally identical values: the same JSON field, the same format string.
**`tests/test_sharecards_gate.py`** asserts this by reloading each source JSON and checking every
card's formatted figure against a value derived independently from it — any drift is a test failure,
not a silent discrepancy.

**Cards in the set.** Three *live* cards (rebuilt each time site data refreshes): the firm-power
gauge (`firm-now`), the capacity-trap share (`capacity-trap`), and the gas-vs-wind comparison
(`gas-vs-wind`). Four *settled* cards (rebuilt whenever the history store appends): the wind stripe
thumbnail (`wind-stripe`), the days-below-10% counter (`days-below-10`), the all-time worst-day
record (`lowest-day`), and the longest calm-spell record (`longest-calm`). One *warning* card
(`warning`): see below.

**Live cards — evergreen and timestamped.** Each live card carries the `snapshot` timestamp from
`latest.json` (e.g. "as of 23 Jun 15:35 UTC"), so a shared card can be read in context. The
`gas-vs-wind` headline is adaptive: it states whichever source actually leads at build time, never
a false claim in the other direction.

**Warning card — the Stage 7 scarcity ladder.** `engine/warnings.py` fetches the active-only
Elexon SYSWARN feed at build time and classifies any notice against the three-tier ladder: NISM
(Notice of Insufficient System Margin, highest severity), EMN (Electricity Margin Notice), CMN
(Capacity Market Notice). The card renders either "Margin notice — a [type] is in force" (alarm
theme) or "All clear — no grid margin warning is in force" (ink theme). `engine/warnings.py` is a
build-time mirror of `site/warnings.js`; both implement the same ladder. A formal parity lock
(like the verdict gate) is deliberate later hardening — deferred because the warning card's text
comes from the live feed, not a numeric formula.

**Content-hash cache bust.** Each PNG is SHA-256-hashed; the first 10 hex digits become a `?v=`
query token on every image URL in `cards.json`, the unfurl stubs, and the homepage `og:image`.
Social scrapers (Twitter/X, LinkedIn, iMessage, Slack) cache OG images aggressively. A rebuild
that changes a card's figures also changes its hash, so the new `?v=` token forces a re-scrape.
The homepage hero (`og:image` pointing at `firm-now.png`) is stamped in place by `stamp_index_og()`.

**No modelled figures.** Every card value traces to a settled or live Elexon / NESO / DUKES figure
already published on the dashboard. The same lower-bound and cross-year caveats shown on the
dashboard are carried on each affected card (`caveat` field, rendered as a footer note). No figure
is introduced or transformed beyond what already exists in `site/data/*.json`.

**Deploy cadence (Stage 10 dependency).** Live cards must be rebuilt every time
`site/data/latest.json` refreshes (≈5 min) to stay current; settled cards need a daily rebuild
after the FUELHH store appends. Wiring this to CI/cron lands with Stage 10. Until then,
`uv run python -m engine.sharecards build` is run manually: it renders PNGs via Playwright
Chromium, writes `site/share/cards.json` and `site/s/*.html`, and reports the card count. The
generated artefacts (`site/share/*.png`, `site/s/*.html`) are committed so the static host serves
them directly without a build step.

**WARNING — the warning card MUST NOT be served publicly without the Stage 10 cadence wired.**
It asserts a binary in-force/clear state at a single point in time; without automatic rebuilds, a
withdrawn notice would keep showing "in force" — a stale false alarm, the exact failure the
project's honesty bargain forbids. All other cards degrade gracefully when stale (a timestamp
shows the age); the warning card cannot — it either lies or tells the truth.

## 10. Provenance + sanity guards *(Stage 9, 2026-06-26)*

`engine/guards.py` centralises the loud-failure contract: a published figure either passes
silently or raises `GuardError` with a message that names the figure and the breach. The build
steps call these *before writing any output*, so corrupt or implausible data **fails the build and
writes nothing** rather than being published. The checks are small, named, message-bearing
predicates (not bare `assert`s, so `python -O` cannot strip them).

**Where they run.**
- *Live verdict* (`engine.grid_engine.sanity_check`, pre-dating this module): demand > 0, share
  ranges, the PV_Live solar cross-check (±10%) and the INDO reconcile (±12%). Unchanged.
- *Derived figures* (`engine.derived.guard_outputs`, new): before `derived.build` writes
  `site/data/*.json` it asserts the stripe's daily CF range and date order/uniqueness, the failure
  counters' nesting (`below_5 ≤ below_10 ≤ observed`), each year's transmission shares summing to
  100% (±0.5pp), the records' internal order, and the nameplate denominators' sanity
  (`check_nameplate_sane`). A breach prints a `GuardError` and returns non-zero, leaving the
  previous good files byte-identical.
- *Share cards* (`engine.sharecards.guard_card_inputs`, new): the cards are screenshotted into
  shareable images, so a wrong figure becomes a wrong picture. The verdict snapshot, firm/wind/
  solar/gas figures, the capacity denominator, the counters, the record CF and the stripe mean are
  range-checked before any card is built; `sharecards.build` catches a load/guard failure and
  returns 1 with a clear message. The source-trace gate (`tests/test_sharecards_gate.py`) still
  recomputes every card figure independently.

**The one value that looks wrong but is correct.** A NEGATIVE net-import share on an export year
(2022) is allowed by construction: `check_shares_sum_100` validates the *sum*, never the *sign* of
an individual share (see §8). The Stage 9 adversarial review flagged a guard that might reject it;
verification confirmed the guard correctly allows it.

**Capacity-factor ceiling.** A daily wind CF is a conservative lower bound (transmission output ÷
total installed), so it cannot exceed 1.0 — output never exceeds installed capacity. `check_cf_range`
rejects anything outside `[0, 1]` (a tiny epsilon absorbs float rounding); above it means a
wrong-unit or doubled feed, or a collapsed nameplate denominator.

**Provenance audit.** Every public figure carries a visible source line and a timestamp. The live
verdict line shows the full snapshot instant (not a bare HH:MM); the settled share cards thread the
source JSON's `generated_utc` (a "rebuilt DD Mon YYYY" stamp); the warning banner and warning card
carry their source (Elexon SYSWARN) and issue time. `site/methodology.html` documents every figure,
formula, tolerance and the honesty bargain, and carries a "last reviewed" date.

**Validation gate.** `tests/test_guards.py` pins each predicate; `tests/test_derived_guards.py` and
`tests/test_sharecards_guards.py` inject bad data (a CF above 1, shares not summing to 100, a broken
counter, an insane nameplate, a missing source file, a corrupt snapshot, a null record) and assert
the build fails with a clear message and writes nothing.
