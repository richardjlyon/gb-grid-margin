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

## 9. Share cards *(Stage 8, 2026-06-26; redesigned v0.9, 2026-06-28)*

**v0.9 update (2026-06-28):** the 8-card set was replaced by a minimal 3-artefact set — an evergreen
**hero** OG card (the site `og:image`; carries no perishable number, fixed illustrative gauge), a live
**reliability balance** card whose background is a green/amber/red traffic light from the live firm share
(`firm_band`, cuts parity-locked to `site/render.js` RELIABILITY_RAMP 0.40/0.65), and a **recent-lull**
card (most recent ≥3-day wind lull). The live card's gauge needle and headline derive from the same
`firm_pct` (tested invariant); its stamp is a dated "live snapshot · …", never "right now". Each card's
content hash is a cache-bust on the shared `/s/<slug>?v=<hash>` URL + stub `og:url` + `og:image`, so a
re-rendered card forces a fresh social unfurl. The daily refresh cron now rebuilds the cards (cached
Chromium, non-fatal) after the live-snapshot refresh and fires a Vercel deploy hook. The old per-source
detail below is retained for history.

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

## 11. Historical embedded solar/wind store *(Reliability Stripe, Stage A, 2026-06-26)*

The reliability stripe needs a *national-demand* reliable-vs-unreliable share over time — which means
the settled history must carry the embedded (distribution-connected) solar and wind that the live
gauge already includes but the transmission-only FUELHH store (§6) does not. `engine/embedded_history.py`
backfills it from **NESO's published Historic Demand Data** into `data/history/embedded_YYYY.csv`,
one row per settlement half-hour, joining 1:1 to the FUELHH store on `(settlement_date,
settlement_period)`. The store mechanics are the shared `engine/widestore.py` (extracted from §6's
pipeline so both stores share one tested append-only/idempotent implementation).

- **Source + columns.** NESO Historic Demand Data (CKAN), one resource per year; columns
  `EMBEDDED_WIND_GENERATION`, `EMBEDDED_SOLAR_GENERATION`, `EMBEDDED_WIND_CAPACITY`,
  `EMBEDDED_SOLAR_CAPACITY`, half-hourly. NESO Open Data Licence.
- **Not metered — disclosed.** Embedded generation is not transmission-metered; these are NESO's
  **modelled outturn estimates**, not settled meter readings like FUELHH. This is a genuine basis
  difference and must be labelled wherever the figure surfaces (the same honesty principle as the
  §8 lower-bound and cross-year caveats). It is NESO's model, not ours — so it still traces to a
  named published source, consistent with the no-modelled-figures-of-our-own rule.
- **Forecast vs outturn seam.** The *live* gauge reads NESO's embedded *forecast*
  (`EMBEDDED_*_FORECAST`, `grid_engine.py`); this store reads NESO's embedded *outturn estimate*
  (`EMBEDDED_*_GENERATION`). Same methodology owner, sibling products — the historical series is the
  corrected/settled estimate, the live tick is the forward forecast. A small step at the join is
  expected and disclosed, not a bug.
- **GB scope confirmed (the named risk).** The spec flagged that the embedded columns might be
  England-&-Wales-only (~15–18% low) rather than GB. Reconciled against PV_Live GB national solar on
  summer-solstice middays: 2018-06-21 embedded 73,696 MWh vs PV_Live 70,404 MWh (4.7%), 2024-06-21
  83,830 vs 84,108 (0.3%) — both well inside ±10%, far from an E&W shortfall. The columns are GB-wide.
  PV_Live (`solar_crosscheck`) is the standing independent solar guard, the historical twin of the
  live ±10% NESO-vs-PV_Live check.
- **Date-format quirk (handled at the boundary).** NESO's `SETTLEMENT_DATE` format is *not* consistent
  across years: ISO `YYYY-MM-DD` (2016–18, 2024–26), `DD-MMM-YYYY` (2019–22, e.g. `01-JAN-2019`),
  and `DD-Mon-YY` (2023, e.g. `01-Jan-23`). `EmbeddedHistRow` normalises all of these to ISO at the
  feed boundary, so every downstream consumer (the join key, `period_start_utc`, `year_path`) sees
  ISO only; an unrecognised format raises loudly. The embedded *column names* are stable across years.
- **Lag + ragged edge.** NESO publishes embedded ~21 days in arrears and fills recent days raggedly,
  so the most recent days are partial (e.g. 2026-05-29 had 45/48 periods, 05-30 had 25/48). These are
  transient (they fill in), not permanent non-publications, so they are **not** recorded in a
  known-gaps manifest the way §6's 77 Elexon holes are; instead the store is trimmed to the last
  fully-complete day. **Committed edge: 2016-01-01 → 2026-05-28, 182,446 rows, validate ok
  (0 unexplained, 0 dupes).** The daily-`append` cadence (Stage 10) extends the edge as NESO completes
  each day: `trim_ragged_edge` holds it at the last fully-complete day so a partial day never enters the
  store (the gap gate would rightly reject it), and `append_rows(on_revision="update")` absorbs NESO's
  retrospective revisions in the re-fetched overlap window — rewriting the cell, with git as the audit
  trail. The one-time backfill stays strict (`on_revision="raise"`), where a revision is a real conflict
  to surface. Consequence for freshness: the embedded-derived carpets sit a few days further back than
  the ~21-day NESO lag whenever the most recent days are still partial — complete-and-correct in
  preference to fresh-but-partial.
- **Validation gate.** `validate` reuses §6's DST-aware period-count + duplicate checks
  (`history.validate_range`). `crosscheck` runs the PV_Live ±10% solar guard on a sample. Pure
  transforms are unit-tested in `tests/test_embedded_history.py`; the network fetch layer is thin and
  untested, mirroring §6.

## 12. Reliability series — Stage B *(2026-06-26)*

`engine/reliability.py` joins the FUELHH store (§6) to the embedded store (§11) on
`(settlement_date, settlement_period)` and emits a half-hourly **national reliable (firm) share
of demand** series via `engine.derived.build` → `site/data/reliability_year.json` (rolling 12
months); `reliability_all.json` (full history) is **no longer emitted** — the all-time toggle was
removed when the carpet block (§15) replaced the dashboard 1-D stripe. `reliability_year.json` is
retained solely as the share-card source (§13). The formula is `reliable_share` in
`engine/reliability.py`, which reuses `compute_verdict` (the gauge's parity-locked formula), so
the historical series is identical, by construction, to the live dial.

**Reliable share can exceed 100% on net-export half-hours.** On half-hours when GB is a net
exporter, `notfirm = wind + solar + net_imports < 0`, so `national_demand = firm + notfirm <
firm`, and `firm / demand > 1.0`. This is faithful to the live dial and is the same accepted
property as the Stage 9 `check_shares_sum_100` rule that allows a negative net-import share on
an export year (§10). The real emitted `reliability_year.json` has ≈5 such half-hours (max
≈1.024). Do NOT clamp these — the contract is documented in the `reliable_share` docstring and
disclosed in the JSON `caveats` field. (The **carpet** in §15 uses the inverse metric
`1 − reliable_share` and **does** clamp to `[0, 1]`; its contract is documented separately.)

**All-time head-row timestamp quirk.** The 2016-01-01 SP48 row carries a `period_start_utc` of
`2015-12-31T23:30Z` in the FUELHH store — a pre-existing Stage 4 boundary quirk (settlement
period 48 of 2016-01-01 starts at 23:30 on the calendar-previous UTC day). It packs
contiguously at the grid head and the rolling-year file is unaffected.

## 13. Reliability stripe — Stage C *(2026-06-26)*

**⚠ Dashboard 1-D stripe superseded by the carpet block (§15).** The rolling-year stripe and the
all-time toggle described below were removed from the live dashboard when the Entry-01 carpet block
(§15) shipped. `reliability_year.json` is no longer loaded at startup by the dashboard and
`reliability_all.json` is no longer fetched on toggle — those consumers were deleted. Stage C now
covers only the **share-card** path: `reliability_year.json` (flat, rolling 12 months) feeds
`engine/sharecards.py` only. The colour ramp, JS↔Python parity lock, and gauge-flip stamp below
remain accurate for the share card.

Stage C adds the stripe to the live dashboard (Entry 01, under the gauge) and a Python share-card
sibling (`engine/sharecards.py` `reliability-stripe` card).

**Colour ramp.** Single red ink, inverted: pale (paper) = firm, full red = unreliable. Firm-share
domain `[lo=0.40, hi=0.65]` (`RELIABILITY_RAMP` in `render.js`). The gauge's 50% arming threshold
is the midpoint of this range: the stripe and the dial share one threshold and cannot give
contradictory readings. The scale saturates — i.e. reaches maximum red — at 40% firm; anything
below that maps to the same full red. Disclosed in the key note and in `methodology.html`.

**JS↔Python colour parity lock.** `reliableShareToColor(s)` in `render.js` and
`reliable_share_to_color(s)` in `engine/sharecards.py` are parity-locked:
`tests/test_reliability_card_parity.py` `test_python_ramp_matches_js_ramp` runs the Python function
against a set of sample shares spanning 0–1.3, including the half-integer boundary cases, and
asserts exact RGB match with the JS formula evaluated in Node.

**Lazy all-time toggle (removed).** The dashboard no longer loads `reliability_year.json` at
startup and `reliability_all.json` is not fetched on toggle — both consumers were removed when the
carpet block (§15) replaced the 1-D stripe. `reliability_year.json` is still read by
`engine/sharecards.py` (the `reliability-stripe` card). `reliability_all.json` is no longer
emitted.

**Gauge flip (lead unreliable, instrument-not-alarm).** The stamp pair in Entry 01 leads with the
unreliable (weather & imports) share in the larger `.stamp-val.lead` slot and places the firm share
in the smaller `.stamp-val.muted` slot. The distinction is size + DOM order, not colour only — the
`lead` class uses `clamp(2.2rem, 5.75vw, 3.2rem)`, the `muted` class is default size. The gauge arc
art and source-mix convention (green = reliable, left-to-right) are unchanged; only stamp emphasis
flips. This is an instrument reading, not an alarm — the needle colour is governed solely by the 50%
arming threshold (`firmStatus` in `render.js`), not by the stamp order.

## 14. Capacity-factor carpets *(Entry 02, 2026-06-27)*

`engine/capacity.py` computes two per-source capacity-factor day-grids — one for wind, one for
solar — over the rolling last 365 days of settled half-hourly data. The output is
`site/data/capacity_carpets.json`, emitted by `engine.derived.build` (inside the
`if embedded_rows:` block, alongside the reliability series from §12). The load-duration curve
this supersedes was removed as illegible to a general audience: ranking half-hours by CF is not a
natural axis for most readers, whereas a settlement-period (local time-of-day) grid is immediately
interpretable.

**Per-source basis formulas.**

```
Wind CF (per SP) = (transmission WIND [Elexon FUELHH WIND column, settled]
                    + embedded wind [NESO outturn estimate, §11])
                   / DUKES total UK wind nameplate (annual-step, MW)

Solar CF (per SP) = embedded solar [NESO outturn estimate, §11]
                    / NESO embedded-solar capacity (contemporaneous, GB, DC/MWp)
```

The wind formula includes embedded wind in the numerator over the full DUKES installed total,
making it a **true load factor** — not the transmission-only lower bound the wind stripe (§8)
carries. The cross-year artifact documented in §8 (apparent CF rising as the offshore transmission
share grew) does not apply here; the numerator and denominator share the same total-capacity basis
for each half-hour's settlement year. Missing or blank FUELHH `WIND` values coerce to 0.

The solar formula uses **NESO embedded-solar capacity as the denominator, not DUKES**. Both
the numerator (embedded solar outturn, `EMBEDDED_SOLAR_GENERATION`) and the denominator
(`EMBEDDED_SOLAR_CAPACITY`) are from the same NESO embedded-history series (§11), on the same
scope (GB) and basis (DC/MWp, contemporaneous). A DUKES solar capacity figure would be
UK-wide, AC-equivalent and end-2024 vintage — a 4–5 GW mismatch that would artificially
depress the solar CF (see §2 for the full accounting of the scope and basis differences). Night
cells store `0.0` (genuine zero output, not gaps); `None` only when the capacity field is absent
or zero.

**Join and time-of-day axis.** `build_carpet_days` joins the settled FUELHH store (§6) to the
embedded store (§11) on `(settlement_date, settlement_period)`. A half-hour present in both stores
fills array slot `SP − 1` (0-indexed into the 48-element `cf` array). Settlement periods follow
the local clock (SP1 = 00:00 local, BST/GMT handled for free by the settlement-period convention).
DST 50-period autumn days produce 50 joined periods; **SP49 and SP50 fall outside the 48-column
grid and are dropped** (`if not (1 <= sp <= PERIODS): continue`). 46-period spring-forward days
produce naturally short rows. Days absent from either store are omitted from both carpets, keeping
the two grids aligned on the same day set.

**Rolling 365-day window.** `rolling_days(days, span_days=365)` retains day-grids within 365
calendar days of the latest day (date-filtered, not count-filtered). The window advances with
each `engine.derived build` run as the embedded store edge extends.

**`capacity_carpets.json` shape.** Top-level keys:

| Key | Contents |
| --- | --- |
| `wind.days`, `solar.days` | list of `{"date": "YYYY-MM-DD", "cf": [48 floats-or-nulls]}` |
| `gauge.nameplate_mw` | DUKES wind+solar combined nameplate in MW; calibrates the live gauge |
| `sat` | `{"wind": 1.0, "solar": 1.0}` — cf at/above which a cell maps to the deepest colour (full nameplate) |
| `basis_wind`, `basis_solar` | prose provenance strings (the formulas above, as text) |
| `seam_note` | forecast-vs-outturn disclosure |
| `source_wind`, `source_solar` | citable source strings |
| `generated_utc`, `window`, `range` | build timestamp, `"rolling_365d"`, date bounds |

`gauge.nameplate_mw` = `round(nameplate["wind_plus_solar_gw"] × 1000)` from `derived.py`, where
`nameplate` is the anchor from `data/nameplate.json` (DUKES 6.2 wind + solar, end-2024).

**`guard_payload` gate (§10).** All checks run before `capacity_carpets.json` is written; any
breach raises `GuardError` and writes nothing:

- *Days non-empty*: each source must have at least one day.
- *Window in range*: 360 ≤ `len(days)` ≤ 367 for each source (rolling 365-day window, with
  a ±5-day tolerance for partial store edges and leap-year boundary effects).
- *Days sorted and unique*: the `date` list is sorted ascending with no repeats.
- *Exactly 48 periods per day*: every `cf` array has length `PERIODS = 48`.
- *CF value range*: each value is `None` or in `[0, 2.0]`. The 2.0 ceiling (in contrast to the
  physical limit of 1.0 for metered data) admits NESO's modelled outturn estimates, which are not
  metered and can carry upward revisions, and the annual-step timing bias for wind (mid-year, the
  prior year-end nameplate understates installed capacity). A gross feed error would push values
  far above 2.0 and is caught.
- *Gauge and saturation*: `nameplate_mw > 0`; each `sat` value in `(0, 1]`.

**The forecast-vs-settled seam.** The live gauge reads NESO's embedded *forecast*
(`EMBEDDED_*_FORECAST`, `engine/grid_engine.py`); the carpets read NESO's embedded *outturn
estimate* (`EMBEDDED_*_GENERATION`, the §11 store). These are sibling products from the same
methodology owner — the outturn estimate is the corrected/settled version, the forecast is the
forward tick. A small step at the join is expected and disclosed (see `_SEAM` in
`engine/capacity.py`). The carpets lag live by approximately three weeks (the §11
embedded-store edge).

**Cross-references.** §8 documents the wind stripe's transmission-only lower bound and the
cross-year artifact that does *not* apply to the carpet wind. §11 documents the embedded store,
its GB scope confirmation, the `SETTLEMENT_DATE` normalisation, and the ~21-day lag.

## 15. Entry-01 reliability carpet block *(2026-06-27)*

The dashboard's 1-D reliability stripe (§13) was replaced by an Entry-02-style metric block: a
half-hourly carpet + live dial + box-plot legend, using the **unreliable share** (`1 − firm`) as
the metric. The source is `site/data/reliability_carpet.json`, emitted by `engine.derived.build`
alongside the capacity carpets (§14).

**Metric and clamping.** Each cell = `clamp(1 − reliable_share, 0, 1)`, computed by
`reliability.build_carpet_days`. Net-export half-hours — where `reliable_share > 1` — read 0%
unreliable. This **differs from the flat `reliability_year.json` series (§12)**, where the
reliable share is intentionally NOT clamped so the above-100% property is preserved for the
share-card ramp. The two files have different contracts; do not mix them.

**Carpet shape.** Days × 48, date left→right (oldest→newest), settlement period top→bottom
(SP1 = 00:00 local). Rolling 365-day window (`capacity.rolling_days`). Colour: a continuous
traffic-light ramp — green (0% unreliable, demand fully met) → amber → red (100% unreliable),
OKLab-interpolated (`render.js unreliabilityColor`, shared by the carpet, the dial track and the
legend bar). Green = reliable / red = unreliable matches the verdict gauge above; amber is the
midpoint hue only, NOT a threshold. Drawn with `keepWorstHigh: true`: when a screen column spans
several days the HIGHEST (most-unreliable) cell wins — the inverse of the output carpets'
darkest-wins, because for unreliability the worst case is high, not low. (`sat` stays 1.0 in the
payload but the rampFn path ignores it and maps `cf` directly.)

**`reliability_carpet.json` shape.** `{basis, source, metric, caveats, generated_utc,
window:"rolling_365d", range, sat:1.0, days:[{date, cf:[48]}]}`. `cf` values are floats in
`[0, 1]` (clamped unreliable share) or `null` (missing half-hour).

**Dial.** `renderReliabilityBlock` in `site/app.js` renders a plain 0–100% arc whose TRACK is the
same green→amber→red ramp (`buildGauge`'s `trackRamp` option, drawn as 30 contiguous coloured
segments since an SVG stroke can't carry a gradient along an arc). No nameplate / MW labels — it is
a share, not a capacity factor. The needle reads `unreliableNowPct(firmPct)` =
`max(0, min(100, 100 − firmPct))` (clamped); an ink tick marks the rolling-year mean. The
percentile band arcs are SUPPRESSED on a ramp track (they would muddy the gradient) — the full
distribution lives in the legend box-plot below instead.

**Legend.** &#8220;now&#8221; caret + box-plot (thin whisker = 9-in-10 / p10–p90, thick bar =
usual half / p25–p75, tick = mean), identical scheme to Entry-02 (§14). Numbers label the
9-in-10 ends and the mean.

**Build guard.** `reliability.guard_carpet_payload` (a §10-style gate, called in `derived.build`)
asserts: days non-empty, sorted and unique; every `cf` array exactly 48 periods; every non-null
value in `[0, 1]`; `sat` in `(0, 1]`. Any breach raises `GuardError` and writes nothing.

**Recompute gate.** `tests/test_reliability_carpet_gate.py` independently re-derives a sample of
carpet cells from the committed CSVs (no `engine.reliability` import) and asserts the published
file agrees.

**`reliability_all.json` removed.** The all-time toggle was removed with the 1-D stripe.
`reliability_all.json` is no longer emitted by `engine.derived.build`. `reliability_year.json`
(flat, rolling 12 months) is retained solely as the share-card source (§13).

## 16. Grid Conditions panel — lamp thresholds *(usual-half policy, 2026-06-29)*

The homepage's Grid Conditions rail lights four lamps from the **live** dashboard figures (no
new derived series — every lamp reads the same numbers the live verdict / capacity dials show,
so a lamp can never disagree with the chart it summarises).

**Site policy — the "usual half" rule.** A computed lamp goes amber when the live reading leaves
the **usual half** — the IQR box (P25–P75) of that panel's own rolling-year distribution, the
*thick bar* of the box-plot drawn under each carpet legend — on the concerning side. The threshold
is read **live from that box-plot** (each panel's `distForDays(...)` percentiles), so there is no
hand-picked constant to defend and a lamp can never contradict the box beside it. The concerning
side depends on the metric: for wind CF and firm share a **low** reading is the worry (`< P25`);
for imports a **high** reading is the worry (`> P75`). The rule is self-updating (the band drifts
with the rolling year) and self-documenting (the band is already on screen). The official scarcity
lamp is exempt — it is a NESO notice, not a computed band.

**Wind lull — trips on AND displays live wind CF `< P25`.** The lamp lights on the *live* wind
capacity factor — live wind output (Elexon FUELINST + NESO embedded) ÷ DUKES total UK wind nameplate,
the figure the Entry-02 capacity dial points to — against the **P25** of that dial's box-plot (the
left edge of the usual half: becalmed more than three-quarters of the year), and it **displays that
capacity factor itself** ("X% of capacity"). A lull is a capacity-factor story — whether the wind is
blowing enough to use its plant — so the CF is the honest reading; it has no demand term, so there is
nothing to apportion or de-rate and the "does it match the receipt?" question does not arise. (It was
briefly displayed as wind's share of demand to echo the §01 receipt — but the receipt counts a net
export off weather generation first, so its apportioned wind sat a point or two *below* the raw lamp
during exports. A category error: the receipt measures wind *meeting demand*, the lamp measures
whether the wind is *blowing*.) **No run-length is shown:**
a "Day N of a run" counter would need *settled* daily CF, but complete settled FUELHH lags ~5 days,
so it can never reflect the current day — it would contradict the live dial (the exact bug that
motivated this design). The lull-*duration* story ("when the wind stops, it stops for days") is told
honestly, on settled data, by the wind detail page's drought plot. An earlier `wind_live_run.json`
series (transmission-only daily run counter) was built and then removed for this reason.

**Heavy imports — trips on capacity `> P75`, reads the exposure (`% of supply`).** The *trigger* is
net imports as a share of GB interconnector capacity — the signed figure the Entry-03 dial needle
points to (sum of signed `INT*` columns ÷ active-reporting interconnector capacity; see §15 / the
import-power payload) — exceeding the **P75** of that panel's box-plot (above the usual half: the
cables working harder than in a typical hour). An export hour is a negative share and so never trips.
But the lamp **displays a different number from the one it trips on**: it reads **net imports as a
share of supply** (`net imports ÷ demand`, ≈ 18–20% live), labelled "*X% of supply*". *Why split
them:* cable-fullness (the trip basis) sizes the *pipe*, but the *risk* heavy imports flag is reliance
on neighbours who may stop selling — and the size of that hole is how much of demand the imports are
currently carrying, not how full the cables are. So the trigger stays tied to the panel's own
distribution (lamp and dial agree on *when* it is heavy) while the reading states the *exposure*. The
two never contradict (both say "heavy"); they show different faces. *Basis history:* an even earlier
build *tripped* on "`> 25%` of demand", which broke when the Entry-03 panel was reframed onto capacity
(lamp read demand, dial read capacity — the panel could show a heavy lean while the lamp stayed
nominal). Trip-on-capacity fixed the *trigger*; reading share-of-supply fixes the *number's meaning*.

**Unreliable — live firm share `< P25`.** The lamp (titled **UNRELIABLE**) turns amber when the live
firm share — reliable *dispatchable* power (gas + nuclear + biomass + other firm); **imports are NOT
firm**, they sit in the unreliable bucket with wind and solar — falls below the **P25** of the
Entry-01 reliability box-plot. Firm is then in its worst quarter of the year, so weather + imports are
carrying an unusually large share of demand. The trip logic stays in firm terms (to match the firm
distribution), but the lamp **displays the unreliable share** (`100 − firm`, e.g. "64% weather and
imports") so the number rises with the alarm and agrees with the title — the rail-level echo of the
§01 verdict gauge's own RELIABLE / UNRELIABLE flip. (This replaced a fixed `< 50%` "majority line";
under the usual-half policy the trip point is the distribution's lower quartile, roughly coincident
with the verdict gauge's `< 40%` red zone rather than an earlier warning.)

**Source-trace.** The panel's pure threshold logic (`site/conditions.js`) takes each percentile as
an argument and is unit-tested (`site/conditions.test.mjs`, run under `tests/test_parity.py`);
because each lamp consumes the same live figures and the same box-plot the dashboard already
renders, there is no separate series to drift. Wiring (which distribution feeds which lamp) is in
`updateComputedLamps()` in `site/app.js`.

## 17. System sell-price history store *(Import-cost panel, Task 1, 2026-06-28)*

`engine/system_price_history.py` pulls Elexon's **settled system sell prices** into an
append-only, git-diffable CSV store — `data/history/system_price_YYYY.csv`, one file per
settlement year — using the same `engine/widestore.py` primitive as the FUELHH (§6) and embedded
(§11) stores.

**Endpoint.**
```
GET https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/{date}
```
Returns `{"data": [{"settlementDate": "YYYY-MM-DD", "settlementPeriod": N,
"systemSellPrice": float_or_null, ...}, ...]}`. One request per settlement day;
the endpoint has no `/stream` variant or bulk-range parameter. Records with a null
`systemSellPrice` are dropped by `parse_day` — they represent settlement periods not yet
published.

**Store format.** Wide CSV, one row per settlement half-hour, columns:
`settlement_date, settlement_period, system_sell_price`. The price column (£/MWh) is stored
as **text** (not integer-truncated, unlike the MW columns in FUELHH/embedded) to preserve
decimal precision; `read_store()` converts it back to `float` on read.

**Revision policy — `on_revision="update"`.** Elexon revises settled system prices
retrospectively (re-runs after late meter data, dispute resolution, etc.). The daily `append`
verb uses `on_revision="update"` so the store tracks the latest published figure, with git
as the audit trail for any change. The one-time `backfill` uses the default `"raise"` —
a revision during initial backfill is a genuine conflict to surface.

**Clean-data edge.** Mirrors FUELHH: `PRICE_EDGE = 2016-01-01`. Settlement prices exist
on the modern API from this date; the full backfill (Task 2) populates 2016-01-01 to
`today − 5 days`.

**CLI verbs.** `backfill [start] [end]` / `append` / `validate` — same shape as §6.
`validate` reuses `history.expected_periods()` and `history.validate_range()`: a settlement
day has 48/46/50 periods (same DST-aware rule), so the completeness check is identical.
**Known gaps.** Like §6, genuine Elexon non-publications are frozen in a manifest —
`data/history/system_price_known_gaps.csv` (`settlement_date,actual,expected,shortfall,note`).
The 2016→edge backfill (Task 2) surfaced **14** days where Elexon simply omits one to three
settlement periods (absent from the `data[]` array, not null prices); `validate` loads the
manifest so the gate passes on those documented holes but still fails on any NEW incomplete day.
The store read glob is `system_price_20*.csv` so the manifest file isn't ingested as a year file.

## 18. Import-cost panel — metric, negative-price floor, carpet scale *(Import-cost panel, 2026-06-28)*

`engine/import_cost.py` joins the FUELHH net-interconnector flow (§6) to the system-price store
(§17) on `(settlement_date, settlement_period)` and emits `site/data/import_cost.json` (a daily £
carpet + dial inputs) via `engine.derived.build`.

**Metric.** `import_value_£(sp) = max(net_import_mw(sp), 0) × 0.5h × system_sell_price(sp)`, summed
to a daily £ (the carpet cell). `net_import_mw` is the case-insensitive sum of all `INT*` legs,
identical to `grid_engine` so a JS port can't diverge. The figure is **net imported energy valued
at the GB system (cash-out) price — NOT the contractual cost of the imports**, which clear in the
day-ahead auction; the `metric_label`/`caveat` fields and the methodology page say so.

**Negative-price floor (Richard's call, 2026-06-28).** GB system prices go negative in oversupply
(2,742 positive-import half-hours over the record). The spec metric (no outer max) would then yield
a *negative* £ cell, contradicting the non-negative guard. Resolution: floor each half-hour's
contribution at £0 — `max(imp × 0.5 × price, 0)` — i.e. valued at **max(system price, 0)**: a
negative cash-out price on an imported half-hour means no cost, not negative cost. Effect: +0.56% on
the all-time total vs signed; the headline days are unaffected. `import_mwh` is left unfloored, so
`mean_price = value / mwh` reflects realised cost.

**Carpet colour scale.** `scale.cap_gbp` is the sqrt-ramp saturation point, set **from the data**:
`_cap_for` rounds up to the next £10m above the costliest day (**max £94.4m → £100m**), floored at
`CAP_FLOOR_GBP = £20m` so a quiet sample can't collapse the scale. Tuned against the real distribution
(median £3.2m, p90 £10.8m, p99 £19.9m): at a £100m cap the everyday range sits in the pale half and
only the genuinely costly days read deep red. The cap is a **colour clamp only** — no datum is
truncated; days at the top of the tail all read deepest-red but are named explicitly by the on-carpet
record marker, the caption, and the costliest-days list, so no figure is hidden. An earlier
draft carried a cited £1,379/MWh emergency-import figure (Montel/Guardian); it was **dropped** — the
panel shows only figures reproducible from Elexon/NESO/DUKES, never an unverifiable external number.

## 19. Provenance registry — the single author of source + basis + caveats *(2026-06-29)*

Provenance (which feeds a figure, the formula in words, the disclosed caveats) used to be
triplicated — in the engine payloads (`*.json` `source`/`basis` fields), in hardcoded strings in
`site/app.js`, and in prose here and on `methodology.html` — and it drifted. **`engine/sources.py`
is now the single author.** It holds a flat registry of ~12 units keyed by stable ID (`verdict`,
`reliability-carpet`, `wind-dial`, `wind-carpet`, `solar-dial`, `solar-carpet`, `wind-unreliability`,
`import-power`, `import-cost`, `overcast`, `warnings`, `lamps-computed`), each carrying its feeds
(name + url), basis, `cadence` (`live`/`settled`), `section`, caveats and method anchor.

- **Emitted** to `site/data/sources.json` by `engine.derived.build` (guarded by `sources.guard_payload`).
- **Methodology cards GENERATED** from it: `engine/methodology.py` renders the "Sources at a glance"
  cards into `site/methodology.html` between the `GENERATED:sources` markers (static, no-JS, indexable).
  The hand-written conceptual prose below the cards stays — NOTES and the prose are for *reasoning*
  (why a denominator, why the mean not the median), the registry is for the *source strings*.
- **Front page cut**: the homepage's ~9 per-figure source lines became **3 "Sources & method →" links**
  (one per §01/§02/§03 → `methodology.html#src-group-<section>`), plus a registry-`cadence`-driven
  "settled strip" chip. The §01 verdict snapshot line was dropped — the same `verdict.snapshot` the
  GRID WARNINGS band already shows; the band is the single freshness clock. `site/app.js` reads
  `data/sources.json` into `SOURCES` and `sectionSrc(section)` renders the links.
- **Machine-checkable**: `tests/test_provenance_gate.py` asserts the methodology page's `data-unit`
  cards == the registry exactly (no stale card, no undocumented figure) and that every front-page
  section link resolves to a generated card group. A registry change that isn't rebuilt fails the gate.

The per-module payload `source`/`basis` fields remain (the share cards and some panels still read
them); the registry is their canonical home and should be kept in step when a basis changes.
