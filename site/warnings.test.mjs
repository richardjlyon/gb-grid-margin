// Pure warnings parser for the live warning light — node --test, run under `uv run pytest`.
// Covers parseActiveWarnings (which pooled per-type records light the lamp, given a clock) and
// resolveWarnings (the per-type fetch wrapper → in_force | clear | unavailable).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseActiveWarnings, resolveWarnings } from './warnings.js';

// A realistic EMN body (the 26 Jun 2026 notice, abbreviated): carries the covered window.
const EMN_TEXT = 'From : Power System Manager – NESO Electricity Control Centre\r\n\r\n'
  + 'ELECTRICITY MARGIN NOTICE\r\n\r\nFor the period:\r\n'
  + 'from 19:00 hrs to 22:00 hrs on Friday   26/06/2026\r\n\r\n'
  + 'There is a reduced system margin. System margin shortfall 671 MW';
const emnRow = { publishTime: '2026-06-25T23:30:00Z', warningType: 'ELECTRICITY MARGIN NOTICE', warningText: EMN_TEXT };

// A clock inside the 19:00–22:00 (26/06) London window, and one after it.
const WITHIN = new Date('2026-06-26T20:00:00Z');   // London BST 21:00 26/06 → in force
const AFTER = new Date('2026-06-27T00:00:00Z');    // London BST 01:00 27/06 → expired

// A live CMN "currently active" body, and a cancelled one.
const CMN_ACTIVE = { publishTime: '2026-06-26T18:00:00Z', warningType: 'CAPACITY MARKET NOTICE',
  warningText: 'Electricity Capacity Market Notice Currently Active\n\n'
    + 'Commencement time of notice : 18:00 on 26/06/2026' };
const CMN_CANCELLED = { publishTime: '2026-06-26T19:00:00Z', warningType: 'CAPACITY MARKET NOTICE',
  warningText: 'Electricity Capacity Market Notice Cancelled\n\n'
    + 'The Capacity Market Notice originally active from 16:30 on 26/06/2026 has been cancelled' };

// Noise the feed can carry — must never light the scarcity lamp.
const sosoRow = { publishTime: '2026-06-26T21:45:00Z', warningType: 'SO-SO TRADES', warningText: 'inter-operator trade' };
const itRow = { publishTime: '2026-06-26T21:00:00Z', warningType: 'IT SYSTEMS OUTAGE', warningText: 'data feed maintenance' };

test('no rows → not in force', () => {
  assert.deepEqual(parseActiveWarnings([], WITHIN), { inForce: false });
});

test('only noise (SO-SO TRADES, IT OUTAGE) → not in force', () => {
  assert.deepEqual(parseActiveWarnings([sosoRow, itRow], WITHIN), { inForce: false });
});

test('non-array input → not in force (defensive, no false alarm)', () => {
  assert.deepEqual(parseActiveWarnings(undefined, WITHIN), { inForce: false });
  assert.deepEqual(parseActiveWarnings(null, WITHIN), { inForce: false });
});

test('NISM was retired — its phrasing is noise, never lights the lamp', () => {
  const nism = { publishTime: '2026-06-26T17:00:00Z', warningType: 'NOTICE OF INSUFFICIENT SYSTEM MARGIN',
    warningText: 'NOTICE OF INSUFFICIENT SYSTEM MARGIN from 17:00 hrs to 23:00 hrs on Friday   26/06/2026' };
  assert.deepEqual(parseActiveWarnings([nism], WITHIN), { inForce: false });
});

test('active EMN (clock inside window) → in force, typed, with parsed window and issue time', () => {
  const r = parseActiveWarnings([emnRow], WITHIN);
  assert.equal(r.inForce, true);
  assert.equal(r.type, 'EMN');
  assert.equal(r.typeLabel, 'Electricity Margin Notice');
  assert.equal(r.issuedAt, '2026-06-25T23:30:00Z');
  assert.deepEqual(r.window, { from: '19:00', to: '22:00', date: '26/06/2026' });
});

test('EMN past its window end → not in force (fail-safe expiry)', () => {
  assert.deepEqual(parseActiveWarnings([emnRow], AFTER), { inForce: false });
});

test('EMN cancellation record → not in force (lamp clear)', () => {
  const cancel = { publishTime: '2026-06-26T21:00:00Z', warningType: 'ELECTRICITY MARGIN NOTICE',
    warningText: 'ELECTRICITY MARGIN NOTICE NOTIFICATION CANCELLATION — the notice for the period '
      + 'from 19:00 hrs to 22:00 hrs on Friday   26/06/2026 has been cancelled' };
  assert.deepEqual(parseActiveWarnings([cancel], WITHIN), { inForce: false });
});

test('mixed scarcity + noise → noise filtered, EMN lights the lamp', () => {
  const r = parseActiveWarnings([sosoRow, emnRow, itRow], WITHIN);
  assert.equal(r.inForce, true);
  assert.equal(r.type, 'EMN');
});

test('active CMN ("Currently Active") → in force, type CMN, window null', () => {
  const r = parseActiveWarnings([CMN_ACTIVE], WITHIN);
  assert.equal(r.inForce, true);
  assert.equal(r.type, 'CMN');
  assert.equal(r.typeLabel, 'Capacity Market Notice');
  assert.equal(r.window, null);
});

test('cancelled CMN → not in force', () => {
  assert.deepEqual(parseActiveWarnings([CMN_CANCELLED], WITHIN), { inForce: false });
});

test('both in force → EMN leads CMN (editorial precedence, NISM gone)', () => {
  const r = parseActiveWarnings([emnRow, CMN_ACTIVE], WITHIN);
  assert.equal(r.type, 'EMN');
});

// --- resolveWarnings: the per-type fetch wrapper → in_force | clear | unavailable ---

// Dispatch on the warningType query so the mock behaves like the real per-type endpoint, and record
// every URL requested so we can assert the client queries BY TYPE (not the buggy no-params call).
function mockFeed({ emn = [], cmn = [] }) {
  const urls = [];
  const httpGet = async (u) => {
    urls.push(u);
    if (u.includes('ELECTRICITY%20MARGIN%20NOTICE')) return { data: emn };
    if (u.includes('CAPACITY%20MARKET%20NOTICE')) return { data: cmn };
    // A no-params call would return only the single global-latest (here: SO-SO TRADES) — the bug.
    return { data: [sosoRow] };
  };
  return { httpGet, urls };
}

test('resolveWarnings — queries BY warningType, one fetch per scarcity type', async () => {
  const { httpGet, urls } = mockFeed({ emn: [emnRow] });
  await resolveWarnings({ httpGet, now: WITHIN });
  assert.ok(urls.some((u) => u.includes('warningType=ELECTRICITY%20MARGIN%20NOTICE')), 'EMN query');
  assert.ok(urls.some((u) => u.includes('warningType=CAPACITY%20MARKET%20NOTICE')), 'CMN query');
  assert.ok(!urls.some((u) => /\/system\/warnings$/.test(u)), 'never the no-params endpoint');
});

test('resolveWarnings — in-force EMN detected even though a newer SO-SO TRADES is the global latest', async () => {
  // The per-type EMN endpoint returns the EMN; the (unused) no-params path would return SO-SO only.
  const { httpGet } = mockFeed({ emn: [emnRow] });
  const r = await resolveWarnings({ httpGet, now: WITHIN });
  assert.equal(r.status, 'in_force');
  assert.equal(r.type, 'EMN');
  assert.deepEqual(r.window, { from: '19:00', to: '22:00', date: '26/06/2026' });
});

test('resolveWarnings — both types in force → EMN headlines', async () => {
  const { httpGet } = mockFeed({ emn: [emnRow], cmn: [CMN_ACTIVE] });
  const r = await resolveWarnings({ httpGet, now: WITHIN });
  assert.equal(r.status, 'in_force');
  assert.equal(r.type, 'EMN');
});

test('resolveWarnings — a cancellation record → clear (lamp not lit)', async () => {
  const { httpGet } = mockFeed({ cmn: [CMN_CANCELLED] });
  assert.equal((await resolveWarnings({ httpGet, now: WITHIN })).status, 'clear');
});

test('resolveWarnings — empty per-type feeds → clear', async () => {
  const { httpGet } = mockFeed({});
  assert.equal((await resolveWarnings({ httpGet, now: WITHIN })).status, 'clear');
});

test('resolveWarnings — fetch throws → unavailable (no false all-clear)', async () => {
  const boom = async () => { throw new Error('network'); };
  assert.equal((await resolveWarnings({ httpGet: boom, now: WITHIN })).status, 'unavailable');
});

test('resolveWarnings — malformed body (data not an array) → unavailable', async () => {
  assert.equal((await resolveWarnings({ httpGet: async () => ({ data: 'oops' }), now: WITHIN })).status, 'unavailable');
  assert.equal((await resolveWarnings({ httpGet: async () => ({}), now: WITHIN })).status, 'unavailable');
});
