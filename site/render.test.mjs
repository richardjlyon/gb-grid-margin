// Pure render helpers for the Grid Gauge dashboard — node --test, run under `uv run pytest`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  gaugeNeedleAngle, cfToInk, tallyGroups, dependenceStatus,
  capacityTrapStatic, gasVsWindMultiple, fmtPct, fmtGW,
} from './render.js';

test('gaugeNeedleAngle maps 0..max onto a -90..+90 half-dial', () => {
  assert.equal(gaugeNeedleAngle(0, 60), -90);
  assert.equal(gaugeNeedleAngle(60, 60), 90);
  assert.equal(gaugeNeedleAngle(30, 60), 0);
});

test('gaugeNeedleAngle clamps out-of-range input to the arc ends', () => {
  assert.equal(gaugeNeedleAngle(-10, 60), -90);
  assert.equal(gaugeNeedleAngle(999, 60), 90);
});

test('cfToInk: low CF is the dark ink end, high CF dissolves to the soft paper end', () => {
  assert.equal(cfToInk(0).toLowerCase(), '#15181c');     // calm day = darkest
  assert.equal(cfToInk(0.45).toLowerCase(), '#eaecee');  // windy day = palest
  assert.equal(cfToInk(1).toLowerCase(), '#eaecee');     // clamped above 0.45
});

test('cfToInk is monotonic — a calmer day is never lighter than a windier one', () => {
  const dark = parseInt(cfToInk(0.05).slice(1), 16);
  const light = parseInt(cfToInk(0.30).slice(1), 16);
  assert.ok(dark < light, 'lower CF must map to a darker (smaller) hex');
});

test('tallyGroups breaks a count into gate-of-five groups', () => {
  assert.deepEqual(tallyGroups(0), []);
  assert.deepEqual(tallyGroups(3), [3]);
  assert.deepEqual(tallyGroups(5), [5]);
  assert.deepEqual(tallyGroups(12), [5, 5, 2]);
});

test('dependenceStatus arms red on the DEPENDENT band or a sub-10% wind day', () => {
  assert.deepEqual(dependenceStatus(20, false), { label: 'NOMINAL', armed: false });
  assert.deepEqual(dependenceStatus(35, false), { label: 'ELEVATED', armed: false });
  assert.deepEqual(dependenceStatus(45, false), { label: 'DEPENDENT', armed: true });
  // A calm-wind day arms the gauge even when the dependence share is only ELEVATED.
  assert.deepEqual(dependenceStatus(35, true), { label: 'ELEVATED', armed: true });
});

test('capacityTrapStatic: live output as a share of DUKES nameplate (sound denominator)', () => {
  // 21500 MW delivered against 50.362 GW built -> 42.7%.
  const t = capacityTrapStatic(21500, 50.362);
  assert.equal(t.built_gw, 50.362);
  assert.equal(t.delivering_mw, 21500);
  assert.equal(t.share_pct, 42.7);
});

test('gasVsWindMultiple: how many times the gas fleet out-produces all wind', () => {
  assert.equal(gasVsWindMultiple(8489, 1400), 6.1);   // 8489/1400 = 6.06 -> 6.1
  assert.equal(gasVsWindMultiple(8000, 8000), 1.0);
  assert.equal(gasVsWindMultiple(5000, 0), null);     // undefined when wind is zero
});

test('fmtPct / fmtGW format for display, with em-dash for non-finite', () => {
  assert.equal(fmtPct(53.1), '53.1%');
  assert.equal(fmtPct(NaN), '—');
  assert.equal(fmtGW(9408), '9.4 GW');
  assert.equal(fmtGW(940), '0.9 GW');
});
