// JS side of the cross-language parity gate. Loads the SAME committed golden vectors
// the Python suite uses and asserts strict key-set + value equality. Run standalone:
//   node --test site/verdict.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  computeVerdict,
  roundHalfEven1,
  validateSnapshot,
  embeddedInWindow,
} from './verdict.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(join(here, '..', 'tests', 'fixtures', 'verdict_vectors.json'), 'utf8'),
);

for (const c of fixture.verdict_cases) {
  test(`verdict parity: ${c.name}`, () => {
    const got = computeVerdict(c.mix, c.embedded);
    // strict key-set: no missing, no extra keys vs the Python contract.
    assert.deepStrictEqual(Object.keys(got).sort(), Object.keys(c.expected).sort());
    // value equality, field by field.
    assert.deepStrictEqual(got, c.expected);
  });
}

for (const c of fixture.snapshot_cases) {
  test(`snapshot parity: ${c.name}`, () => {
    assert.strictEqual(validateSnapshot(c.mix, c.demand), c.expected_valid);
  });
}

for (const c of fixture.embedded_cases) {
  test(`embedded parity: ${c.name}`, () => {
    assert.strictEqual(embeddedInWindow(c.embedded_time, c.snapshot_time), c.expected_valid);
  });
}

// The load-bearing boundary: a .x5 tie must round half-to-even like Python.
test('roundHalfEven1 rounds the 12.25 tie to 12.2 (not 12.3)', () => {
  assert.strictEqual(roundHalfEven1(12.25), 12.2);
});
test('roundHalfEven1 rounds the 12.75 tie to 12.8 (odd digit rounds up to even)', () => {
  assert.strictEqual(roundHalfEven1(12.75), 12.8);
});
