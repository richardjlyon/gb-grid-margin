// Orchestration/fallback/clock coverage for live.js — the layer the parity tests don't
// reach. resolveState takes an injectable httpGet so the state machine is testable with
// canned feed bodies (no network, no DOM). Run: node --test site/live.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { resolveState } from './live.js';

const SNAP = '2026-06-25T13:30:00Z';
const NOW = Date.parse(SNAP) + 5 * 60 * 1000; // 5 min after the snapshot — fresh, trusted clock
const clock = () => NOW;

const fuelBody = (snap = SNAP, extra = {}) => {
  const mix = { CCGT: 6000, WIND: 5000, NUCLEAR: 3000, BIOMASS: 2000, INTFR: 1500, ...extra };
  return Object.entries(mix).map(([fuelType, generation]) => ({ startTime: snap, fuelType, generation }));
};
const nesoBody = () => ({
  result: { records: [{
    DATE_GMT: '2026-06-25T00:00:00', TIME_GMT: '13:30',
    EMBEDDED_SOLAR_FORECAST: 8000, EMBEDDED_WIND_FORECAST: 1000,
    EMBEDDED_SOLAR_CAPACITY: 22000, EMBEDDED_WIND_CAPACITY: 6400,
  }] },
});
const itsdoBody = (mw = 17500) => ({ data: [{ initialTransmissionSystemDemandOutturn: mw }] });

// A well-formed latest.json with an OLDER snapshot than the live one (so H1 won't trip).
const latestJson = (over = {}) => ({
  schema_version: 1,
  verdict: {
    renewables_pct: 50.0, wind_pct: 20.0, solar_pct: 30.0,
    gas_plus_imports_pct: 30.0, gas_pct: 18.0, import_pct: 12.0,
    wind_mw: 6000, solar_mw: 8000,
  },
  provenance: {
    build_time_utc: new Date(Date.parse(SNAP) - 10 * 60 * 1000).toISOString(),
    snapshot: '2026-06-25T13:00:00Z',
    wind_capacity_mw: 6400, solar_capacity_mw: 22000,
  },
  ...over,
});

// Build an httpGet that routes by URL substring; a value of Error (instance) is thrown.
function makeHttpGet({ fuel, neso, itsdo, latest }) {
  return async (url) => {
    const pick = url.includes('FUELINST') ? fuel
      : url.includes('datastore_search') ? neso
        : url.includes('demand/outturn') ? itsdo
          : url.includes('latest.json') ? latest : undefined;
    if (pick instanceof Error) throw pick;
    if (pick === undefined) throw new Error(`unexpected url ${url}`);
    return pick;
  };
}

const NO_FAULTS = { break: null, slow: null, partial: null, staleNeso: false, futureNeso: false, clockOffsetMs: 0 };

test('happy path renders LIVE with verdict numbers', async () => {
  const httpGet = makeHttpGet({ fuel: fuelBody(), neso: nesoBody(), itsdo: itsdoBody(), latest: latestJson() });
  const s = await resolveState(NO_FAULTS, clock, { httpGet });
  assert.equal(s.mode, 'live');
  assert.ok(Number.isFinite(s.verdict.renewables_pct));
});

// H1: a prior successful build proves a newer snapshot exists → the live reading is stale.
test('H1: live snapshot older than last build falls back, not LIVE', async () => {
  const httpGet = makeHttpGet({
    fuel: fuelBody('2026-06-25T12:30:00Z'), // live snapshot an hour behind the build
    neso: nesoBody(), itsdo: itsdoBody(),
    latest: latestJson({ provenance: { ...latestJson().provenance, snapshot: '2026-06-25T13:00:00Z' } }),
  });
  const s = await resolveState(NO_FAULTS, () => Date.parse('2026-06-25T12:35:00Z'), { httpGet });
  assert.equal(s.mode, 'fallback');
});

// H2: a corrupt-but-schema-valid latest.json must reach UNAVAILABLE, never NaN% or a throw.
test('H2: live fails + corrupt fallback (missing pct) → UNAVAILABLE, no numbers', async () => {
  const bad = latestJson();
  delete bad.verdict.renewables_pct;
  const httpGet = makeHttpGet({ fuel: new Error('feed down'), neso: nesoBody(), itsdo: itsdoBody(), latest: bad });
  const s = await resolveState(NO_FAULTS, clock, { httpGet });
  assert.equal(s.mode, 'unavailable');
  assert.equal(s.verdict, null);
});

test('H2: live fails + fallback capacity zero → UNAVAILABLE (no Infinity%)', async () => {
  const bad = latestJson();
  bad.provenance.wind_capacity_mw = 0;
  const httpGet = makeHttpGet({ fuel: new Error('feed down'), neso: nesoBody(), itsdo: itsdoBody(), latest: bad });
  const s = await resolveState(NO_FAULTS, clock, { httpGet });
  assert.equal(s.mode, 'unavailable');
});

// M1: an empty ITSDO body must NOT discard a good live verdict.
test('M1: empty ITSDO body stays LIVE with a degraded note', async () => {
  const httpGet = makeHttpGet({ fuel: fuelBody(), neso: nesoBody(), itsdo: { data: [] }, latest: latestJson() });
  const s = await resolveState(NO_FAULTS, clock, { httpGet });
  assert.equal(s.mode, 'live');
  assert.match(s.reconcileNote, /unavailable/);
});

test('M1: a genuine ITSDO reconcile breach falls back', async () => {
  const httpGet = makeHttpGet({ fuel: fuelBody(), neso: nesoBody(), itsdo: itsdoBody(40000), latest: latestJson() });
  const s = await resolveState(NO_FAULTS, clock, { httpGet });
  assert.equal(s.mode, 'fallback');
});

// M2: an unbounded fallback fetch must not hang — a throwing httpGet → UNAVAILABLE.
test('M2: fallback fetch failure → UNAVAILABLE (does not hang)', async () => {
  const httpGet = makeHttpGet({ fuel: new Error('feed down'), neso: nesoBody(), itsdo: itsdoBody(), latest: new Error('timeout') });
  const s = await resolveState(NO_FAULTS, clock, { httpGet });
  assert.equal(s.mode, 'unavailable');
});

// M3: fallback capacity shares must use round-half-even, matching the engine on .x5 ties.
test('M3: fallback capacity share uses round-half-even (12.25 → 12.2)', async () => {
  const bad = latestJson();
  bad.verdict.wind_mw = 2450;            // 2450 / 20000 * 100 = 12.25 → half-even → 12.2
  bad.provenance.wind_capacity_mw = 20000;
  const httpGet = makeHttpGet({ fuel: new Error('feed down'), neso: nesoBody(), itsdo: itsdoBody(), latest: bad });
  const s = await resolveState(NO_FAULTS, clock, { httpGet });
  assert.equal(s.mode, 'fallback');
  assert.equal(s.capacity.wind_capacity_share_pct, 12.2);
});
