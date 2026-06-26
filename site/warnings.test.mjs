// Pure warnings parser for the live warning light — node --test, run under `uv run pytest`.
// Covers parseActiveWarnings: which rows from /system/warnings (active-only) light the lamp.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseActiveWarnings, resolveWarnings } from './warnings.js';

// A realistic EMN body (the 26 Jun 2026 notice, abbreviated): carries the covered window.
const EMN_TEXT = 'From : Power System Manager – NESO Electricity Control Centre\r\n\r\n'
  + 'ELECTRICITY MARGIN NOTICE\r\n\r\nFor the period:\r\n'
  + 'from 19:00 hrs to 22:00 hrs on Friday   26/06/2026\r\n\r\n'
  + 'There is a reduced system margin. System margin shortfall 671 MW';
const emnRow = { publishTime: '2026-06-25T23:30:00Z', warningType: 'ELECTRICITY MARGIN NOTICE', warningText: EMN_TEXT };

// Noise the active feed can carry alongside — must never light the scarcity lamp.
const sosoRow = { publishTime: '2026-06-25T22:00:00Z', warningType: 'SO-SO TRADES', warningText: 'inter-operator trade' };
const itRow = { publishTime: '2026-06-25T21:00:00Z', warningType: 'IT SYSTEMS OUTAGE', warningText: 'data feed maintenance' };

test('no rows → not in force', () => {
  assert.deepEqual(parseActiveWarnings([]), { inForce: false });
});

test('only noise (SO-SO TRADES, IT OUTAGE) → not in force', () => {
  assert.deepEqual(parseActiveWarnings([sosoRow, itRow]), { inForce: false });
});

test('non-array input → not in force (defensive, no false alarm)', () => {
  assert.deepEqual(parseActiveWarnings(undefined), { inForce: false });
  assert.deepEqual(parseActiveWarnings(null), { inForce: false });
});

test('active EMN → in force, typed, with parsed window and issue time', () => {
  const r = parseActiveWarnings([emnRow]);
  assert.equal(r.inForce, true);
  assert.equal(r.type, 'EMN');
  assert.equal(r.typeLabel, 'Electricity Margin Notice');
  assert.equal(r.issuedAt, '2026-06-25T23:30:00Z');
  assert.deepEqual(r.window, { from: '19:00', to: '22:00', date: '26/06/2026' });
});

test('mixed scarcity + noise → noise filtered, EMN lights the lamp', () => {
  const r = parseActiveWarnings([sosoRow, emnRow, itRow]);
  assert.equal(r.inForce, true);
  assert.equal(r.type, 'EMN');
});

test('CMN with no parseable window → in force, type CMN, window null', () => {
  const cmn = { publishTime: '2026-01-08T12:04:00Z', warningType: 'CAPACITY MARKET NOTICE',
    warningText: 'CAPACITY MARKET NOTICE issued. System expected tight in settlement period 36.' };
  const r = parseActiveWarnings([cmn]);
  assert.equal(r.inForce, true);
  assert.equal(r.type, 'CMN');
  assert.equal(r.typeLabel, 'Capacity Market Notice');
  assert.equal(r.window, null);
});

test('NISM phrasing → in force, type NISM', () => {
  const nism = { publishTime: '2026-02-01T17:00:00Z', warningType: 'NOTICE OF INSUFFICIENT SYSTEM MARGIN',
    warningText: 'NOTICE OF INSUFFICIENT SYSTEM MARGIN from 17:00 hrs to 19:00 hrs on Sunday   01/02/2026' };
  const r = parseActiveWarnings([nism]);
  assert.equal(r.inForce, true);
  assert.equal(r.type, 'NISM');
  assert.equal(r.typeLabel, 'Notice of Insufficient System Margin');
});

test('multiple active → most severe headlines (EMN outranks CMN)', () => {
  const cmn = { publishTime: '2026-06-25T23:40:00Z', warningType: 'CAPACITY MARKET NOTICE', warningText: 'CMN' };
  const r = parseActiveWarnings([cmn, emnRow]);
  assert.equal(r.type, 'EMN');
});

test('multiple active → NISM outranks EMN', () => {
  const nism = { publishTime: '2026-06-25T20:00:00Z', warningType: 'NOTICE OF INSUFFICIENT SYSTEM MARGIN', warningText: 'NISM' };
  const r = parseActiveWarnings([emnRow, nism]);
  assert.equal(r.type, 'NISM');
});

// --- resolveWarnings: the thin fetch wrapper → in_force | clear | unavailable ---
const ok = (body) => async () => body;

test('resolveWarnings — active EMN feed → in_force, typed', async () => {
  const r = await resolveWarnings({ httpGet: ok({ data: [emnRow] }) });
  assert.equal(r.status, 'in_force');
  assert.equal(r.type, 'EMN');
  assert.deepEqual(r.window, { from: '19:00', to: '22:00', date: '26/06/2026' });
});

test('resolveWarnings — empty feed → clear', async () => {
  assert.equal((await resolveWarnings({ httpGet: ok({ data: [] }) })).status, 'clear');
});

test('resolveWarnings — only noise → clear', async () => {
  assert.equal((await resolveWarnings({ httpGet: ok({ data: [sosoRow, itRow] }) })).status, 'clear');
});

test('resolveWarnings — fetch throws → unavailable (no false all-clear)', async () => {
  const boom = async () => { throw new Error('network'); };
  assert.equal((await resolveWarnings({ httpGet: boom })).status, 'unavailable');
});

test('resolveWarnings — malformed body (data not an array) → unavailable', async () => {
  assert.equal((await resolveWarnings({ httpGet: ok({ data: 'oops' }) })).status, 'unavailable');
  assert.equal((await resolveWarnings({ httpGet: ok({}) })).status, 'unavailable');
});
