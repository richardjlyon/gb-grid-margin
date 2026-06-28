// site/conditions.js — pure lamp logic for the GRID CONDITIONS rail.
//
// No DOM, no network. Each function maps already-fetched live data to a lamp render-state, so it is
// unit-testable under `node --test` (conditions.test.mjs) and the rail can never drift from source.
// Thresholds are the panel's contract; the wind run is precomputed server-side (wind_live_run.json).

export const FIRM_MAJORITY_PCT = 50;   // firm share below this => weather+imports are the majority
export const HEAVY_IMPORT_PCT = 25;    // net imports above this share of demand => heavy reliance

// Wind lull: server precomputes the run (transmission-only daily CF < 20%); we just reshape it.
export function windLullLamp(run) {
  if (!run || !Number.isFinite(run.current_run_days)) return { state: 'unavailable' };
  const base = { cfPct: run.current_cf_pct, asOf: run.as_of };
  return run.current_run_days >= 1
    ? { state: 'active', days: run.current_run_days, ...base }
    : { state: 'nominal', ...base };
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
