import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  windLullLamp, firmMajorityLamp, heavyImportsLamp, scarcityLamp,
  FIRM_MAJORITY_PCT, HEAVY_IMPORT_PCT,
} from './conditions.js';

test('windLullLamp — in a run is active with day count', () => {
  const r = windLullLamp({ current_run_days: 3, current_cf_pct: 18, as_of: '2026-06-23' });
  assert.equal(r.state, 'active');
  assert.equal(r.days, 3);
  assert.equal(r.cfPct, 18);
});
test('windLullLamp — run 0 is nominal', () => {
  assert.equal(windLullLamp({ current_run_days: 0, current_cf_pct: 31, as_of: '2026-06-23' }).state, 'nominal');
});
test('windLullLamp — missing data is unavailable', () => {
  assert.equal(windLullLamp(null).state, 'unavailable');
  assert.equal(windLullLamp({}).state, 'unavailable');
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

test('scarcityLamp — maps warning states', () => {
  assert.equal(scarcityLamp({ status: 'in_force', type: 'EMN', typeLabel: 'Electricity Margin Notice' }).state, 'in_force');
  assert.equal(scarcityLamp({ status: 'clear' }).state, 'clear');
  assert.equal(scarcityLamp({ status: 'unavailable' }).state, 'unavailable');
  assert.equal(scarcityLamp(null).state, 'unavailable');
});
