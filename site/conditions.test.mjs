import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  windLullLamp, firmMajorityLamp, heavyImportsLamp, scarcityLamp,
  WIND_LULL_PCT, FIRM_MAJORITY_PCT, HEAVY_IMPORT_PCT,
} from './conditions.js';

test('windLullLamp — live CF below the line is active (a lull now)', () => {
  const r = windLullLamp(18);
  assert.equal(r.state, 'active');
  assert.equal(r.cfPct, 18);
});
test('windLullLamp — boundary: exactly the line is nominal', () => {
  assert.equal(windLullLamp(25).state, 'nominal');   // 25 exactly → nominal (strict <)
  assert.equal(windLullLamp(24.9).state, 'active');
  assert.equal(windLullLamp(31).state, 'nominal');
  assert.equal(WIND_LULL_PCT, 25);
});
test('windLullLamp — non-finite CF is unavailable', () => {
  assert.equal(windLullLamp(NaN).state, 'unavailable');
  assert.equal(windLullLamp(undefined).state, 'unavailable');
  assert.equal(windLullLamp(null).state, 'unavailable');
});

test('firmMajorityLamp — boundary at 50', () => {
  assert.equal(firmMajorityLamp(49.9).state, 'active');
  assert.equal(firmMajorityLamp(50).state, 'nominal');
  assert.equal(firmMajorityLamp(NaN).state, 'unavailable');
  assert.equal(FIRM_MAJORITY_PCT, 50);
});

test('heavyImportsLamp — boundary at 25% of demand', () => {
  assert.equal(heavyImportsLamp(2600, 10000).state, 'active');   // 26%
  assert.equal(heavyImportsLamp(2500, 10000).state, 'nominal');  // 25% exactly → nominal
  assert.equal(heavyImportsLamp(-4000, 10000).state, 'nominal'); // exporting → nominal
  assert.equal(heavyImportsLamp(2600, 0).state, 'unavailable');  // bad demand
  assert.equal(HEAVY_IMPORT_PCT, 25);
});
test('heavyImportsLamp — NaN guards', () => {
  assert.equal(heavyImportsLamp(NaN, 10000).state, 'unavailable');
  assert.equal(heavyImportsLamp(2600, NaN).state, 'unavailable');
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
