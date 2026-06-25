// site/verdict.js — the browser half of the parity contract.
//
// A line-for-line transliteration of engine/grid_engine.py compute_verdict and its
// snapshot/embedded guards. It must emit the EXACT same keys and values as the Python
// engine for every input; the golden + fuzz parity tests enforce this. Pure: no DOM,
// no fetch.

// Mirror of the Python build-time constants.
export const REQUIRED_FUELS = ['CCGT', 'WIND', 'NUCLEAR'];
export const DEMAND_FLOOR_MW = 15000;
export const EMBEDDED_WINDOW_MIN = 30;

const EXCLUDE = new Set(['WIND', 'CCGT', 'OCGT', 'NUCLEAR', 'BIOMASS']);
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const get = (mix, k) => (has(mix, k) ? mix[k] : 0);

// Round half-to-even to 1 decimal place, matching Python's round(x, 1) on the same
// IEEE-754 double. Uses the 17-significant-digit decimal expansion (which uniquely
// identifies the double) to read the true discarded remainder — so naive half-up
// divergence on .x5 ties (e.g. 12.25 -> 12.2, not 12.3) cannot happen.
export function roundHalfEven1(x) {
  if (!Number.isFinite(x)) return x;
  if (Math.abs(x) < 1e-6) return 0; // rounds to 0.0 at 1 dp; also avoids exponential toPrecision strings
  const neg = x < 0;
  const s = Math.abs(x).toPrecision(17); // decimal, no exponent for our 0..100 range
  const dot = s.indexOf('.');
  const intPart = dot === -1 ? s : s.slice(0, dot);
  const frac = dot === -1 ? '' : s.slice(dot + 1);
  const d1 = frac.length ? Number(frac[0]) : 0;
  const rest = frac.slice(1).replace(/0+$/, ''); // discarded part beyond 1 dp
  let unit = Number(intPart) * 10 + d1; // value*10, truncated toward zero
  if (rest === '') {
    // exact at 1 dp — nothing to round
  } else if (rest[0] > '5' || (rest[0] === '5' && rest.length > 1)) {
    unit += 1; // remainder > 0.5
  } else if (rest[0] < '5') {
    // remainder < 0.5 — truncate
  } else if (unit % 2 === 1) {
    unit += 1; // remainder == 0.5 exactly — round half to even
  }
  const val = unit / 10;
  // TODO(stage3-audit L2): returns +0 where Python round() yields -0.0; only reachable with
  // negative national demand, which the guards block. See engine/NOTES.md §5 deferred findings.
  return neg ? -val : val;
}

export function computeVerdict(mix, embedded) {
  const solar = embedded.solar_mw;
  const embeddedWind = embedded.wind_mw;
  const transWind = get(mix, 'WIND');
  const gas = get(mix, 'CCGT') + get(mix, 'OCGT');
  const nuclear = get(mix, 'NUCLEAR');
  const biomass = get(mix, 'BIOMASS');
  let netImports = 0;
  let other = 0;
  for (const [k, v] of Object.entries(mix)) {
    if (k.toUpperCase().startsWith('INT')) { netImports += v; continue; }
    if (v > 0 && k !== 'PS' && !EXCLUDE.has(k)) other += v;
  }
  const wind = transWind + embeddedWind;
  const demand = transWind + gas + nuclear + biomass + other + netImports + solar + embeddedWind;
  const pct = (x) => (demand ? roundHalfEven1((x / demand) * 100) : 0.0);
  return {
    snapshot: null, // filled by caller, mirrors Python
    embedded_time: embedded.time,
    national_demand_mw: demand,
    wind_mw: wind,
    solar_mw: solar,
    gas_mw: gas,
    net_import_mw: netImports,
    nuclear_mw: nuclear,
    biomass_mw: biomass,
    other_mw: other,
    wind_pct: pct(wind),
    solar_pct: pct(solar),
    gas_pct: pct(gas),
    import_pct: pct(netImports),
    gas_plus_imports_pct: pct(gas + netImports),
    renewables_pct: pct(wind + solar),
    solar_included: true,
  };
}

// Collapse FUELINST records to the single most recent 5-minute bucket: {fuelType: MW}.
export function latestSnapshot(records) {
  if (!records || records.length === 0) {
    throw new Error('FUELINST returned no records');
  }
  let latest = records[0].startTime;
  for (const r of records) if (r.startTime > latest) latest = r.startTime;
  const mix = {};
  for (const r of records) if (r.startTime === latest) mix[r.fuelType] = r.generation;
  return { snapshot: latest, mix };
}

// True only if the FUELINST bucket looks complete (not a partial publish).
export function validateSnapshot(mix, demand) {
  for (const f of REQUIRED_FUELS) if (!has(mix, f)) return false;
  let hasInt = false;
  for (const k of Object.keys(mix)) if (k.toUpperCase().startsWith('INT')) { hasInt = true; break; }
  if (!hasInt) return false;
  return demand >= DEMAND_FLOOR_MW;
}

// True if the embedded estimate is within EMBEDDED_WINDOW_MIN of the snapshot.
// Fail-closed: an unparseable timestamp returns false (treated as stale), never fresh.
export function embeddedInWindow(embeddedTime, snapshotTime) {
  const emb = Date.parse(embeddedTime);
  const snap = Date.parse(snapshotTime);
  if (Number.isNaN(emb) || Number.isNaN(snap)) return false;
  return Math.abs(emb - snap) <= EMBEDDED_WINDOW_MIN * 60 * 1000;
}

// The capacity-trap, on the LIVE NESO GB-DC capacities (NOT nameplate.json — see
// engine/NOTES.md #2; the bases must never be mixed).
export function capacityTrap(verdict, embedded) {
  const share = (mw, cap) => (cap ? roundHalfEven1((mw / cap) * 100) : 0.0);
  return {
    wind_capacity_share_pct: share(verdict.wind_mw, embedded.wind_capacity_mw),
    solar_capacity_share_pct: share(verdict.solar_mw, embedded.solar_capacity_mw),
    denominator_basis: 'NESO GB-DC live',
  };
}
