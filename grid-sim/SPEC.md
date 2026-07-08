# Grid-Sim — design specification (v0.3)

A standalone Rust library for simulating the GB electricity system. Built to compute
counterfactuals, size storage and back-up, explore market-rule alternatives, and drive
an online teaching game. *Library-first*: the core is a pure, deterministic simulation
engine; everything else (CLI, game, plots) is a separate consumer of it.

> **v0.3 changelog.** Added first-class support for **multi-decade, continuous-horizon
> runs with persistent storage state**, so storage sizing can be tested against the full
> historical weather record including inter-year variability (the binding deficit can span
> years, e.g. the 2009–11 wind lull). A run is now over a weather *record* of arbitrary
> length, not a single year; storage SOC carries across the whole record and is never reset
> at year boundaries. Changes in §2, §3, §4, §7, §13, §14. This is a horizon-and-data
> capability inside v1, **not** the greenfield cost-optimiser ("Mode B") — that remains
> parked. Designing SOC-carryover into the core now avoids a later rewrite.

> **v0.2 changelog.** Revised after critique by three context-free expert reviewers
> (energy-system modeller, energy-system economist, game/Rust-wasm engine designer).
> Their full critiques are in `CRITIQUES.md`. Material changes: two-basis costing (§8);
> the "pay twice" retained-firm cost (§8); v0 storage demoted to illustrative, adequacy
> headline moved to v1 (§2, §7); embedded-generation / demand-basis resolution (§8a);
> carbon as transfer vs resource cost (§8); endogenous CfD reference price (§8); a
> determinism contract (§13); schema versioning + run provenance (§9a); settlement
> reframed as redistribution-only and the nodal claim corrected (§5); game shell set to
> JS/TS-over-wasm in a worker (§10); validation tolerances pre-committed (§14).

---

## 1. Purpose and end-uses

Three end-uses, one engine:

1. **Counterfactuals.** What the GB system would have cost over real historical years
   under a different mix or market design — e.g. an all-gas (CCGT) fleet vs the subsidised
   wind/solar system actually built, including CfD top-ups and the Renewables Obligation.
2. **Storage and back-up sizing.** How much storage (energy *and* power) and firm back-up
   a renewable build needs to keep the lights on through real wind droughts, and how that
   requirement scales. **(Adequacy headline is a v1 deliverable — see §2/§7.)**
3. **Teaching game.** An online "Energy Game": configure a fleet and market, run it against
   real or synthetic weather, see cost, emissions and reliability — the energy trilemma,
   hands-on.

The same deterministic core serves all three: *take a demand series and weather-driven
renewable output, dispatch a fleet by merit order, account for cost.*

---

## 2. Scope ladder (deliberate simplicity first)

**Run horizon (applies to all versions).** A run is over a weather *record* of arbitrary
length — one year (~17,520 half-hourly steps) for a market/counterfactual run, or the full
multi-decade reanalysis record (~40 years ≈ 700k steps) for storage sizing. **Storage state
of charge persists continuously across the whole record and is never reset at year
boundaries** — inter-year carryover is the whole point of the multi-decade mode, since the
binding deficit can be a multi-year span (the 2009–11 wind lull), not a single bad year. The
single horizon parameter and persistent SOC are core from the start; you cannot recover
inter-year carryover by looping a per-year run.

**v0 — copper-plate GB, cost/counterfactual done properly.** Single node, half-hourly,
greedy merit-order economic dispatch (one weather year for the cost headline). v0's *job* is
the
cost/counterfactual headline, defensible: a resolved demand basis (§8a), a gas fleet with
an internal merit order and part-load heat rates (§8), a transmission/distribution loss
factor, explicit interconnector treatment, carbon reported with and without ETS, and an
endogenous CfD reference price. Storage in v0 is the heuristic (charge on surplus,
discharge on deficit) and is **illustrative only — it does not publish a storage number.**

**v1 — economic + adequacy realism.** The storage/adequacy headline lives here: the
**multi-decade continuous run with persistent SOC** (above) for storage sizing against
inter-year weather variability; a storage LP with foresight (reported as a floor alongside a
rolling-horizon number); a system reserve constraint with a defined sizing rule;
thermal/nuclear de-rating and forced outages; a configurable minimum-synchronous (must-run
inertia) floor; price-responsive interconnectors with correlated availability (§6);
pluggable settlement rules (§5); monetised storage, curtailment and back-up (§8).

**v2 — operational/structural realism (resist unless required).** Regional/nodal network
with power-flow limits and boundary (B6) constraints; unit commitment (min up/down, ramp,
start costs); strategic bidding agents; endogenous investment (build/retire); stochastic
weather ensembles.

The polemical and teaching force comes from v0/v1 being simple enough to be unimpeachable.
**Rule: a v0 PR that adds v2 abstraction (node graph, agent traits, UC state) is rejected.**
Leave the *seams* (§5), build nothing behind them until needed.

---

## 3. Architecture

A Cargo workspace. Strict dependency direction: everything depends on the core; the core
depends on nothing platform-specific.

```
grid-sim/
  crates/
    grid-sim-core/        # THE PRODUCT. Pure, deterministic, no I/O, no rendering.
    grid-sim-data/        # Loaders: real GB series -> core types. Owns all I/O.
    grid-sim-scenario/    # Declarative scenario definition + sweep expansion + versioning.
    grid-sim-cli/         # Batch runner: counterfactuals, sweeps, scenario compare.
    grid-sim-validate/    # Parity vs ELEXON/NESO/PyPSA-GB. Heavy deps, feature-gated.
  game/                   # Separate: compute-only wasm core + JS/TS UI (see §10).
```

**Core invariants.** `grid-sim-core` has no file I/O, no network, no rendering, no
framework dependency, no global state, and `#![forbid(unsafe_code)]`. It compiles to native
and wasm unchanged. Heavy data crates (`polars`, etc.) live in `-data`/`-cli`/`-validate`,
never the core, to keep the wasm bundle lean.

**The fundamental contract:** a run is a pure function
`run(scenario: &Scenario) -> Results`, deterministic and cheap to call repeatedly (the seed,
if any, lives inside `Scenario`). Everything — sweeps, the game loop, future investment
dynamics — is an outer loop over this function. The fleet is external data the caller
varies; it is never mutated inside a run.

**Horizon and state.** The `Scenario` carries a weather record of arbitrary length and a
run horizon; the run steps once through the whole record. **Storage state of charge is
internal to the run and carries across the entire horizon** — it is initialised once at the
start (a declared `initial_soc`, or "filled") and never reset at year boundaries. A
40-year run is therefore one `run()` call over a ~700k-step record, *not* 40 chained
yearly calls — chaining would reset SOC and destroy the inter-year carryover that storage
sizing depends on. SOC is the only state that crosses steps; the run remains pure (same
record in → same results out).

---

## 4. Domain model (core types)

- `Technology` — a *generation* type: marginal cost inputs (fuel price, efficiency/heat
  rate, carbon intensity, variable O&M), carbon emission factor, and a dispatch role
  (must-run renewable / baseload / dispatchable thermal / peaker). Storage and
  interconnectors are **sibling types, not technologies** (they carry state / a foreign
  price; do not overload one mega-enum).
- `Unit` / `GeneratorBlock` — installed capacity of a technology **at a node**, carrying a
  marginal cost and an optional **bid** (`bid: Option<Bid>`; `None` ⇒ bid == running cost,
  the v0/v1 invariant encoded in the type, not in discipline; v2 makes bid a function of
  strategy).
- `StorageUnit` — **separate** power rating (MW charge/discharge) and energy rating (MWh),
  round-trip efficiency, and state of charge that **persists across the whole run horizon**
  (initialised once from a declared `initial_soc`). (Power/energy separation makes the
  duration cliff visible; persistent SOC makes inter-seasonal and inter-year storage real.)
- `Interconnector` — a link to a neighbour node with a fixed **capacity** (cable MW) and a
  separate per-step **availability** (deliverable MW), plus the neighbour's price (§6).
- `Node` — a location. v0 has one node ("GB"); generation and demand are **keyed by
  `NodeId`** (a newtype index over `Vec`-backed collections) from day one, with the
  single-node fast path hard-coded and **no graph/flow machinery** until v2.
- `WeatherRecord` — per-step capacity factors for weather-dependent technologies over a
  record of **arbitrary length** (one year, or the full ~40-year reanalysis span for storage
  sizing), from real reanalysis/outturn. The *same* weather drives GB renewables and
  neighbour availability so correlations are observed, not imposed. (A single year is just a
  record of length one year — there is no separate `WeatherYear` type.) Multi-decade records
  must be a **continuous, gap-filled hourly/half-hourly series** with a stated resampling and
  gap policy (§8a, §14); year boundaries follow an **April–March** convention so a severe
  winter is never split across the seam.
- `DemandSeries` — per-step, per-node demand on a **declared basis** (§8a). Reshapeable for
  electrification scenarios, not just scalable.
- `Fleet` — the full set of units, storage, interconnectors and network for a scenario.

---

## 5. Dispatch and settlement (the swappable seams)

Two concepts kept strictly separate:

- **Dispatch** — *who runs.* A `DispatchStrategy` trait at **per-step** granularity
  (`dispatch_step(&self, state, ctx) -> StepDispatch`; never per-unit — that's 7M+ vtable
  calls). v0: greedy merit order, no foresight. v1: optimising strategy + storage LP. v2:
  bidding agents. The last (most expensive) unit dispatched sets the marginal price.
- **Settlement** — *what they get paid.* A `PricingRule` trait, a pure function over the
  dispatch result. Implementations: pay-as-clear (system marginal price), pay-as-bid, and a
  split/decoupled pool.

**Framing constraint (do not overclaim).** Settlement experiments are **short-run
redistribution only** — who earns what with dispatch and bids held fixed at cost. They are
silent on investment response and the missing-money problem. Two specific corrections:
- *Pay-as-bid* with `bid == cost` produces the canonical wrong answer (it appears to "save
  money" by paying everyone marginal cost, ignoring that real bidders shade offers upward).
  The model may show the mechanical payment but must label it an upper bound on savings that
  strategic bidding erodes.
- *Nodal/LMP pricing is **not** "just a new `PricingRule`."* LMP changes *dispatch* by
  internalising network constraints, and collapses to a single price in copper-plate. It
  requires the v2 network; it is not achievable over v0.

### The four extensibility seams (cheap now, expensive to retrofit)
1. **cost ≠ bid** — `Option<Bid>` per unit.
2. **dispatch strategy trait** — greedy / optimised / agent, per-step.
3. **settlement as its own step** — pricing rule independent of dispatch.
4. **node-keyed collections** — one node in v0, structurally regional-ready.
Plus **pure runs** — `(Fleet, WeatherYear) -> Results`, fleet external, so investment
dynamics are just an outer loop.

---

## 6. Imports / interconnectors

Load-bearing distinction: **capacity ≠ availability**. The cable MW rating is fixed; the
deliverable power in a half-hour is not. An interconnector links to a *priced neighbour
node*; in merit order an import offer enters the stack at the neighbour's price, bounded by
`min(capacity, availability)`. When availability collapses the import is absent and GB
covers residual from domestic firm plant or sheds load (unserved energy).

**v0 must state the counterfactual import treatment explicitly:** in the all-gas world, are
imports (a) held at historical outturn, or (b) re-dispatched on price against an all-gas GB?
These give different numbers; the choice is a declared scenario property, not a default.

**Driving availability — two routes, rigidly separated:**
- *Data-driven (descriptive claims).* Neighbour availability derived from the **same
  weather year** as GB renewables, using real per-country data (ENTSO-E Transparency) or
  reanalysis CF (renewables.ninja / MERRA-2) for FR/BE/NL/DE/DK/NO. The synoptic
  correlation is *observed*, not assumed.
- *Parametric synoptic overlay (game + sensitivity).* Scales neighbour export availability
  down as a function of GB wind CF over an event window, with a severity dial. **Badged
  scenario, never history; the severity dial must never leak into a descriptive claim.**

**Caveat to respect:** neighbour *export availability* is driven by neighbour *residual
demand and scarcity pricing*, not neighbour wind CF alone — French nuclear and Norwegian
hydro (reservoir-level dependent, a slow variable) are genuine diversifiers. Modelling
availability as f(neighbour wind) alone is too pessimistic and is acceptable only as the
parametric overlay. The data-driven route should use neighbour residual/scarcity where it
claims to be observed. Model several distinct neighbour types, not one slab. This lets the
model **derive interconnector capacity credit endogenously** (the Capacity Market de-rates
interconnectors ~60–70% for exactly this correlated-scarcity reason) rather than asserting
it — but only the data-driven route may publish that derivation.

---

## 7. Storage and back-up

- **v0 (illustrative only):** heuristic — charge on renewable surplus, discharge on deficit,
  within power/energy limits and round-trip efficiency. Deterministic by construction. Used
  in the game and for illustration; **publishes no storage number.**
- **v1 (the adequacy headline):** an LP optimiser, but reported honestly — a perfect-
  foresight solve is a *lower bound* ("even with a crystal ball you need this much"); a
  rolling-horizon (receding-window, e.g. 48–96h) solve is the operational number reported
  above it. Separate power from energy ratings so the duration cliff is explicit.
- **Split the optimiser by end-use:** the LP is a CLI/analysis path (a slower batch run is
  fine for sizing). The interactive game ships the heuristic — the LP must not gate the
  game loop, and `clarabel` stays out of the browser in v1 (see §13 on its nondeterminism).
- Pumped hydro / reservoir hydro have specific energy/inflow/head constraints a generic
  `StorageUnit` does not capture; treat generically in v0/v1 but label it.
- **Sizing against the multi-decade record (the inter-year-variability test).** Run a fixed
  fleet continuously over the full ~40-year record with persistent SOC and report, as
  first-class outputs: the **cumulative surplus/deficit curve** over the whole record; its
  **peak-to-trough span = the minimum store energy required** (start-SOC-independent by
  construction, so the answer doesn't depend on assumed initial fill); the **maximum
  residual power = the charge/discharge power rating required**; the identity and span of the
  **binding deficit event** (which may cross years); and a **contingency multiplier** knob
  (the Royal Society used +20% to cover weather rarer than the record). This is the analytic
  that tests storage estimation against long-term weather including inter-year variability,
  and it is what validates against the RS study (§14).
- Outputs: SOC trace through a real drought; firm-capacity requirement retained regardless
  of renewable build (costed in §8); the minimum store energy/power to firm a given build
  across the **whole multi-decade record** (not a single design year), with the binding
  multi-year event identified (§12 on the event definition).

---

## 8. Economics and accounting

The flagship outputs are economic, so this section is where the model is most attackable.
The governing rule, applied everywhere:

> **Two-basis costing, identical for every fleet.** Every headline exists in two forms —
> *wholesale-energy-only (SRMC)* and *all-in resource cost* (annuitised capex + fixed O&M +
> variable + storage + back-up). Never compare one fleet's all-in against another's SRMC.
> Both bases are computed the same way for gas and for renewables.

- **Marginal cost** per technology = `fuel_price / efficiency + carbon_price ×
  emission_factor + variable_O&M`. Sets merit order and marginal price.
- **Gas counterfactual** is *not* a single efficiency. The all-gas fleet has an **internal
  merit order** (new/old CCGT + OCGT/recip tiers) and **load-dependent (part-load) heat
  rates**; it must include **start-up and no-load costs** for the cycling a renewable-laced
  residual demand forces. A single ~54% heat rate understates gas cost (i.e. flatters gas)
  — these are v0 fixes because this is the headline number. The counterfactual meets
  **demand (load)**, not a replicated generation total; state whether storage losses,
  curtailment and pumped-hydro are in/out of the MWh base.
- **The "pay twice" line (must-have).** The honest comparison is not "gas system vs wind
  system" but "gas system" vs "**wind system + the firm fleet kept on standby anyway**."
  Net the retained firm-capacity cost (Capacity Market annuity / de-rated firm MW × CM
  price) onto the renewables side. This is both the most honest and the most damning result
  for the built system, and it is the model's strongest legitimate point.
- **Carbon: transfer vs resource cost (must separate).** Report the gas counterfactual
  (i) excluding carbon, (ii) with ETS price as a transfer (what bills see), and optionally
  (iii) with social cost of carbon (the true resource cost). State the carbon price and the
  year prominently — it is the single most rhetorically loaded input. Never bury it inside
  one marginal-cost number.
- **Subsidy accounting (expanded).** CfD top-up + RO + **Capacity Market payments** +
  **constraint/curtailment payments** + a balancing-cost (BSUoS) adder scaling with
  renewable share. The **CfD reference price must be the model's own endogenous gas-set
  marginal price**, not an independent input — otherwise the subsidy number flips sign with
  the assumed gas price (in 2022 CfDs paid money back). RO is legacy/closed; model it as
  (ROCs × buyout + recycle) or scope-limit it explicitly.
- **Relabel honestly.** A "subsidy vs wholesale" figure is **not** a consumer bill — bills
  also carry network, policy, balancing and supplier-margin costs. Do not label it "bill."
- **Monetise what is currently only sized:** storage (£/kW + £/kWh annuity), curtailment
  (volume × constraint-payment rate), back-up (firm MW × CM price). A "total system cost"
  with these left as physical MW/MWh is technically computed but economically misleading.
- **System-cost completeness.** Move from plant LCOE to system LCOE / VALCOE: profile cost
  (capture-price collapse — the model's strongest legitimate cost insight), balancing,
  network/connection, and back-up/adequacy. The model captures profile well, gestures at
  back-up, and **must disclose** that network reinforcement is excluded (copper-plate) and
  that this *flatters renewables*.
- **Provenance + sensitivity as a release gate.** Every cost output carries its price year,
  gas/carbon assumption, discount rate/WACC, and basis. Every headline ships with a stated
  sensitivity band over the dominant drivers (gas price, efficiency, weather year,
  availability, WACC). A single point estimate is attackable; a banded one is not. Run
  across multiple weather *and* price years — never present a single year (especially 2022)
  as representative.

### 8a. Demand basis and embedded generation (must-resolve in v0)

The classic GB error. ELEXON FUELHH/FUELINST is **transmission-system** generation only;
embedded (distribution-connected) solar and small wind (~16 GW rooftop solar) appear as
*suppressed demand*, not generation. Taking BMRS renewables as "GB output" and BMRS/NESO
demand as "GB demand" simultaneously understates output *and* demand, and the errors do not
cancel. **Resolve explicitly:** declare the basis (recommended: national/end-user demand =
TSD + embedded + losses, with embedded-inclusive renewable output via NESO embedded
outturn/Sheffield Solar), and a transmission/distribution **loss factor** (~8% gen-vs-
demand gap) for absolute-£ honesty. The parent `gb-grid-margin` project has already solved
embedded-vs-transmission basis, annual-step nameplate, Elexon settlement-run revisions and
lower-bound CF disclosure — **port that knowledge deliberately rather than rediscover it.**

### 8a-bis. Multi-decade weather record (required for storage sizing)

Storage sizing against inter-year variability needs a **continuous multi-decade hourly/
half-hourly reanalysis CF series** for wind and solar — renewables.ninja / MERRA-2 / ERA5,
~1980–present — *not* the ELEXON settled era (2016+) the cost/counterfactual mode uses. Keep
the two sources in their lanes (the §6/§14 discipline): **metered outturn for historical
replay and validation; reanalysis for the long sizing record.** Validate the reanalysis CF
against outturn over the overlap before trusting the pre-2016 span. State the resampling
rule (hourly→half-hourly), the gap-filling policy, and that ~40 years still **undersamples
rare weather** — beyond ~1-in-10 events the record extrapolates (hence the §7 contingency
multiplier), it does not observe (§12).

---

## 9. Scenario configuration

A scenario is **just data**. Declarative, human-readable, diffable, version-controlled.
**Prefer RON** (round-trips Rust enums for dispatch role / settlement rule cleanly; TOML's
flat tables fight the nested fleet/node structure — if hand-editing prices matters, keep
prices in a TOML side-file). A scenario fully specifies: fleet (capacity per technology per
node), weather record, demand (composed from components — §9b), fuel/carbon prices, discount
rate, storage fleet, interconnector set + availability mode + import treatment, settlement
rule, dispatch strategy, run horizon, and a seed.

Three patterns: **base + overrides** (inherit, change one stated parameter); **sweeps** (a
runner takes a base + an axis to vary → a response curve); **named scenarios** (files in the
repo; every result traces to a config + data version). The game is a scenario edited live
and re-run each tick.

### 9a. Schema versioning and run provenance (must-have)

The project's whole value is auditability, so this is load-bearing, not optional:
- `schema_version` + `#[serde(deny_unknown_fields)]` on every `Scenario` and `Results`
  struct; a `migrate(old) -> new` path; a corpus of old scenario files that must still parse
  in CI. (This is also what stops a shared game-URL link rotting.)
- A **`RunManifest`** inside every `Results`: scenario hash (canonical-serialise then hash
  the bytes — never hash `f64` directly), data-version hashes, engine semver, seed,
  wall-clock. Makes "any number reproducible from source" mechanically true.
- Treat `Results` as a **public API surface** the moment any published number or the game
  depends on it; snapshot-test the serialised JSON shape, not just the internal numbers.

### 9b. Demand specification

Demand is composed from **named additive components**, not baked as one series — so the total
is auditable and "different scenarios" become parameter changes, not new files. Each
component carries an annual energy and a shape/driver; the scenario-layer `DemandModel` scales
and sums them into the single per-step `DemandSeries` the core consumes (the **core stays
dumb** — it never sees components, only the resolved series; composition is a data/scenario
concern, preserving core purity).

```ron
demand: (
    basis: NationalEndUser,            // §8a — declared, kept consistent
    components: [
        ( name: "base", annual_twh: 355.0, shape: Profile("gb_2018_halfhourly") ),
        ( name: "heat", annual_twh: 96.0,  shape: Temperature( source: WeatherRecord, hp_cop: 2.8 ) ),
        ( name: "ev",   annual_twh: 119.0, shape: Profile("ev_smart_charge") ),
    ],
)
```

(The example reproduces the Royal Society 355 + 96 + 119 = 570 TWh decomposition.)

- **Two modes, one type.** *Replay* (cost/counterfactual): a single component pointing at a
  historical outturn series. *Synthetic/projected* (2050 sizing): components scaled to target
  annual energies. Same `DemandSeries` out; different population.
- **Scenarios ride the §9 machinery.** The 440/570/700 TWh variants are a **sweep** over the
  total (or a component's `annual_twh`); "high electrification" overrides the heat/EV
  energies; "smart vs dumb EV charging" overrides the `ev` component's `shape`; "no heat
  pumps" drops a component. One base + stated overrides, so any two demand scenarios differ in
  exactly the declared way.
- **Weather–demand correlation is a property of a component's shape (the important toggle).**
  `shape: Temperature(source: WeatherRecord)` drives heat-pump load from the *same* weather
  record as wind/solar, so a cold calm anticyclone raises demand exactly as wind collapses.
  Switch the same component to `shape: Profile("fixed_2018")` and you have the Royal Society
  assumption (demand repeated, uncorrelated with weather). That one toggle is what turns
  *reproduce RS* into *show RS understates storage need* (§14, §16) — the demand-scenario
  mechanism and the §16 extension are the same lever.

---

## 10. Results schema and visualisation

The core emits a **structured, versioned results schema** (`serde` → JSON/Parquet).
Visualisation is downstream and decoupled — never in the core.

- **Analytical/static** (writing and web): the CLI emits result tables, rendered by a small
  set of *signature* graphics, each carrying one argument: stacked dispatch over time;
  residual-load + storage-SOC trace through a drought; capture-price vs penetration;
  curtailment vs overbuild; cost waterfall (gas counterfactual vs actual + subsidy, on both
  cost bases); reliability (LOLE / unserved-energy) heatmap across weather years; the
  trilemma scatter (cost vs reliability vs emissions).
- **Interactive game (architecture set):** **compute-only wasm core + JS/TS (or Leptos)
  HTML/CSS UI** — *not* egui for the shipped web game (an opaque canvas fights theming,
  mobile, accessibility and share-cards; egui is fine only for a native debug UI). The
  boundary is **data-only** (`run(scenario) -> results`, typed via `serde-wasm-bindgen` /
  `tsify`); never expose core types. Run the wasm core in a **Web Worker** so a 17,520-step
  run never janks the UI. **Two-phase model:** edits to fleet/price/weather trigger a
  debounced recompute; "scrub through the year" and "trigger a blocking high" *animate an
  already-computed result* (a cheap 60fps cursor over cached series), not a per-frame
  re-run. Memoise runs by scenario hash. **Share scenarios via the URL fragment** (versioned
  RON/CBOR, deflate+base64) — essential for a teaching tool, and why §9a versioning is not
  optional. A scenario-diff view is the same schema rendered twice.

---

## 11. Explorations the engine supports

- *Renewable value:* capture-price cannibalisation; curtailment vs overbuild (flag
  copper-plate curtailment as a transmission-unconstrained lower bound until B6 constraints
  exist); negative-price frequency; marginal value of the next GW of wind.
- *Adequacy (v1):* firm-capacity requirement ("build it twice"); LOLE vs the 3-hours/year
  standard; storage duration cliff.
- *Cost/policy:* gas counterfactual; carbon-price merit-order flip; CfD top-up accounting;
  nuclear-firm vs intermittent+storage+gas; settlement-rule redistribution.
- *Demand/weather risk:* electrification reshaping the peak; weather-year sensitivity to
  find the design-driving Dunkelflaute; self-sufficiency / no-imports stress.
- Unifying output: the **trilemma frontier**.

---

## 12. Fidelity, the design event, and the descriptive/predictive ceiling

Sits deliberately below the professional models (DESNZ DDM, NESO PLEXOS, AFRY BID3, Aurora)
and the open academic PyPSA-GB. Simplifications: single node vs nodal; economic dispatch vs
unit commitment; greedy/LP vs full UC; exogenous vs endogenous fleet; single historical
weather years vs stochastic ensembles; no behaviour/losses-beyond-a-factor/inertia (v1 adds
a must-run floor). Temporal resolution (half-hourly, full year) matches or exceeds the
professionals.

**Descriptive ceiling: high** for the cost/price/settlement questions — accounting truths
over real demand/weather/output where copper-plate plus real marginal pricing reproduces the
phenomenon. **Predictive ceiling: low** — frame as a *scenario calculator, not a forecaster*.
"Given this fleet and this weather year, here is the cost and the storage gap" is honest;
"here is what 2035 will cost" is beyond the model. Never let a scenario projection be
reported as a prediction.

**Define the Dunkelflaute (must-have, currently undefined and load-bearing).** Specify the
meteorological event — threshold (e.g. combined wind+solar CF < X% of demand), duration,
area — the dataset length, and the return-period method. With ~10–14 years of good
reanalysis you **cannot count a 1-in-20**; state plainly that return periods beyond ~1-in-10
are extrapolations, not observations. "The design-driving Dunkelflaute" must be a defined
event, not an assertion.

---

## 13. Determinism contract (must-have — currently asserted, not engineered)

Two of the three end-uses must agree to the penny: the CLI headline number must equal what
the game shows, or the credibility argument collapses. Mandates:

- **Ordered collections only.** Iterate `BTreeMap` / `IndexMap` / `Vec`-indexed newtypes —
  **never `std::HashMap`** (randomised iteration order).
- **No parallel float reductions.** `Σ` over the year is not associative in IEEE-754; never
  `par_iter().sum()` a float without a fixed-order fold. Parallelism is at the **sweep**
  level only (rayon over independent runs), never inside a run (storage SOC is sequential —
  doubly so for a multi-decade run, whose entire point is the sequential SOC carry; the
  ~700k-step cumulative deficit fold must be fixed-order or the storage number is not
  reproducible).
- **RNG:** `rand_chacha::ChaCha8Rng`, seeded from the scenario — never `thread_rng`, the OS
  RNG, or `StdRng` (algorithm unstable across versions).
- **Fixed-point money.** Represent published currency figures as `i64` minor units (or a
  `fixed`/`Decimal` crate) so they are exact and platform-independent; keep physical
  quantities (MW, MWh) in `f64`. This sidesteps the native↔wasm float divergence for exactly
  the numbers that are politically contested.
- **wasm vs native.** Byte-identical `f64` across platforms is **not** guaranteed (FMA
  contraction, historic x87). Define determinism as *within-platform byte-identical* +
  *cross-platform within a documented ULP tolerance* (the fixed-point money figures are exact
  regardless). Forbid relying on `mul_add`; set `RUSTFLAGS` consistently.
- **LP nondeterminism (v1).** Interior-point/simplex solvers return different optimal
  vertices for degenerate problems (flat-price periods → tied storage schedules) and vary
  across versions. Pin the solver version; add a deterministic lexicographic tie-break on the
  reported schedule; snapshot-test and expect to re-bless on solver bumps. The deterministic
  v0 heuristic is the canonical *published* storage path; the LP is exploratory/analysis.

---

## 14. Testing and validation

- **Software gates:** determinism (within-platform byte-identical); snapshot tests (`insta`)
  on dispatch/settlement outputs *and* on the serialised `Results` schema; golden analytical
  cases (hand-computable small fleets); property tests (`proptest`) — shares sum to demand,
  SOC within limits, **energy conserved** (the single best correctness net, also a hard
  runtime guard, not only a test); centralised loud `GuardError`s (port `engine/guards.py`
  discipline); `criterion` benchmarks **gated in CI** with a regression threshold; a
  **wasm32 CI job** that diffs the wasm result against native on a golden scenario (the only
  guard against native↔wasm divergence); `cargo-fuzz` on the scenario deserialiser before
  the game accepts shared URLs from strangers; never panic on bad input in the core (return
  `Result`; `thiserror` in core, `anyhow` only in shells — a wasm panic is an unrecoverable
  tab-killing trap).
- **Scientific validation (pre-commit the tolerances).** PyPSA-GB is a **cross-check, not an
  oracle** (it has its own simplifications; never let it certify a headline, least of all
  storage where both share the foresight problem). Against ELEXON/NESO outturn, reconcile on
  pre-committed tolerances for: annual energy by fuel; the **price duration curve shape**
  (especially the high-price tail — not just the mean); monthly/seasonal and diurnal energy
  patterns (a model can match annual totals while getting the pattern wrong, invalidating
  storage claims); emissions vs NESO carbon-intensity outturn. Additional gates: reproduce
  the **marginal-fuel split** (how often gas sets the price — the "bills track gas" claim,
  validated directly); **energy-balance closure < 1%** on real-replay; **capture-price**
  validation against published outturn capture prices (if it can't reproduce *historical*
  cannibalisation, the forward curve is worthless); **adequacy** against NESO's published
  LOLE / de-rated margin using their de-rating factors.
- **Storage-sizing reference case (Royal Society 2023).** Validate the multi-decade sizing
  mode against the Royal Society *Large-scale electricity storage* study (Llewellyn Smith,
  DOI 10.1098/rs-policy.2026-14) as a documented reproduction target: 37 years of
  renewables.ninja weather (1980–2016), single-node GB, ~570 TWh demand, 80/20 wind/solar,
  hydrogen store at 41% round-trip (74% electrolyser × 55% H₂→power), April–March years. The
  test: with the *same* inputs, reproduce their order-of-magnitude results — store volume
  ~60–120 TWh, threshold overbuild ≈ 1.23× demand, the 2009–11 binding period. Reproducing
  these is the proof the inter-year-variability sizing works. Note the RS study is itself a
  **cross-check, not ground truth** (it omits weather–demand correlation, which it states
  *understates* storage need — see §16, the on-brand extension that drives their number up).

`serde` + `serde-wasm-bindgen`/`tsify` (boundary), RON (scenarios), `polars`/`ndarray`
(data/cli/validate only), `smallvec` (per-step merit stack), `rayon` (sweep-level only, CLI;
not wasm without `wasm-bindgen-rayon` + COOP/COEP), `rand_chacha` (RNG), a fixed-point/
`Decimal` crate (money), `good_lp`/`clarabel` (v1 LP, CLI-only), `criterion` (benchmarks),
`insta` (snapshots), `proptest` (properties), `cargo-fuzz` (deserialiser), `thiserror`/
`anyhow` (errors), `wasm-bindgen`/`wasm-pack` + a Web Worker + JS/TS or Leptos (game).

---

## 16. Open questions

- Game shape: fleet-builder vs live-dispatch sim? (Sets the shell.)
- Priority: the unimpeachable counterfactual number, or a free exploratory sandbox? (Sets
  how much fidelity to buy.)
- Neighbour-data source of record for interconnector availability — reanalysis CF for the
  physical correlation, ENTSO-E (gappy; budget for cleaning) for validation only?
- How much of the parent `gb-grid-margin` data pipeline to reuse directly vs reimplement in
  `grid-sim-data`?
- **Weather–demand correlation (the on-brand extension to the RS sizing case).** The Royal
  Society study holds demand fixed and repeats one profile, which it acknowledges
  *understates* storage need (cold, calm anticyclones = low wind *and* high heat-pump demand
  at once). grid-sim already drives renewables and neighbour availability from the same
  weather record; extending that to drive **demand** (temperature-dependent heat-pump load)
  from the same record would reproduce the RS number and then show it is a **conservative
  floor** — real storage need is larger. Worth doing *after* the plain RS reproduction
  validates, so the two numbers are directly comparable. Decision: is this a v1 sizing
  feature or a deliberate follow-on study?
- Greenfield cost-optimiser ("Mode B") stays parked — the sizing mode above tests storage
  *estimation* against weather without needing the £/MWh minimisation. Build Mode B only if
  the question shifts from "how much storage does this fleet need" to "what is the
  least-cost fleet+storage mix."
