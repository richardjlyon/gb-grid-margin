// site/conditions.js — pure lamp logic for the GRID CONDITIONS rail.
//
// No DOM, no network. Each function maps already-fetched live data to a lamp render-state, so it is
// unit-testable under `node --test` (conditions.test.mjs) and the rail can never drift from source.
//
// SITE POLICY (the panel's contract): a lamp goes AMBER when the live reading leaves the "usual half"
// — the IQR box (P25–P75) of that panel's rolling-year distribution — on the concerning side. The
// threshold percentile is PASSED IN, read live from the same box-plot the panel draws, so a lamp can
// never disagree with the box beside it; there are no hand-picked constants. Concerning side depends
// on the metric: for wind CF and firm share a LOW reading is the worry (< P25); for imports a HIGH
// reading is the worry (> P75). See engine/NOTES.md §16 and [[grid-conditions-lamp-policy]].

// Wind lull: lights on the LIVE wind capacity factor — the SAME number as the Entry-02 dial (live
// wind output / DUKES total wind nameplate), against the P25 of that dial's box-plot. Below the usual
// half = becalmed right now. A settled run-count can't be live (complete FUELHH settles ~5 days late),
// so the lull-*duration* story lives in the wind detail page; the lamp reports the live reading only.
export function windLullLamp(cfPct, p25) {
  if (!Number.isFinite(cfPct) || !Number.isFinite(p25)) return { state: 'unavailable' };
  return { state: cfPct < p25 ? 'active' : 'nominal', cfPct };
}

// Unreliable grid: lights when the live FIRM share — reliable dispatchable power (gas + nuclear +
// biomass + other firm); imports are NOT firm — drops below the P25 of the Entry-01 reliability
// box-plot. Firm is in its worst quarter of the year, so weather + imports are carrying an unusually
// large share of demand. The lamp displays the UNRELIABLE share (100 − firm) so its number rises with
// the alarm; the trip logic here stays in firm terms to match the firm-share distribution.
export function firmMajorityLamp(firmPct, p25) {
  if (!Number.isFinite(firmPct) || !Number.isFinite(p25)) return { state: 'unavailable' };
  return { state: firmPct < p25 ? 'active' : 'nominal', firmPct };
}

// Heavy imports: lights when live net imports as a share of interconnector capacity — the SAME figure
// the Entry-03 dial points to — exceed the P75 of that panel's box-plot (above the usual half: the
// cables are working harder than they do in a typical hour). `importPct` is signed: an export hour is
// negative and so never trips, and the value is carried through so the status line can read "X% export".
export function heavyImportsLamp(importPct, p75) {
  if (!Number.isFinite(importPct) || !Number.isFinite(p75)) return { state: 'unavailable' };
  return { state: importPct > p75 ? 'active' : 'nominal', pct: importPct };
}

// Overcast: solar is a special case — a flat capacity-factor threshold is meaningless because the
// diurnal + seasonal cycles swamp it, so the distribution is CONDITIONED on solar geometry. `cell` =
// [p25, ceiling] of the live (week-of-year, settlement-period) slot from solar_overcast.json, or null
// for a night / low-sun slot (a daytime-only instrument). Relative trip: live solar CF below the
// slot's p25 = cloudier than three-quarters of comparable half-hours. The readout is the empirical
// clear-sky index — live CF / ceiling (P95, "about as clear as this slot gets") — clamped to [0,1]
// because cloud-edge over-irradiance can briefly push real output past the ceiling. See NOTES §16.
export function overcastLamp(cfNow, cell) {
  if (!cell) return { state: 'dark' };
  if (!Number.isFinite(cfNow)) return { state: 'unavailable' };
  const [p25, ceiling] = cell;
  const clearFrac = ceiling > 0 ? Math.max(0, Math.min(1, cfNow / ceiling)) : null;
  return { state: cfNow < p25 ? 'active' : 'nominal', cfNow, clearFrac };
}

// Both notices share the one authoritative red; EMN vs CMN is told apart by SHAPE, not colour. EMN
// (the headline) is the default filled dot; CMN is a hollow red ring. Returns the CSS class to add
// for the ring form, or '' for the filled default. Colour-intensity distinction was imperceptible at
// lamp scale — shape is legible.
export function scarcityShapeClass(type) {
  return type === 'CMN' ? 'scarcity-cmn' : '';
}

// The official guest. Active state is 'in_force' (one authoritative red for both EMN and CMN — the
// status text names which notice it is), all-clear is 'clear'. Mirrors resolveWarnings(). The
// usual-half rule does NOT apply: this is the authoritative NESO SYSWARN notice, not a computed band.
export function scarcityLamp(warn) {
  if (!warn || !warn.status || warn.status === 'unavailable') return { state: 'unavailable' };
  if (warn.status === 'in_force') return { state: 'in_force', type: warn.type, label: warn.typeLabel };
  return { state: 'clear' };
}
