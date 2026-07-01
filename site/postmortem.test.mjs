import test from 'node:test';
import assert from 'node:assert/strict';
import { activeCommentIndex, revealedPoints, formatClock, formatCalendar, frameParts } from './postmortem-draw.js';
import { COL_WIND, COL_SOLAR, COL_IMPORTS } from './render.js';

test('activeCommentIndex picks the last entry at or before sp', () => {
  const c = [{ period: 24 }, { period: 38 }, { period: 43 }];
  assert.equal(activeCommentIndex(c, 20), -1);
  assert.equal(activeCommentIndex(c, 24), 0);
  assert.equal(activeCommentIndex(c, 40), 1);
  assert.equal(activeCommentIndex(c, 48), 2);
});

test('revealedPoints reveals only up to i and skips null prices', () => {
  const frames = [{ price_gbp_mwh: 50 }, { price_gbp_mwh: null }, { price_gbp_mwh: 100 }];
  const pts = revealedPoints(frames, 2);
  assert.equal(pts.length, 2);            // null skipped
  assert.equal(pts[pts.length - 1].y, 1); // 100 is the max -> y=1
});

test('revealedPoints normalises x by the full series length, not the revealed count', () => {
  const frames = [{ price_gbp_mwh: 50 }, { price_gbp_mwh: 100 }, { price_gbp_mwh: 75 }];
  const pts = revealedPoints(frames, 1); // partial reveal: only first 2 of 3 frames
  assert.equal(pts.length, 2);
  assert.equal(pts[1].x, 0.5); // k=1 / (n-1)=2, n = full series length (3), not revealed count
});

test('frameParts returns reliability/wind/solar/imports keyed to the shared render.js palette', () => {
  const frame = { firm_pct: 62, wind_cf_pct: 30, solar_cf_pct: 10, import_cf_pct: 5 };
  const parts = frameParts(frame);
  assert.equal(parts.length, 4);
  assert.deepEqual(parts.map((p) => p.key), ['reliability', 'wind', 'solar', 'imports']);
  const byKey = Object.fromEntries(parts.map((p) => [p.key, p]));
  assert.equal(byKey.wind.color, COL_WIND);
  assert.equal(byKey.solar.color, COL_SOLAR);
  assert.equal(byKey.imports.color, COL_IMPORTS);
});

test('frameParts treats a null CF field as zero with a dash valueText', () => {
  const frame = { firm_pct: 62, wind_cf_pct: null, solar_cf_pct: 10, import_cf_pct: 5 };
  const parts = frameParts(frame);
  const wind = parts.find((p) => p.key === 'wind');
  assert.equal(wind.value, 0);
  assert.equal(wind.valueText, '—');
});

test('formatClock renders local half-hour', () => {
  assert.equal(formatClock('2026-06-24T10:30:00Z'), '11:30'); // BST = UTC+1
});

test('formatCalendar renders day/month/weekday', () => {
  const c = formatCalendar('2026-06-24T10:30:00Z');
  assert.deepEqual(c, { day: '24', month: 'JUN', weekday: 'WED' });
});
