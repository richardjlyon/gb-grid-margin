// site/share.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { intents } from './share.js';

test('intents builds X / LinkedIn / Bluesky / Facebook URLs pointing at the stub', () => {
  const card = { slug: 'firm-now', figure: '75% firm', label: 'of the grid is firm' };
  const out = intents(card);
  const x = out.find((i) => i.name === 'X');
  assert.ok(x.href.includes('twitter.com/intent/tweet'));
  assert.ok(decodeURIComponent(x.href).includes('75% firm — of the grid is firm'));
  assert.ok(decodeURIComponent(x.href).includes('https://gridmargin.co.uk/s/firm-now'));
  assert.deepEqual(out.map((i) => i.name), ['X', 'LinkedIn', 'Bluesky', 'Facebook']);
});
