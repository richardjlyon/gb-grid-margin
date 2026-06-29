import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  windLullLamp, firmMajorityLamp, heavyImportsLamp, overcastLamp, scarcityLamp,
} from './conditions.js';

// SITE POLICY: a lamp goes amber when the live reading leaves the "usual half" (the IQR box,
// P25–P75) of that panel's distribution, on the concerning side. Wind/firm: low is concerning
// (< P25). Imports: high is concerning (> P75). The percentile is passed in (read live from the
// panel's box-plot) — no magic constants — so the lamp can never disagree with the box beside it.

test('windLullLamp — live CF below the panel P25 is active (a lull now)', () => {
  const r = windLullLamp(18, 22);   // P25 of wind CF ≈ 22
  assert.equal(r.state, 'active');
  assert.equal(r.cfPct, 18);
});
test('windLullLamp — boundary: exactly P25 is nominal (strict <)', () => {
  assert.equal(windLullLamp(22, 22).state, 'nominal');
  assert.equal(windLullLamp(21.9, 22).state, 'active');
  assert.equal(windLullLamp(40, 22).state, 'nominal');
});
test('windLullLamp — missing reading OR missing threshold is unavailable', () => {
  assert.equal(windLullLamp(NaN, 22).state, 'unavailable');
  assert.equal(windLullLamp(18, NaN).state, 'unavailable');
  assert.equal(windLullLamp(18, undefined).state, 'unavailable');
});

test('firmMajorityLamp — below panel P25 is active', () => {
  assert.equal(firmMajorityLamp(35, 38).state, 'active');   // P25 of firm ≈ 38
  assert.equal(firmMajorityLamp(38, 38).state, 'nominal');  // boundary → nominal
  assert.equal(firmMajorityLamp(38.1, 38).state, 'nominal');
});
test('firmMajorityLamp — missing reading OR threshold is unavailable', () => {
  assert.equal(firmMajorityLamp(NaN, 38).state, 'unavailable');
  assert.equal(firmMajorityLamp(35, NaN).state, 'unavailable');
});

test('heavyImportsLamp — above panel P75 is active', () => {
  assert.equal(heavyImportsLamp(67, 54).state, 'active');   // 67% of capacity, P75 ≈ 54
  assert.equal(heavyImportsLamp(67, 54).pct, 67);
});
test('heavyImportsLamp — boundary: exactly P75 is nominal (strict >)', () => {
  assert.equal(heavyImportsLamp(54, 54).state, 'nominal');
  assert.equal(heavyImportsLamp(54.1, 54).state, 'active');
  assert.equal(heavyImportsLamp(30, 54).state, 'nominal');
});
test('heavyImportsLamp — exporting (negative share) is nominal, never trips', () => {
  const r = heavyImportsLamp(-40, 54);
  assert.equal(r.state, 'nominal');
  assert.equal(r.pct, -40);   // carried through so the status line can read "40% export"
});
test('heavyImportsLamp — missing reading OR threshold is unavailable', () => {
  assert.equal(heavyImportsLamp(NaN, 54).state, 'unavailable');
  assert.equal(heavyImportsLamp(67, NaN).state, 'unavailable');
});

// OVERCAST: cell = [p25, ceiling] (CF) for the current (week, SP) of the conditional grid, or null
// for a night/low-sun slot. Relative trip: live solar CF below the slot's p25. Readout = CF/ceiling.
test('overcastLamp — below the slot P25 is active (cloudier than usual for this slot)', () => {
  const r = overcastLamp(0.20, [0.35, 0.70]);   // summer-noon cell
  assert.equal(r.state, 'active');
  assert.ok(Math.abs(r.clearFrac - 0.20 / 0.70) < 1e-9);
});
test('overcastLamp — at/above P25 is nominal', () => {
  assert.equal(overcastLamp(0.35, [0.35, 0.70]).state, 'nominal');   // boundary → nominal
  assert.equal(overcastLamp(0.60, [0.35, 0.70]).state, 'nominal');
});
test('overcastLamp — clear-day fraction clamps to 1 when CF exceeds the ceiling', () => {
  assert.equal(overcastLamp(0.80, [0.35, 0.70]).clearFrac, 1);   // cloud-enhancement over-irradiance
});
test('overcastLamp — a null cell (night / low sun) is dark, never an alarm', () => {
  assert.equal(overcastLamp(0.0, null).state, 'dark');
  assert.equal(overcastLamp(0.5, null).state, 'dark');
});
test('overcastLamp — non-finite CF with a daytime cell is unavailable', () => {
  assert.equal(overcastLamp(NaN, [0.35, 0.70]).state, 'unavailable');
  assert.equal(overcastLamp(undefined, [0.35, 0.70]).state, 'unavailable');
});

test('scarcityLamp — maps warning states', () => {
  assert.equal(scarcityLamp({ status: 'in_force', type: 'EMN', typeLabel: 'Electricity Margin Notice' }).state, 'in_force');
  assert.equal(scarcityLamp({ status: 'clear' }).state, 'clear');
  assert.equal(scarcityLamp({ status: 'unavailable' }).state, 'unavailable');
  assert.equal(scarcityLamp(null).state, 'unavailable');
});
test('scarcityLamp — malformed object with no status', () => {
  assert.equal(scarcityLamp({}).state, 'unavailable');
});
