// site/render.js — pure presentation helpers for the Grid Margin dashboard.
//
// No DOM, no network: just the maths that turns engine numbers into the gauge angle,
// the stripe's ink ramp, the gate-of-five tally and the display strings. Kept separate
// from app.js so it is unit-testable under `node --test` (render.test.mjs), alongside the
// verdict/live parity gates. These are display helpers, NOT parity-locked engine maths.

// --- the half-dial gauge ----------------------------------------------------

// Map a value in [0, max] onto a 180-degree dial: 0 -> -90 (left), max -> +90 (right),
// max/2 -> 0 (straight up). Out-of-range values clamp to the arc ends.
export function gaugeNeedleAngle(value, max) {
  const t = Math.min(1, Math.max(0, value / max));
  return -90 + t * 180;
}

// --- the reliability-stripe colour ramp ------------------------------------

// Reliability-stripe ramp. Firm-share domain, anchored to the gauge's 50% arming line: pale at the
// firm margin (>=hi), saturating to full red at/below the floor (<=lo). Single red ink, no green.
export const RELIABILITY_RAMP = { lo: 0.40, hi: 0.65 };
const _REL_PAPER = [251, 251, 249], _REL_RED = [214, 18, 31], _REL_GAP = [232, 232, 230];

// firm share s -> [r,g,b]. null -> gap grey (distinct from 0). s can exceed 1 on net-export
// half-hours -> clamps to the palest (most-reliable) end. The scale saturates at lo.
export function reliableShareToColor(s) {
  if (s == null) return _REL_GAP.slice();
  const { lo, hi } = RELIABILITY_RAMP;
  const t = Math.max(0, Math.min(1, (hi - s) / (hi - lo)));
  return [0, 1, 2].map((k) => Math.round(_REL_PAPER[k] + (_REL_RED[k] - _REL_PAPER[k]) * t));
}

export const rgbCss = ([r, g, b]) => `rgb(${r},${g},${b})`;

// Live "now" position on the unreliable-share key: 100 − firm, clamped to [0,100].
export function unreliableNowPct(firmPct) {
  return Number.isFinite(firmPct) ? Math.max(0, Math.min(100, 100 - firmPct)) : null;
}

// --- the gate-of-five failure tally ----------------------------------------

// --- the dependence gauge status -------------------------------------------

// The firm-power gauge reads how much of demand firm, dispatchable generation is meeting
// right now (gas + nuclear + biomass + other firm fuels). Two states: RELIABLE, or UNRELIABLE
// (armed red) when firm power runs low — the grid leaning hard on weather and imports, which
// fall away together in a calm. A fuel-gauge metaphor: low needle = running on empty.
export function firmStatus(firmPct) {
  const label = firmPct < 50 ? 'UNRELIABLE' : 'RELIABLE';
  return { label, armed: label === 'UNRELIABLE' };
}

// --- the capacity trap (static DUKES denominator) --------------------------

// Live wind+solar output as a share of DUKES total UK nameplate. Uses the DUKES
// figure (sound, dated, cited), NOT the live NESO embedded-wind capacity, which is
// embedded-only and would read ~146%. A static "% of installed" per engine/NOTES §2.
export function capacityTrapStatic(deliveringMw, builtGw) {
  const share = builtGw ? Math.round((deliveringMw / (builtGw * 1000)) * 1000) / 10 : 0;
  return { built_gw: builtGw, delivering_mw: deliveringMw, share_pct: share };
}

// Firm vs weather-&-imports shares for display. Prefers the engine's own firm_pct/
// notfirm_pct (parity-locked, round-half-even) when present; otherwise derives them from
// the always-present MW fields, so a pre-firm fallback latest.json still renders the cut
// instead of crashing.
export function firmShares(v) {
  const d = v.national_demand_mw;
  const firmMw = Number.isFinite(v.firm_mw) ? v.firm_mw
    : (v.gas_mw || 0) + (v.nuclear_mw || 0) + (v.biomass_mw || 0) + (v.other_mw || 0);
  const notfirmMw = Number.isFinite(v.notfirm_mw) ? v.notfirm_mw
    : (v.wind_mw || 0) + (v.solar_mw || 0) + (v.net_import_mw || 0);
  const pct = (mw) => (d ? Math.round((mw / d) * 1000) / 10 : 0);
  return {
    firm_mw: firmMw,
    notfirm_mw: notfirmMw,
    firm_pct: Number.isFinite(v.firm_pct) ? v.firm_pct : pct(firmMw),
    notfirm_pct: Number.isFinite(v.notfirm_pct) ? v.notfirm_pct : pct(notfirmMw),
  };
}

// --- the source-mix arc (the gauge) ----------------------------------------
// The gauge is a proportional arc on the SHARE-OF-DEMAND basis: the arc is 100% of national demand
// (what Britain consumes right now). One slice per source, length ∝ output — green-toned for the
// reliable (dispatchable, weather-independent) sources, red-toned for the unreliable (weather &
// imports). Imports are a slice when importing; on export the weather slices shrink to what served
// demand and the surplus becomes a magenta spill-over tail (exportMw). Only POSITIVE slices are
// drawn; a negative net flow (export) is the tail, never a slice. (The old "generating" basis —
// share of domestic generation — was removed; self-sufficiency is read off the import/export line.)
const ARC_RELIABLE = [
  ['gas', 'Gas', '#1b5e3f', (v) => v.gas_mw],
  ['nuclear', 'Nuclear', '#2e7d52', (v) => v.nuclear_mw],
  ['biofuel', 'Biofuel', '#4a9c73', (v) => v.biomass_mw],
  ['hydro', 'Hydro & other', '#79c1a0', (v) => v.other_mw],
];
const COL_WIND = '#1f6fc0';     // wind — the blue from Entry 02 (per-source identity, not red)
const COL_SOLAR = '#e0921a';    // solar — the yellow-orange from Entry 02
const COL_IMPORTS = '#c2188f';  // imports — magenta (interconnector flows)
export const COL_EXPORT = '#c2188f';   // magenta — surplus sent abroad (interconnector flows)

export function sourceArcModel(v) {
  const num = (x) => (Number.isFinite(x) ? x : 0);
  const reliable = ARC_RELIABLE.map(([key, label, color, get]) => ({
    key, label, color, group: 'reliable', mw: Math.max(0, num(get(v))),
  }));
  const firm = reliable.reduce((s, r) => s + r.mw, 0);
  const wind = Math.max(0, num(v.wind_mw));
  const solar = Math.max(0, num(v.solar_mw));
  const weather = wind + solar;
  const netImp = num(v.net_import_mw);
  const red = (key, label, color, mw) => ({ key, label, color, group: 'unreliable', mw });

  const arcTotal = num(v.national_demand_mw);        // the arc is national demand
  let firmServed; let slices; let exportMw = 0;

  if (netImp >= 0) {                                 // importing: imports is a real slice
    firmServed = firm;
    slices = [...reliable,
      red('wind', 'Wind', COL_WIND, wind),
      red('solar', 'Solar', COL_SOLAR, solar),
      red('imports', 'Imports', COL_IMPORTS, netImp)];
  } else {                                           // exporting: surplus is the tail, not a slice
    const exportTotal = -netImp;
    const exportFromWeather = Math.min(exportTotal, weather);     // exports come off the surplus
    const exportFromFirm = exportTotal - exportFromWeather;       // …then off firm (over-export)
    const weatherServed = weather - exportFromWeather;
    firmServed = firm - exportFromFirm;
    const fScale = firm > 0 ? firmServed / firm : 0;
    const wScale = weather > 0 ? weatherServed / weather : 0;
    slices = [
      ...reliable.map((r) => ({ ...r, mw: r.mw * fScale })),
      red('wind', 'Wind', COL_WIND, wind * wScale),
      red('solar', 'Solar', COL_SOLAR, solar * wScale)];
    exportMw = exportTotal;
  }
  const denom = arcTotal > 0 ? arcTotal : 1;
  return {
    slices: slices.map((s) => ({ ...s, frac: s.mw / denom })),
    arcTotal,
    firmPct: Math.round((firmServed / denom) * 1000) / 10,
    exportMw,
    selfSufficiencyMw: netImp,
  };
}

// --- live import-spend rate -------------------------------------------------

// Live import-spend rate: MW × £/MWh = £/hour. Export (net ≤ 0) → £0/h.
// Parity-locked to engine/build_site.py:import_block — the Python golden test
// asserts the same result for inputs (6890, 800) → 5512000 and (-500, 800) → 0.
export function importRatePerHour(netMw, pricePerMwh) {
  return Math.max(netMw, 0) * pricePerMwh;
}

// --- display formatting -----------------------------------------------------

export const fmtPct = (x) => (Number.isFinite(x) ? `${x.toFixed(1)}%` : '—');
export const fmtPct0 = (x) => (Number.isFinite(x) ? `${Math.round(x)}%` : '—');
export const fmtGW = (mw) => (Number.isFinite(mw) ? `${(mw / 1000).toFixed(1)} GW` : '—');
export const fmtMW = (mw) => (Number.isFinite(mw) ? `${Math.round(mw).toLocaleString('en-GB')} MW` : '—');

// --- the capacity-trap carpets + gauge calibration (Entry 02) ----------------
const _CARPET_PAPER = [251, 251, 249], _CARPET_FULL = [214, 18, 31], _CARPET_GAP = [232, 232, 230];

// sRGB <-> OKLab (Björn Ottosson, 2020). OKLab is a perceptually-uniform space: equal steps in its
// coordinates read as equal perceived steps, and a white->colour line holds a single hue (no detour
// through purple, the way a naive sRGB blend does). We interpolate the carpet/legend ramp here so an
// equal capacity-factor step is an equal perceived-density step. The CSS legend bar mirrors this with
// `linear-gradient(... in oklab, ...)`. See methodology.html #capacity-trap.
const _s2l = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const _l2s = (c) => { const v = c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055; return Math.max(0, Math.min(255, Math.round(v * 255))); };
function _srgbToOklab([r, g, b]) {
  const R = _s2l(r), G = _s2l(g), B = _s2l(b);
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s];
}
function _oklabToSrgb([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [_l2s(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
          _l2s(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
          _l2s(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)];
}

// One carpet cell: cf -> colour. White paper at 0 (no output), deepening to the saturated `full`
// colour at/above satFull (full output), interpolated in OKLab for a perceptually-uniform ramp.
// `full` is the per-source [r,g,b] (blue for wind, amber for solar); it defaults to the original red.
// The exact endpoints are returned verbatim (no OKLab round-trip drift). cf null -> neutral grey (a
// data gap, not an honest 0).
export function carpetCellColor(cf, satFull, full = _CARPET_FULL) {
  if (cf == null) return _CARPET_GAP.slice();
  const t = Math.max(0, Math.min(1, cf / satFull));  // 0 at no output (paper), 1 at full (saturated)
  if (t <= 0) return _CARPET_PAPER.slice();
  if (t >= 1) return full.slice();
  const A = _srgbToOklab(_CARPET_PAPER), B = _srgbToOklab(full);
  return _oklabToSrgb([0, 1, 2].map((k) => A[k] + (B[k] - A[k]) * t));
}

// Entry 03 wind carpet: cf -> colour. Windy (high CF) = pale paper; calm (CF->0) = deep red,
// OKLab-interpolated. INVERTED from the Entry 02 capacity carpet on purpose: here LOW output is
// the salient (red) end — the failures carry the ink. `windyAnchor` is the palest end (full wind).
const _WIND_PAPER = [251, 251, 249], _WIND_DEEP = [140, 12, 20], _WIND_GAP = [232, 232, 230];
export function windDroughtColor(cf, windyAnchor = 0.45) {
  if (cf == null) return _WIND_GAP.slice();
  const t = Math.max(0, Math.min(1, cf / windyAnchor));  // 0 at calm, 1 at windy
  if (t >= 1) return _WIND_PAPER.slice();
  if (t <= 0) return _WIND_DEEP.slice();
  const A = _srgbToOklab(_WIND_DEEP), B = _srgbToOklab(_WIND_PAPER);
  return _oklabToSrgb([0, 1, 2].map((k) => A[k] + (B[k] - A[k]) * t));
}

// The unreliability ramp (Entry 01 reliability block): a traffic-light gradient on the SHARED
// 0..1 scale used by the dial track, the carpet, and the legend bar. t=0 -> green (fully reliable),
// t=0.5 -> amber, t=1 -> red (fully unreliable), interpolated in OKLab so the midpoint reads as a
// true amber rather than the muddy brown a naive sRGB green->red blend would give. This is a
// CONTINUOUS gradient, NOT a threshold: amber is only the midpoint hue, never an arming line (the old
// thresholded 40%/65% stripe ramp was deliberately removed). Green = reliable / red = unreliable
// matches the verdict gauge directly above this block. null -> neutral gap grey.
const _RAMP_GREEN = [27, 110, 69], _RAMP_AMBER = [230, 160, 25], _RAMP_RED = [214, 18, 31];  // green #1b6e45 — the reliable green shared with the verdict gauge
export function unreliabilityColor(t) {
  if (t == null) return _CARPET_GAP.slice();
  t = Math.max(0, Math.min(1, t));
  const [lo, hi, k] = t <= 0.5
    ? [_RAMP_GREEN, _RAMP_AMBER, t / 0.5]
    : [_RAMP_AMBER, _RAMP_RED, (t - 0.5) / 0.5];
  if (k <= 0) return lo.slice();
  if (k >= 1) return hi.slice();
  const A = _srgbToOklab(lo), B = _srgbToOklab(hi);
  return _oklabToSrgb([0, 1, 2].map((i) => A[i] + (B[i] - A[i]) * k));
}

// The RELIABILITY ramp (Entry 01 block, the form actually shown): unreliabilityColor read from the
// other end so the dial reads firm/reliable share — t=0 (no firm power) -> red (the alarm), t=1 (all
// firm) -> green. Reversing here, not duplicating the OKLab maths, keeps the two ramps a single source
// of truth and guarantees the green/amber/red endpoints match the carpet's. null -> neutral gap grey.
export function reliabilityColor(t) {
  return unreliabilityColor(t == null ? null : 1 - t);
}

// The gauge tick model at 0/25/50/75/100%: dial fraction + the inner (%) and outer (MW) labels.
// 0% and 100% are always present; MW ends are 0 and the full nameplate.
export function gaugeCalibration(nameplateMw) {
  return [0, 25, 50, 75, 100].map((pct) => ({
    pct,
    frac: pct / 100,
    label_pct: `${pct}%`,
    label_mw: nameplateMw == null ? null : Math.round((nameplateMw * pct) / 100).toLocaleString('en-GB'),
  }));
}

// --- the drought-spike geometry helper (Entry 03) ----------------------------

// Entry 03 drought-spike geometry: each lull -> a vertical spike. x = its start date mapped onto
// the time axis; height ∝ duration; minor flags the frequent 1-day dips (drawn thin/pale so the
// multi-day towers dominate). Pure: the canvas shell paints these.
export function droughtSpikes(lulls, { x0ms, x1ms, w, h, maxDays }) {
  const span = Math.max(1, x1ms - x0ms);
  return lulls.map((l) => ({
    x: ((Date.parse(l.start) - x0ms) / span) * w,
    h: Math.max(0, Math.min(1, l.days / maxDays)) * h,
    minor: l.days < 2,
    severe: !!l.severe,
  }));
}

// --- the drought caption and carpet month helpers ----------------------------

const _MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

// Neutral plain-language caption for the drought plot (sceptic's voice, no catastrophising).
export function droughtCaption(summary) {
  const n = summary?.counts?.ge_3d ?? 0;
  const r = summary?.record_lull;
  if (!r) return 'No sustained calms on record.';
  const [y, m] = r.start.split('-');
  return `Since 2016 the wind has stayed below a tenth of capacity for three days or more on `
    + `${n} occasions — the longest ${r.days} days, ${_MONTHS[+m - 1]} ${y}.`;
}

// 12 month labels positioned by their first-of-month day-of-year fraction across a 366-day axis.
export function carpetMonthTicks() {
  const cum = [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];  // leap-year DOY of the 1st
  return cum.map((doy, i) => ({ label: _MONTHS[i][0], frac: doy / 366 }));
}

// --- the import-cost carpet + gauge helpers (Entry: imports) -----------------

// Import-cost carpet cell colour: cheap (£0) → pale paper, expensive (at/above cap) → deep red.
// sqrt-compressed so mid-range prices land in the visible portion of the ramp (not crowded at
// the cheap end). Reuses the wind drought constants — same paper/deep-red convention (red = bad).
// null → gap grey (distinct from £0).
export function importValueColor(value_gbp, capGbp = 10e6) {
  if (value_gbp == null) return _WIND_GAP.slice();
  const t = Math.sqrt(Math.min(Math.max(value_gbp, 0), capGbp) / capGbp);
  if (t <= 0) return _WIND_PAPER.slice();
  if (t >= 1) return _WIND_DEEP.slice();
  const A = _srgbToOklab(_WIND_PAPER), B = _srgbToOklab(_WIND_DEEP);
  return _oklabToSrgb([0, 1, 2].map((k) => A[k] + (B[k] - A[k]) * t));
}

// Import spend rate → gauge needle angle. Right = expensive. Wraps the shared half-dial maths.
export function importRateAngle(rate_per_h, capPerH = 5e6) {
  return gaugeNeedleAngle(rate_per_h, capPerH);
}

// Legend marks for the import-cost carpet key: low (£1m), mid (£5m) and the cap itself, so the
// top mark always lands at the red end (frac 1.0) whatever cap the engine emits — no mark can fall
// off the bar. frac uses the SAME sqrt transform as importValueColor, so the marks sit exactly
// where the colours do.
export function importLegendStops(capGbp) {
  return [1e6, 5e6, capGbp].map((v) => ({
    label: `£${Math.round(v / 1e6)}m`,
    frac: Math.sqrt(v / capGbp),
  }));
}

// Neutral sceptic's-voice caption for the import-cost panel (British spelling, no catastrophising).
export function importCostCaption(summary) {
  const w = summary?.worst_day;
  if (!w) return 'No import cost data on record.';
  const [y, m, d] = w.date.split('-');
  const mon = _MONTHS[+m - 1].slice(0, 3);
  const gbpm = (w.value_gbp / 1e6).toFixed(1);
  return `Since 2016 the costliest single day for imports was £${gbpm}m, on ${+d} ${mon} ${y}.`;
}
