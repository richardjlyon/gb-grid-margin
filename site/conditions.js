// site/conditions.js — pure lamp logic for the GRID CONDITIONS rail.
//
// No DOM, no network. Each function maps already-fetched live data to a lamp render-state, so it is
// unit-testable under `node --test` (conditions.test.mjs) and the rail can never drift from source.
// Thresholds are the panel's contract; every lamp reads the same live figures the dashboard shows.

export const WIND_LULL_PCT = 25;       // live wind capacity factor below this => a lull right now
export const FIRM_MAJORITY_PCT = 50;   // firm share below this => weather+imports are the majority
export const HEAVY_IMPORT_PCT = 25;    // net imports above this share of demand => heavy reliance

// Wind lull: lights on the LIVE wind capacity factor — the SAME number as the Entry-02 dial
// (live wind output / DUKES total wind nameplate). Below the line = becalmed right now. A settled
// run-count can't be live (complete FUELHH settles ~5 days late), so the lull-*duration* story lives
// in Entry 03; the lamp reports the live reading only and so never disagrees with the dial below it.
export function windLullLamp(cfPct) {
  if (!Number.isFinite(cfPct)) return { state: 'unavailable' };
  return { state: cfPct < WIND_LULL_PCT ? 'active' : 'nominal', cfPct };
}

export function firmMajorityLamp(firmPct) {
  if (!Number.isFinite(firmPct)) return { state: 'unavailable' };
  return { state: firmPct < FIRM_MAJORITY_PCT ? 'active' : 'nominal', firmPct };
}

export function heavyImportsLamp(netImportMw, demandMw) {
  if (!Number.isFinite(netImportMw) || !Number.isFinite(demandMw) || demandMw <= 0) {
    return { state: 'unavailable' };
  }
  const pct = (netImportMw / demandMw) * 100;
  return { state: pct > HEAVY_IMPORT_PCT ? 'active' : 'nominal', pct };
}

// The official guest. Active state is 'in_force' (red), all-clear is 'clear'. Mirrors resolveWarnings().
export function scarcityLamp(warn) {
  if (!warn || !warn.status || warn.status === 'unavailable') return { state: 'unavailable' };
  if (warn.status === 'in_force') return { state: 'in_force', type: warn.type, label: warn.typeLabel };
  return { state: 'clear' };
}
