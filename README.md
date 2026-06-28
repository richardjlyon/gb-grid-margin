# GB Grid Margin

**Live at [gridmargin.co.uk](https://gridmargin.co.uk).**

A live, public dashboard that reads Britain's electricity grid for **reliability** — not how
clean the power is, but whether you can count on it. In plain numbers: how much of the
country's electricity, at any moment, comes from firm, dispatchable power available whatever
the weather (gas, nuclear, biomass), and how much leans on wind, solar and imports — the
sources that fall away together when a cold, still spell settles over north-west Europe.

GB Grid Margin is built on one rule: **every figure traces to a public Elexon, NESO or DUKES
dataset and can be checked.** The data sources, the formulas and the code are all open. No
figure on the site is modelled — each one is measured.

A companion to *The Energy Trap*, and sibling to the [Subsidy Clock](https://subsidyclock.co.uk):
the Clock measures the cost of energy policy; this measures the risk.

## How it works (hybrid)

- **History layer (daily).** A scheduled job pulls settled half-hourly generation (FUELHH),
  interconnector flows and demand after Elexon publishes them, appends to a committed
  data store, recomputes the derived series, and writes static JSON the site reads.
- **Live layer (in-browser, ~5 min).** The page fetches the latest 5-minute generation
  snapshot (FUELINST), demand and interconnector flows directly from Elexon and renders the
  live figures. A build-written `latest.json` is the fallback.

### Direct browser fetch

Elexon's BMRS Insights API (`data.elexon.co.uk`) sends `Access-Control-Allow-Origin: *` and
permits CORS preflight, so the live layer fetches Elexon directly from the browser — no proxy.

## Layout

```
engine/        Python data engine (retrieval, compute, site-data build)
engine/NOTES.md  Methodology decisions and known limitations
site/          Static dashboard (no framework, no bundler)
site/data/     Build-written JSON consumed by the site
data/          Committed reference data (capacity figures, append-only store)
tests/         Engine tests (methodology guards, feed-boundary models)
```

## Running

The engine is a [uv](https://docs.astral.sh/uv/) project. From the repo root:

```
uv sync                                   # create the environment
uv run python -m engine.grid_engine       # print the live verdict
uv run python -m engine.history append    # append newly-settled half-hours to the store
uv run python -m engine.history validate  # check the store (counts, gaps, duplicates)
uv run pytest                             # run the tests
```

The settled history store lives in `data/history/` (`fuelhh_YYYY.csv`, wide, one row per
half-hour, back to 2016-01-01 — the Elexon clean-data edge). `known_gaps.csv` is the frozen
record of half-hours Elexon never published; `validate` passes on those but fails on any new gap.

## Data sources

- **FUELINST** — 5-minute transmission generation by fuel type (live layer).
- **FUELHH** — settled half-hourly generation by fuel type (history layer).
- **Interconnectors** — the `INT*` fuel types (net import/export flows).
- **Capacity (nameplate)** — installed wind and solar capacity from DUKES 2025 (Table 6.2,
  UK), used as the denominator for capacity-factor figures. The end-2024 anchor (live layer) is
  in `data/nameplate.json`; the 2009–2024 annual series (historical capacity factors, applied
  annual-step) is in `data/nameplate_series.json`. Cited and dated.
- **Solar** — not present in FUELINST (embedded solar is netted off demand). The published
  figure is NESO's embedded estimate, cross-checked at build time against Sheffield Solar
  PV_Live. See `engine/NOTES.md`.

## Methodology and provenance

Each published figure carries a source line and a "last updated" timestamp. The formulas and
their datasets are documented in `engine/NOTES.md` and on the site's methodology page.
Build-time checks reject implausible values so a bad pull fails loudly rather than publishing
silently.

## Status

The dashboard and engine are built and tested: three sections — the reliability gauge, the
capacity trap, and wind unreliability — on the live and settled layers, with a full
methodology page. Continuous deployment (a scheduled refresh job plus hosting) is the
remaining piece before launch. Open methodology decisions are tracked in `engine/NOTES.md`.

## Licence

- **Code** — [MIT](LICENSE). Use it freely.
- **Derived figures and series** (the JSON this project computes and publishes) — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): reuse with attribution to GB Grid Margin.
- **Raw data** — Elexon (BMRS), NESO and DUKES remain under their own terms; this project does not relicense them.
