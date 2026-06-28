# GB Grid Margin

**Live at [gridmargin.co.uk](https://gridmargin.co.uk).**

A live, public dashboard of Britain's electricity system. It shows, in plain numbers, how
much of the country's power comes from wind and solar at any moment, how much from gas and
imported electricity, and how close the system runs to its operational limits.

GB Grid Margin is built on one rule: **every figure traces to a public Elexon or NESO dataset and
can be checked.** The data sources, the formulas and the code are all open. No figure on the
site is modelled — each one is measured.

A companion to *The Energy Trap*.

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
their datasets are documented in `engine/NOTES.md` (and, once the site ships, on a methodology
page). Build-time checks reject implausible values so a bad pull fails loudly rather than
publishing silently.

## Status

Early build. CORS settled; the live verdict and capacity-share pipeline run against real
FUELINST data. Open methodology decisions are tracked in `engine/NOTES.md`.

## Licence

TBC.
