# Grid-Sim — expert critiques of SPEC v0.1

Three context-free expert reviewers were each given SPEC v0.1 and nothing else, and asked
to critically examine it and recommend scope additions for completeness, efficiency,
maintainability and extensibility. Their full critiques are preserved here verbatim; the
synthesis was folded into SPEC v0.2.

---

# 1. Energy-system modeller

**Reviewer stance:** GB system modeller. The architecture (pure core, swappable dispatch/
settlement traits, node-keyed-from-day-one) is good engineering. The job here is the physics
and the numbers. §12 claims a "high descriptive ceiling" for the counterfactual, storage and
settlement questions, and that v0 is "simple enough to be unimpeachable." For two of three
headline questions that holds with caveats; for storage/adequacy it does **not** hold as
specified.

## 1. Methodological soundness — where v0 gives materially wrong numbers

**1.1 Gas counterfactual — formula wrong on two counts.** A single fleet efficiency is wrong
by 5–15%: real CCGTs run a load-following duty cycle (part-load loses ~3–5 pts; ~52%→~48%
LHV), and the fleet includes OCGT/recip at ~35–42%. One ~54% number *understates* gas cost —
i.e. flatters gas, cutting against the thesis. Fix in v0: a merit order within the gas fleet,
or a load-dependent heat-rate curve. Also `Σ generation_MWh` over which demand? Gas must serve
*all* demand including what renewables served; the import treatment in the all-gas world must
be pinned (held at outturn vs re-dispatched on price). Missing entirely: start-up/no-load/
cycling costs — a renewable-laced residual forces hard cycling that copper-plate greedy
dispatch can't see. Safe to omit only if stated as understating gas (again cuts against
thesis).

**1.2 Greedy storage is not conservative.** Fine for price formation (an accounting truth).
But reused for storage sizing, "charge on surplus" can fill the battery Tuesday and be full
when the binding 5-day drought starts Friday (under-size), or hold charge it should release
(over-size). Error unbounded. **The storage headline must not ship on v0.** §2's "v0 alone
delivers a defensible storage number" is false.

**1.3 Perfect-foresight LP is the opposite failure** — it *under-sizes* by dispatching with a
crystal ball. Report perfect-foresight as the optimistic *floor* ("even with foresight you
need this much"), with rolling-horizon as the honest operational number above it.

**1.4 Copper-plate — safe except B6.** Scotland–England boundary constraints and the wind
curtailment + constraint payments (£1bn+/yr) they cause are erased by copper-plate. The moment
you touch curtailment cost, flag it a transmission-unconstrained lower bound or pull boundary
constraints forward.

## 2. Missing physics that invites attack

(a) **Reserve/response/ancillary — biggest single gap.** Energy-only dispatch over-dispatches
inflexible plant and under-costs the system. Add a system reserve constraint at v1 with a
*defined* sizing rule, not a placeholder. (b) **Must-run / minimum stable generation for
inertia.** GB can't run ~100% inverter-based; a configurable minimum-synchronous MW/% floor is
cheap and pre-empts "you ignored inertia" on renewable-system runs. (c) **Thermal availability
/ forced outages** — adequacy is *governed* by this; 100%-available firm plant under-sizes
back-up. Must-add for any adequacy headline (de-rating per technology minimum). (d)
**Interconnector availability** — right concept, but neighbour export availability is neighbour
*residual demand/scarcity*, not neighbour wind CF alone; French nuclear and Norwegian hydro
(reservoir-level, slow) still export in a blocking high. f(neighbour wind) is too pessimistic
— fine as the parametric overlay, not as "observed." (e) **Pumped/reservoir hydro** specific
constraints — generic StorageUnit misses them; label it. (f) **Demand basis / embedded** —
critical, see §3. (g) **Losses** — ~8% gen-vs-demand gap; add a flat factor in v0 for
absolute-£ honesty. (h) **Dunkelflaute undefined** — threshold/duration/area/return-period
method all unspecified; with ~10–14 yrs you can't count a 1-in-20. Most attackable adequacy
claim in the document. Must define + cap claimed return periods.

## 3. Data realism

(a) **Embedded-generation / demand-basis trap (biggest data risk, unmentioned).** FUELHH is
transmission-only; embedded solar/wind (~16 GW rooftop) appears as suppressed demand. Naïve
use understates output *and* demand; errors don't cancel. Resolve in v0: reconstruct national/
end-user demand = TSD + embedded + losses; use embedded-inclusive output. The parent project
already solved this — port it. (b) **CF basis** — reanalysis CF is modelled, diverges 5–15%
from outturn; use outturn for historical replay, reanalysis only for synthetic years; match
numerator/denominator. (c) **Half-hourly vs hourly** — ELEXON/NESO HH, ENTSO-E/MERRA-2 hourly;
state the resampling rule; don't let interpolated hourly masquerade as HH truth. (d)
**Settlement vintage** — ELEXON revises II→SF→R1/R2/R3/RF; pin the run. (e) **ENTSO-E gaps** —
real coverage holes for exactly the series needed; prefer reanalysis for the physical
correlation, ENTSO-E for validation. (f) **DUKES annual nameplate** — within-year denominator
slightly wrong near commissioning; state it. (g) **CfD reference-price definition** — must
match the exact index or top-up accounting is wrong.

## 4. Validation — necessary, not sufficient

PyPSA-GB is **not ground truth** — a cross-check, never an oracle, never for storage. Outturn
parity must specify tolerances and metrics: annual energy by fuel; **price duration curve
shape** (the high-price tail, not the mean); monthly/seasonal/diurnal patterns; emissions vs
NESO. Additional gates: marginal-fuel split backtest (validate "bills track gas" directly);
energy-balance closure <1% on real replay; capture-price validation against published outturn;
adequacy vs NESO's published LOLE/de-rated margin; sensitivity bands as a release gate.

## 5. Scope recommendations (triaged)

**Must add to be credible:** demand-basis/embedded resolution (v0); gas-fleet internal merit
order + part-load heat rates + start costs (v0); Dunkelflaute definition + return-period
honesty (v0/v1); thermal de-rating/availability (v1); system reserve constraint with a sizing
rule (v1); foresight-honest storage + remove v0 storage headline (v1); validation gates 1–5
pre-committed (throughout); loss factor (v0). **Should add:** minimum-synchronous floor (v1);
B6 constraint + curtailment-payment accounting (pull from v2); neighbour availability driven by
residual/scarcity (v1); explicit counterfactual import treatment (v0). **Defer:** pumped-hydro
constraints (v2); full unit commitment (v2, provided simplified start costs in v0); stochastic
ensembles (v2, but need ≥10–14 replay years now); nodal network (v2).

**Bottom line.** The cost/price/settlement counterfactual genuinely can be made unimpeachable —
§12's high descriptive ceiling holds *there*. The spec overclaims for v0 in two places: §2's
storage number, and the unmentioned embedded/demand-basis trap. Fix the gas-fleet heat rate,
nail the demand basis, define the design event, pre-commit validation tolerances. Port the
parent project's hard-won knowledge deliberately.

---

# 2. Energy-system economist

**Headline judgement.** The spec is unusually self-aware (§12 is good discipline). But the
flagship economic claim — gas counterfactual vs the subsidised system — is, as specified, a
**variable-cost-only number masquerading as a system-cost comparison.** A hostile economist
dismantles the headline in one move: you compared the wind/solar system's full subsidised cost
against gas's fuel-and-carbon bill only, omitting gas's own capital, capacity, balancing and
carbon-risk costs. That asymmetry cuts against the sceptic's case as easily as for it.

## 1. Counterfactual correctness — the central problem

§8's `Σ MWh × (gas_price/efficiency + carbon × emission_factor)` is short-run marginal cost,
not system cost. Asymmetric four ways:

**1a. Variable-only vs all-in — the fatal asymmetry.** The wind side is charged CfD+RO
(capital recovery); the gas side only fuel+carbon+vO&M. "Renewables' capex+opex vs gas's
opex." Overstates gas's attractiveness (omits ~£40–60k/MW/yr fixed + ~£10–25/MWh capital).
Fix: compute both sides on an SRMC basis *and* a full-system basis, never mixed — two numbers,
"wholesale energy only" and "all-in resource cost", identical method both fleets.

**1b. The gas fleet is kept and paid for in the *actual* system too (the sceptic's strongest
honest point, currently missing).** Real system = renewables capex *plus* a near-full gas fleet
on Capacity-Market standby. Honest comparison: "gas" vs "wind + the gas you keep anyway." Net
retained-firm-capacity cost onto the renewables side — *more* damning *and* more honest.

**1c. Same `Σ MWh` is not the same service.** Real-system generation includes curtailed
overbuild and storage round-trip losses; an all-gas fleet meets demand with less total
generation. Specify: counterfactual meets *demand (load)*, not replicated generation; state
storage losses / curtailment / pumped-hydro in or out.

**1d. Carbon does huge contestable work.** ETS ~£35–75/t × ~0.18 t/MWh adds ~£6–14/MWh — but
the ETS *price* is a transfer (to Treasury), the *damage* (SCC) is the resource cost; the spec
conflates them. Including ETS loads gas with a policy tax (flatters renewables — opposite of
intent). Separate: gas cost excluding carbon; with ETS as transfer; optionally with SCC. State
which the headline uses, the price, and the year. **Rigged-both-ways risk:** against gas (load
ETS + 2022 gas price, credit renewables zero fuel); for gas (omit capex, omit SCC, ignore gas
price volatility). The model must show both framings or be accused of cherry-picking.

## 2. Subsidy accounting — materially incomplete

**2a. CfD reference-price circularity (real and serious).** Top-up = (strike − reference
price), reference price is gas-set, so the subsidy number depends on the assumed gas price; in
2022 CfDs paid *back*. The reference price must be the model's *own endogenous* gas-set price,
not an independent assumption. **2b. Capacity Market — absent** (~£1bn/yr; the mechanism that
pays the retained fleet in 1b). **2c. Constraint/curtailment payments — absent** (~£1bn/yr,
renewables-attributable; computed physically, never costed). **2d. BSUoS/balancing** rises with
renewable share — add a £/MWh adder. **2e. Embedded benefits** — flag out of scope explicitly.
**2f. RO** is more than buyout (ROCs × buyout + recycle), and is legacy/closed. **2g.** "Subsidy
vs wholesale" is **not** a bill (bills carry policy/network/margin too) — relabel.

## 3. Price-formation / market-rule experiments — meaningful but narrow

Legitimate: the *redistribution* (transfer) effect holding dispatch and bids fixed at cost
("under pay-as-clear, inframarginal generators earn this rent; under a split pool, renewables
capture it"); the mechanical "marginal price is gas-set." **3a. Pay-as-bid with cost=bid is
degenerate** — its whole content is that bidders shade offers; cost=bid shows it "saving money"
= the canonical wrong answer. Must caveat as an upper bound on savings. **3b. No investment
response** — settlement changes revenue → investment (missing money, why CfDs exist); fleet
fixed, so "split pool is cheaper" is a static illusion. State short-run-redistribution-only.
**3c. Nodal = "just a new PricingRule" is wrong** — LMP changes *dispatch*, collapses to one
price in copper-plate; needs the v2 network. Correct §5.

## 4. System-cost completeness

For an honest total: generation variable (have it); generation **capex annuity + fixed O&M**
(missing — must add); **retained firm/back-up (CM)** (must cost); **storage** capex+opex (must
cost, not just size); **curtailment/constraint** (must cost); **balancing/reserve/inertia**
(should cost); **network reinforcement** (omitted by copper-plate — must acknowledge; omission
*flatters renewables*); profile/utilisation cost via capture price (have it — the strongest
legitimate insight). System LCOE differs from plant LCOE mainly through profile, balancing,
grid and backup costs (the standard integration-cost buckets). A total with storage/backup
unpriced is "technically computed, economically misleading."

## 5. Scope additions (prioritised)

**Must add:** two-basis costing identical both fleets; endogenous internally-consistent
reference price; cost the retained firm fleet ("pay twice"); monetise storage/curtailment/
backup; separate carbon transfer vs resource cost (report with/without); relabel "bill"
honestly; frame settlement as short-run redistribution + pay-as-bid caveat + correct nodal
claim; mandatory provenance (price year / gas / carbon / basis) on every cost output.
**Nice to have:** gas-price *risk*/volatility distribution (bills spiked on variance, not
mean); discount-rate/WACC transparency (swings comparison 20%+); social cost of carbon;
network adder once v2 nodal exists; VALCOE decomposition in the waterfall.
**Most likely to embarrass:** SRMC-gas vs all-in-wind; subsidy reported without disclosing it
flips sign with gas price; "pay-as-bid saves £X" from cost=bid; "total system cost" with
backup/storage unpriced; any single-year (esp. 2022) presented as representative.

**Bottom line.** Architecture sound, §12 honesty excellent. The gap is in §8 (accounting) and
§5 (settlement claims): a variable-cost wholesale comparison labelled as system/bill, and an
exogenous reference price that is really endogenous. Fix MUST items 1–3 and the headline
becomes unimpeachable — and *more* damning of the built system (the pay-twice point) than the
current spec can express.

---

# 3. Game / Rust-wasm engine designer

**Verdict up front.** Macro-architecture is right — the pure-core/data/cli/scenario/wasm-game
split and the `run(&Scenario) -> Results` contract are the best decisions in the document.
Problems concentrate in four places: (a) determinism (§13) is asserted, not engineered, and
other choices threaten it; (b) the trait seams are partly premature and one is mis-cut; (c) the
game loop has an unaddressed batch-vs-interactive mismatch; (d) the v1 LP-in-browser is a
latent showstopper.

## 1. Architecture

Tighten the contract into types: `#![forbid(unsafe_code)]`; consider `no_std`-compatibility for
the dispatch kernel as a discipline tripwire; **seed lives in the scenario**, RNG =
`rand_chacha::ChaCha8Rng` (never `thread_rng`/OS/`StdRng`). Seams graded: **cost≠bid** — keep,
but `bid: Option<Bid>` (None ⇒ bid==cost) not two always-duplicated fields. **dispatch trait** —
keep at **per-step** granularity, never per-unit (7M+ vtable calls). **settlement** — strongly
keep; the best seam; earns its place in v0. **node-keyed** — keep the keying (NodeId newtype
over Vec), drop the graph/flow machinery until v2 (premature-abstraction trap). `Technology` is
under-modelled — storage/interconnector are structurally different (SOC; foreign node); keep
them sibling types, not a mega-enum with `unreachable!()` arms. **Versioning is the load-bearing
gap:** `schema_version` + `#[serde(deny_unknown_fields)]` + a migration path + a parse-corpus in
CI on both `Scenario` and `Results`; prefer **RON** (round-trips enums) over TOML; version
`Results` as a public API and snapshot the JSON shape; add a `RunManifest` (scenario hash +
data-version hashes + engine semver + seed + wall-clock) so reproducibility is mechanical.
Missing crate: `grid-sim-validate` for the parity work (heavy deps, feature-gated).

## 2. Determinism — asserted but not engineered

(1) **Float summation order** — `Σ` is not associative; iterate ordered collections only
(BTreeMap/IndexMap/Vec, never HashMap); never `par_iter().sum()` a float. (2) **wasm vs native
divergence will bite** — same `f64` differs last-ULP (x87/FMA); the CLI headline must match the
game. Forbid `mul_add`; set RUSTFLAGS consistently; accept cross-platform byte-identical isn't
guaranteed and pick: within-platform identical + cross-platform ULP tolerance, *or* fixed-point.
(3) **Fixed-point money** — `i64` minor units (or `Decimal`/`fixed`) for published £, `f64` for
physics; highest-leverage determinism decision, sidesteps cross-platform float for exactly the
contested numbers. (4) **LP nondeterminism (v1)** — degenerate problems → different optimal
vertices; flat-price periods give tied schedules; pin the solver, add a lexicographic tie-break,
snapshot + re-bless on bumps. Heuristic v0 is deterministic by construction — a real reason to
keep it the canonical published path. (5) **Scenario hashing** — can't hash `f64`; canonical-
serialise then hash bytes. Add a "Determinism contract" section stating platform scope, ordered-
collection rule, no-parallel-reduction rule, RNG, fixed-point money, LP tie-break.

## 3. The game shell — the hardest unsolved problem

The model is a batch 17,520-step annual run; the game wants real-time. **Lean JS/TS-over-wasm,
not egui:** it's a teaching artefact embedded in a web essay — must theme to the page, be share-
card/SEO friendly, degrade gracefully, support mobile text input and accessibility; egui's
opaque canvas fights all of that and balloons the bundle. egui only for a native debug UI.
Boundary data-only (`run(scenario_json) -> results_json`, typed via `serde-wasm-bindgen`/
`tsify`); never expose core types. **Resolve the mismatch with a two-phase model:** run-once →
get full SOC/dispatch/price series → animation is a cheap 60fps cursor over cached arrays;
only fleet/price/weather edits trigger a (debounced) recompute. **Mandate a Web Worker** so the
run never janks the DOM thread. Memoise by scenario hash. **Share via URL fragment** (versioned
RON/CBOR, deflate+base64) — essential, and why versioning isn't optional. State lives in the TS
shell (one scenario = source of truth); core stays stateless.

## 4. Performance & scale

The single run is sub-ms to low-ms — the spec over-worries it. Pressure is in **sweeps** (3-axis
= thousands of runs) and interactive recompute. **SoA** for the 17,520-length series (Vec<f64>
columns, cache-friendly, auto-vectorises); AoS fine for the small fleet. `smallvec` for the
per-step merit stack; reusable scratch buffers in a `RunContext`. **rayon at the sweep level,
never inside a run** (SOC is sequential; parallelising reintroduces float-order nondeterminism).
rayon doesn't work in wasm without `wasm-bindgen-rayon` + cross-origin isolation — so the game
gets single-threaded worker runs, the CLI gets rayon sweeps. **The v1 LP in-browser is a real
risk:** clarabel is pure-Rust (can target wasm) but inflates the bundle, is orders slower
(seconds/run → kills the loop), and is nondeterministic. Keep the LP out of the game entirely
(game ships the heuristic; LP is CLI/analysis only); if ever in-browser, use a rolling-horizon
(48–96h) formulation, not full-year.

## 5. Maintainability/extensibility & scope additions

**Must have:** schema versioning + migration + parse-corpus; the `RunManifest` provenance
object; **wasm CI** that diffs wasm vs native on a golden scenario (the only guard against
float divergence); property tests as invariants + `debug_assert!` (energy conservation is the
best net); centralised loud `GuardError`s (port grid-margin's `guards.py`). **Nice to have:**
`cargo-fuzz` on the deserialiser (promote to must-have before the public game accepts shared
URLs — untrusted input); criterion benchmarks gated in CI with a regression threshold; an
optional feature-gated `Trace`/event log (debugging + teaching animations); `thiserror` in core
/ `anyhow` in shells, core never panics (a wasm panic is an unrecoverable tab-killing trap);
extension via the existing traits, no dynamic plugin system; a `scenario migrate` CLI subcommand.
**Structural caution:** the bigger risk is *over*-engineering — don't build the node graph,
bidding-agent surface, or UC state in v0; leave the seams and nothing behind them; reject a v0 PR
that adds v2 abstraction.

**Top 6:** (1) write a determinism contract incl. fixed-point money; (2) version everything that
serialises + RunManifest; (3) split the storage optimiser by end-use (heuristic = canonical/game,
LP = CLI-only); (4) resolve the game batch/interactive mismatch (two-phase, Web Worker, JS-over-
wasm, scenario-in-URL); (5) wasm-vs-native CI diff; (6) re-cut two seams (`Option<Bid>`; storage/
interconnector as siblings; NodeId keying with no graph). The bones are good; the gap is making
determinism real and adding the engineering scaffolding the spec gestures at but doesn't mandate.
