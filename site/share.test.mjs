// site/share.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { intents, actionButtons } from './share.js';

test('intents builds X / LinkedIn / Bluesky / Facebook URLs pointing at the stub', () => {
  const card = { slug: 'firm-now', figure: '75% firm', label: 'of the grid is firm' };
  const out = intents(card);
  const x = out.find((i) => i.name === 'X');
  assert.ok(x.href.includes('twitter.com/intent/tweet'));
  assert.ok(decodeURIComponent(x.href).includes('75% firm — of the grid is firm'));
  assert.ok(decodeURIComponent(x.href).includes('https://gridmargin.co.uk/s/firm-now'));
  assert.deepEqual(out.map((i) => i.name), ['X', 'LinkedIn', 'Bluesky', 'Facebook']);
});

test('intents append the content hash to the shared URL so a re-rendered card busts the social cache', () => {
  const card = { slug: 'live-balance', figure: '65%', label: 'depended on weather', version: 'deadbeef12' };
  const out = intents(card);
  for (const i of out) {
    assert.ok(decodeURIComponent(i.href).includes('https://gridmargin.co.uk/s/live-balance?v=deadbeef12'),
      `${i.name} href must carry the cache-bust token`);
  }
});

test('intents omit the bust param when a card has no version (backward compatible)', () => {
  const x = intents({ slug: 'firm-now', figure: 'f', label: 'l' }).find((i) => i.name === 'X');
  assert.ok(decodeURIComponent(x.href).includes('/s/firm-now'));
  assert.ok(!decodeURIComponent(x.href).includes('/s/firm-now?v='));
});

test('actionButtons renders Download + Copy image for a card', () => {
  const html = actionButtons({ slug: 'live-balance', png: '/share/live-balance.png?v=abc' });
  assert.match(html, /Download/);
  assert.match(html, /Copy image/);
  assert.match(html, /\/share\/live-balance\.png\?v=abc/);
});
