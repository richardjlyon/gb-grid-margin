// Tiny JS evaluator for the fuzz parity test. Reads a batch JSON file
// (argv[2]) of [{mix, embedded}, ...], maps each through computeVerdict, and prints
// the JSON array of outputs to stdout. No assertions — the assertion lives in pytest.
import { readFileSync } from 'node:fs';
import { computeVerdict } from './verdict.js';

const batch = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = batch.map((c) => computeVerdict(c.mix, c.embedded));
process.stdout.write(JSON.stringify(out));
