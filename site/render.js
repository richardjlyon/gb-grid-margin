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

// The gauge arms to red only when a figure genuinely fails: gas+imports in the
// DEPENDENT band (>40% of demand) OR wind below 10% of capacity. Restraint is the
// credibility — on a calm sunny midday the needle stays ink.
export function dependenceStatus(gasImportsPct, windBelow10) {
  const label = gasImportsPct > 40 ? 'DEPENDENT' : gasImportsPct >= 30 ? 'ELEVATED' : 'NOMINAL';
  return { label, armed: label === 'DEPENDENT' || windBelow10 };
}

// --- the capacity trap (static DUKES denominator) --------------------------

// Live wind+solar output as a share of DUKES total UK nameplate. Uses the DUKES
// figure (sound, dated, cited), NOT the live NESO embedded-wind capacity, which is
// embedded-only and would read ~146%. A static "% of installed" per engine/NOTES §2.
export function capacityTrapStatic(deliveringMw, builtGw) {
  const share = builtGw ? Math.round((deliveringMw / (builtGw * 1000)) * 1000) / 10 : 0;
  return { built_gw: builtGw, delivering_mw: deliveringMw, share_pct: share };
}

// How many times the gas fleet out-produces the whole wind fleet, to one decimal.
// Null when wind is zero (no defensible multiple), so the card omits the figure.
export function gasVsWindMultiple(gasMw, windMw) {
  return windMw > 0 ? Math.round((gasMw / windMw) * 10) / 10 : null;
}

// --- display formatting -----------------------------------------------------

export const fmtPct = (x) => (Number.isFinite(x) ? `${x.toFixed(1)}%` : '—');
export const fmtGW = (mw) => (Number.isFinite(mw) ? `${(mw / 1000).toFixed(1)} GW` : '—');
export const fmtMW = (mw) => (Number.isFinite(mw) ? `${Math.round(mw).toLocaleString('en-GB')} MW` : '—');
