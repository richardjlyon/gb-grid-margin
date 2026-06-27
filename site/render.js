// site/render.js — pure presentation helpers for the Grid Gauge dashboard.
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

// --- the wind stripe colour ramp -------------------------------------------

const _INK = [0x15, 0x18, 0x1c];      // calm day: the dark band
const _SOFT = [0xea, 0xec, 0xee];     // windy day: dissolves toward the paper
const _CF_FULL = 0.45;                // CF at/above which a day is the palest end

const _hex2 = (n) => n.toString(16).padStart(2, '0');

// Single-hue ink ramp: low CF (calm, the danger) -> dark ink; high CF -> soft paper.
// Deliberately monochrome — "the wind rarely blows" is read off the dark texture, with
// no y-axis. Red lives only on the foot-tick rail (failing days), never in the band.
export function cfToInk(cf) {
  const t = Math.min(1, Math.max(0, cf / _CF_FULL));
  const ch = (i) => Math.round(_INK[i] + t * (_SOFT[i] - _INK[i]));
  return `#${_hex2(ch(0))}${_hex2(ch(1))}${_hex2(ch(2))}`;
}

// --- the gate-of-five failure tally ----------------------------------------

// Break a day count into gate-of-five groups for the self-writing tally.
export function tallyGroups(n) {
  const out = [];
  let left = n;
  while (left >= 5) { out.push(5); left -= 5; }
  if (left > 0) out.push(left);
  return out;
}

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

// --- reliability stripe: binning + axis-tick maths --------------------------

const _REL_MON = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

export function binSeriesToColumns(values, nCols) {
  const n = values.length, out = new Array(nCols);
  for (let c = 0; c < nCols; c++) {
    const i0 = Math.floor((c / nCols) * n), i1 = Math.max(i0 + 1, Math.floor(((c + 1) / nCols) * n));
    let sum = 0, cnt = 0;
    for (let i = i0; i < i1 && i < n; i++) { if (values[i] != null) { sum += values[i]; cnt++; } }
    out[c] = cnt ? sum / cnt : null;
  }
  return out;
}

// Tick positions as fractions across the series. 'rolling' -> month + year ticks; 'all' -> years only.
export function reliabilityAxisTicks(startMs, stepMs, n, mode = 'rolling') {
  const months = [], years = [];
  let lastYr = null;
  for (let i = 0; i < n; i++) {
    const d = new Date(startMs + i * stepMs);
    const firstOfMonth = d.getUTCDate() === 1 && d.getUTCHours() === 0 && d.getUTCMinutes() === 0;
    if (i === 0 || firstOfMonth) {
      const frac = i / n;
      if (mode === 'rolling') months.push({ frac, label: _REL_MON[d.getUTCMonth()] });
      if (d.getUTCFullYear() !== lastYr) { lastYr = d.getUTCFullYear(); years.push({ frac, label: String(d.getUTCFullYear()) }); }
    }
  }
  return { months, years };
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

// The gauge tick model at 0/25/50/75/100%: dial fraction + the inner (%) and outer (MW) labels.
// 0% and 100% are always present; MW ends are 0 and the full nameplate.
export function gaugeCalibration(nameplateMw) {
  return [0, 25, 50, 75, 100].map((pct) => ({
    pct,
    frac: pct / 100,
    label_pct: `${pct}%`,
    label_mw: Math.round((nameplateMw * pct) / 100).toLocaleString('en-GB'),
  }));
}
