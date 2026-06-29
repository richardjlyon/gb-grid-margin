"""Provenance registry — the single author of every figure's source + basis + caveats.

Provenance (which feeds a figure, the formula in words, the disclosed caveats) used to be
triplicated across the engine payloads, hardcoded strings in `site/app.js`, and prose in
`site/methodology.html` / `engine/NOTES.md` — and it drifted. This module is the one place that
authorship lives. The engine already computes the real bases, so it OWNS the registry; a
hand-maintained file would just relocate the drift.

`engine.derived.build` emits `build_payload(generated_utc)` to `site/data/sources.json`. From there:
  * the methodology page's per-metric source cards are GENERATED (engine.methodology),
  * the front page links to each section's method anchor (no per-figure source prose), and
  * a build gate (tests/test_provenance_gate.py) asserts every on-page metric ID has an entry here,
    so no bare figure can ship.

Keep this MINIMAL: ~12 flat entries keyed by stable ID, NOT a generic CMS. Each unit carries the
feeds (name + url), the basis (formula in words), a cadence ("live" | "settled" — drives the
front-page "settled" tag, replacing seam prose), a section (groups units under a homepage method
anchor), the disclosed caveats, and the methodology anchor it renders under.
"""

from __future__ import annotations

import copy

from engine.guards import require

# Sections group units under a homepage panel + its method anchor, and each maps to a front-page
# "Sources & method →" link: reliability (§01), wind + solar (§02, two distinct groups), imports (§03).
# `warnings` is the GRID WARNINGS rail (no front-page link of its own).
ALLOWED_SECTIONS = {"reliability", "wind", "solar", "imports", "warnings"}
ALLOWED_CADENCES = {"live", "settled"}

# --- canonical feeds (named once, referenced by id) -------------------------
_ELEXON_FUELINST = {"name": "Elexon FUELINST (live)",
                    "url": "https://bmrs.elexon.co.uk/generation-by-fuel-type"}
_ELEXON_FUELHH = {"name": "Elexon FUELHH (settled)",
                  "url": "https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH"}
_ELEXON_SYSPRICE = {"name": "Elexon system (cash-out) price",
                    "url": "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices"}
_ELEXON_SYSWARN = {"name": "Elexon SYSWARN (active notices)",
                   "url": "https://data.elexon.co.uk/bmrs/api/v1/system/warnings"}
_NESO_EMBEDDED_FORECAST = {"name": "NESO embedded wind & solar forecast",
                           "url": "https://www.neso.energy/data-portal/embedded-wind-and-solar-forecasts"}
_NESO_HISTORIC_DEMAND = {"name": "NESO Historic Demand Data (embedded outturn)",
                         "url": "https://www.neso.energy/data-portal/historic-demand-data"}
_DUKES_62 = {"name": "DUKES 2025, Table 6.2 (UK nameplate, end-2024)",
             "url": "https://www.gov.uk/government/statistical-data-sets/dukes-renewable-sources-of-energy-chapter-6"}
_DESNZ_INTERCONNECTORS = {"name": "DESNZ GB interconnector capacity",
                          "url": "https://www.gov.uk/government/publications/next-steps-for-electricity-interconnection-in-great-britain/next-steps-for-electricity-interconnection-in-great-britain-accessible-webpage"}
_PV_LIVE = {"name": "Sheffield Solar PV_Live (cross-check)",
            "url": "https://www.solar.sheffield.ac.uk"}


# --- the registry (the single author) ---------------------------------------
# id -> unit. The basis strings mirror the payload `basis`/`source` fields (engine/derived.py and
# the per-metric modules) so the registry reads as their canonical home, not a second copy to drift.
REGISTRY: dict[str, dict] = {
    "verdict": {
        "label": "Reliability gauge (live)",
        "section": "reliability",
        "cadence": "live",
        "method_anchor": "verdict",
        "feeds": [_ELEXON_FUELINST, _NESO_EMBEDDED_FORECAST],
        "basis": ("Firm (reliable) share of national demand = (gas + nuclear + biomass + other firm) "
                  "÷ national demand, recomputed live in the browser by the same parity-locked formula "
                  "as the build. Wind, solar and net interconnector imports are the weather-and-imports "
                  "(correlated-failure) bucket."),
        "caveats": [
            "A 5-minute snapshot. 'Weather & imports' classifies by what is firm when the continent "
            "is also becalmed — not a claim those megawatts are absent right now.",
        ],
    },
    "reliability-carpet": {
        "label": "Reliability strip (settled, per half-hour)",
        "section": "reliability",
        "cadence": "settled",
        "method_anchor": "reliability",
        "feeds": [_ELEXON_FUELHH, _NESO_HISTORIC_DEMAND, _PV_LIVE],
        "basis": ("Reliable (firm) share of demand per half-hour, by the same parity-locked formula as "
                  "the live gauge (engine.grid_engine.compute_verdict), over the rolling 365 settled "
                  "days. Net-export half-hours clamp to 100% reliable, matching the live dial."),
        "caveats": [
            "The firm fuels are settled Elexon FUELHH; the embedded solar/wind are NESO's modelled "
            "outturn estimates, not metered — a mixed metered+estimated layer, disclosed.",
            "Live gauge reads NESO's embedded forecast; the carpet reads settled outturn ~3 weeks "
            "behind — the same measure, a forecast-vs-settlement seam.",
        ],
    },
    "wind-dial": {
        "label": "Wind dial (live)",
        "section": "wind",
        "cadence": "live",
        "method_anchor": "capacity-trap",
        "feeds": [_ELEXON_FUELINST, _NESO_EMBEDDED_FORECAST, _DUKES_62],
        "basis": ("Live wind capacity factor = live wind output (Elexon FUELINST + NESO embedded "
                  "forecast) ÷ DUKES total UK wind nameplate."),
        "caveats": [],
    },
    "wind-carpet": {
        "label": "Wind strip (settled, per half-hour)",
        "section": "wind",
        "cadence": "settled",
        "method_anchor": "capacity-trap",
        "feeds": [_ELEXON_FUELHH, _NESO_HISTORIC_DEMAND, _DUKES_62],
        "basis": ("Wind capacity factor per half-hour = (transmission WIND [Elexon FUELHH] + embedded "
                  "wind [NESO outturn]) ÷ DUKES total UK wind nameplate (annual-step) — a true load "
                  "factor, no cross-year artifact."),
        "caveats": [
            "Live gauge reads NESO's embedded forecast; the carpet reads settled outturn ~3 weeks "
            "behind — a forecast-vs-settlement seam.",
        ],
    },
    "solar-dial": {
        "label": "Solar dial (live)",
        "section": "solar",
        "cadence": "live",
        "method_anchor": "capacity-trap",
        "feeds": [_NESO_EMBEDDED_FORECAST],
        "basis": ("Live solar capacity factor = NESO embedded solar forecast ÷ NESO embedded-solar "
                  "capacity (contemporaneous, GB, DC/MWp) — numerator and denominator from the same "
                  "NESO embedded series."),
        "caveats": [],
    },
    "solar-carpet": {
        "label": "Solar strip (settled, per half-hour)",
        "section": "solar",
        "cadence": "settled",
        "method_anchor": "capacity-trap",
        "feeds": [_NESO_HISTORIC_DEMAND],
        "basis": ("Solar capacity factor per half-hour = embedded solar (NESO outturn) ÷ NESO "
                  "embedded-solar capacity (contemporaneous, GB/DC). Night cells are a genuine zero, "
                  "not a gap."),
        "caveats": [
            "A DUKES solar figure would mismatch (UK not GB, AC-equivalent not DC); the NESO "
            "embedded-solar capacity is the methodology-correct denominator.",
        ],
    },
    "wind-unreliability": {
        "label": "Wind drought — whole-record carpet & lulls (wind detail)",
        "section": "wind",
        "cadence": "settled",
        "method_anchor": "wind-unreliability",
        "feeds": [_ELEXON_FUELHH, _NESO_HISTORIC_DEMAND, _DUKES_62],
        "basis": ("Daily wind capacity factor = mean power of (transmission WIND [Elexon FUELHH] + "
                  "embedded wind [NESO outturn]) ÷ DUKES total UK wind nameplate (annual-step), back to "
                  "2016. A lull is a run of consecutive days below 10%; severe if it touches below 5%."),
        "caveats": [
            "Combined-basis figures supersede the former transmission-only lower bound; cached share "
            "images may show the higher old numbers.",
        ],
    },
    "import-power": {
        "label": "Imports — capacity-factor panel (live needle, settled strip)",
        "section": "imports",
        "cadence": "settled",
        "method_anchor": "import-cost",
        "feeds": [_ELEXON_FUELINST, _ELEXON_FUELHH, _DESNZ_INTERCONNECTORS],
        "basis": ("Net imports as a share of GB interconnector capacity per half-hour = "
                  "max(net interconnector inflow, 0) ÷ the capacity of the legs reporting that "
                  "half-hour. The live needle is the same net-import figure as the verdict gauge; "
                  "export half-hours floor to zero."),
        "caveats": [],
    },
    "import-cost": {
        "label": "Imports — £ cost (import detail page)",
        "section": "imports",
        "cadence": "settled",
        "method_anchor": "import-cost",
        "feeds": [_ELEXON_FUELHH, _ELEXON_SYSPRICE],
        "basis": ("Daily GB net import value = Σ over settled half-hours of "
                  "max(net interconnector inflow, 0) × ½h × GB system sell price (floored at £0). "
                  "Back to 2016."),
        "caveats": [
            "Net imported energy valued at the GB system (cash-out) price — NOT the contractual cost "
            "of the imports, which clear in the day-ahead auction. No licensed price series is used.",
        ],
    },
    "overcast": {
        "label": "OVERCAST lamp (conditional solar)",
        "section": "warnings",
        "cadence": "live",
        "method_anchor": "conditions",
        "feeds": [_NESO_EMBEDDED_FORECAST, _NESO_HISTORIC_DEMAND],
        "basis": ("Amber when live solar capacity factor falls below the 25th percentile of comparable "
                  "half-hours, conditioned on (week-of-year, settlement period) so the diurnal+seasonal "
                  "cycle does not swamp it. Readout = live CF ÷ that slot's clear-sky (P95) ceiling, "
                  "'X% of a clear day'; after dark the lamp is dormant."),
        "caveats": [
            "Live lamp reads NESO's embedded forecast; the distribution is settled outturn — a "
            "forecast-vs-settlement seam.",
        ],
    },
    "warnings": {
        "label": "SCARCITY NOTICE — operational warnings (live)",
        "section": "warnings",
        "cadence": "live",
        "method_anchor": "warnings",
        "feeds": [_ELEXON_SYSWARN],
        "basis": ("Red while NESO has at least one active margin notice on Elexon SYSWARN. Three-tier "
                  "scarcity ladder, most to least severe: NISM (Notice of Insufficient System Margin), "
                  "EMN (Electricity Margin Notice), CMN (Capacity Market Notice). The only authoritative "
                  "lamp."),
        "caveats": [
            "A margin notice means the buffer is thin — the operator asking the market for more with "
            "hours of warning — not that the lights are going out.",
        ],
    },
    "lamps-computed": {
        "label": "Computed lamps — UNRELIABLE · WIND LULL · HEAVY IMPORTS",
        "section": "warnings",
        "cadence": "live",
        "method_anchor": "conditions",
        "feeds": [_ELEXON_FUELINST, _NESO_EMBEDDED_FORECAST, _DESNZ_INTERCONNECTORS, _DUKES_62],
        "basis": ("Each computed lamp goes amber when the live reading leaves the usual half — the "
                  "P25–P75 box of that panel's own rolling-year distribution — on the concerning side: "
                  "UNRELIABLE when firm share < P25, WIND LULL when wind CF < P25, HEAVY IMPORTS when "
                  "import share of capacity > P75. The rail reads in one language: each active lamp "
                  "shows its source's share of national demand (the verdict-receipt basis), even where "
                  "it trips on a different distribution. The threshold is the box-plot beside the panel."),
        "caveats": [
            "The amber lamps are this site's own reading of live conditions, not an official statement "
            "of system state. Only the red SCARCITY NOTICE carries an authoritative NESO source.",
        ],
    },
}


def build_payload(generated_utc: str) -> dict:
    """The registry as an emittable payload. A deep copy so callers can't mutate the module dict."""
    return {"generated_utc": generated_utc, "units": copy.deepcopy(REGISTRY)}


def guard_payload(payload: dict) -> None:
    """Fail the build loudly if any unit is malformed — no bare figure ships.

    Every unit must carry feeds (each with a name + http url), a basis, a cadence in the allowed
    set, and a section in the allowed set. caveats must be a list (it may be empty).
    """
    require(payload.get("generated_utc"), "sources payload missing generated_utc")
    units = payload.get("units")
    require(isinstance(units, dict) and units, "sources payload has no units")
    for uid, u in units.items():
        require(u.get("label"), f"source unit {uid!r} missing label")
        require(u.get("basis"), f"source unit {uid!r} missing basis")
        require(u.get("section") in ALLOWED_SECTIONS,
                f"source unit {uid!r} bad section {u.get('section')!r} "
                f"(expected one of {sorted(ALLOWED_SECTIONS)})")
        require(u.get("cadence") in ALLOWED_CADENCES,
                f"source unit {uid!r} bad cadence {u.get('cadence')!r} "
                f"(expected one of {sorted(ALLOWED_CADENCES)})")
        require(u.get("method_anchor"), f"source unit {uid!r} missing method_anchor")
        require(isinstance(u.get("caveats"), list), f"source unit {uid!r} caveats must be a list")
        feeds = u.get("feeds")
        require(isinstance(feeds, list) and feeds, f"source unit {uid!r} has no feeds")
        for feed in feeds:
            require(feed.get("name"), f"source unit {uid!r} has a feed with no name")
            require(str(feed.get("url", "")).startswith("http"),
                    f"source unit {uid!r} feed {feed.get('name')!r} has no url")
