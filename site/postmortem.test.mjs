import test from 'node:test';
import assert from 'node:assert/strict';
import { activeCommentIndex, revealedPoints, formatClock, formatCalendar } from './postmortem-draw.js';

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

test('formatClock renders local half-hour', () => {
  assert.equal(formatClock('2026-06-24T10:30:00Z'), '11:30'); // BST = UTC+1
});

test('formatCalendar renders day/month/weekday', () => {
  const c = formatCalendar('2026-06-24T10:30:00Z');
  assert.deepEqual(c, { day: '24', month: 'JUN', weekday: 'WED' });
});
