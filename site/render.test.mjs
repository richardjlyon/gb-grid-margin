// Pure render helpers for the Grid Gauge dashboard — node --test, run under `uv run pytest`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  gaugeNeedleAngle, cfToInk, tallyGroups, firmStatus, firmShares,
  capacityTrapStatic, fmtPct, fmtPct0, fmtGW, sourceArcModel,
  reliableShareToColor, unreliableNowPct, rgbCss, RELIABILITY_RAMP,
  carpetCellColor, gaugeCalibration,
} from './render.js';

const approx = (a, b, eps = 0.001) => Math.abs(a - b) <= eps;

test('sourceArcModel — importing: imports is a slice, fracs tile demand', () => {
  const v = { gas_mw: 12000, nuclear_mw: 5000, biomass_mw: 2000, other_mw: 1000, wind_mw: 8000, solar_mw: 2000, net_import_mw: 6000, national_demand_mw: 36000 };
  const m = sourceArcModel(v);
  assert.equal(m.arcTotal, 36000);
  assert.equal(m.firmPct, 55.6);
  assert.equal(m.exportMw, 0);
  assert.ok(approx(m.slices.find((s) => s.key === 'imports').frac, 6000 / 36000));
  assert.ok(approx(m.slices.reduce((s, x) => s + x.frac, 0), 1));
});

test('sourceArcModel — exporting: weather slice shrinks, surplus is the tail', () => {
  const v = { gas_mw: 12000, nuclear_mw: 5000, biomass_mw: 2000, other_mw: 1000, wind_mw: 10000, solar_mw: 0, net_import_mw: -4500, national_demand_mw: 25500 };
  const m = sourceArcModel(v);
  assert.equal(m.arcTotal, 25500);
  assert.equal(m.firmPct, 78.4);
  assert.equal(m.exportMw, 4500);
  assert.equal(m.slices.find((s) => s.key === 'imports'), undefined);
  assert.ok(approx(m.slices.find((s) => s.key === 'wind').mw, 5500));   // 10000 − 4500 exported
  assert.ok(approx(m.slices.reduce((s, x) => s + x.frac, 0), 1));       // served slices tile demand
});

test('sourceArcModel — over-export: no negative slices (clamp), firm shrinks', () => {
  const v = { gas_mw: 12000, nuclear_mw: 5000, biomass_mw: 2000, other_mw: 1000, wind_mw: 2000, solar_mw: 0, net_import_mw: -5000, national_demand_mw: 17000 };
  const m = sourceArcModel(v);
  assert.equal(m.exportMw, 5000);
  assert.equal(m.firmPct, 100);
  assert.ok(approx(m.slices.find((s) => s.key === 'wind').mw, 0));
  assert.ok(m.slices.every((s) => s.mw >= -1e-9));
  assert.ok(approx(m.slices.reduce((s, x) => s + x.frac, 0), 1));
});

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

test('firmStatus reads the firm-power share; UNRELIABLE (red) when firm power runs low', () => {
  assert.deepEqual(firmStatus(70), { label: 'RELIABLE', armed: false });
  assert.deepEqual(firmStatus(55), { label: 'RELIABLE', armed: false });
  assert.deepEqual(firmStatus(35), { label: 'UNRELIABLE', armed: true });
  // boundary: exactly 50 is RELIABLE; below 50 (less than half the grid firm) arms red.
  assert.deepEqual(firmStatus(50), { label: 'RELIABLE', armed: false });
  assert.deepEqual(firmStatus(49.9), { label: 'UNRELIABLE', armed: true });
});

test('firmShares prefers the engine fields, derives from MW for a pre-firm fallback', () => {
  // full verdict (current schema) — uses the parity-locked engine firm_pct/notfirm_pct
  const full = firmShares({ national_demand_mw: 20000, firm_mw: 8000, notfirm_mw: 12000, firm_pct: 40.0, notfirm_pct: 60.0 });
  assert.equal(full.firm_pct, 40.0);
  assert.equal(full.notfirm_pct, 60.0);
  // old fallback latest.json — no firm_* fields, derive from the per-fuel MW
  const old = firmShares({ national_demand_mw: 20000, gas_mw: 6000, nuclear_mw: 1000, biomass_mw: 1000, other_mw: 0, wind_mw: 8000, solar_mw: 3000, net_import_mw: 1000 });
  assert.equal(old.firm_mw, 8000);
  assert.equal(old.notfirm_mw, 12000);
  assert.equal(old.firm_pct, 40.0);
  assert.equal(old.notfirm_pct, 60.0);
});

test('capacityTrapStatic: live output as a share of DUKES nameplate (sound denominator)', () => {
  // 21500 MW delivered against 50.362 GW built -> 42.7%.
  const t = capacityTrapStatic(21500, 50.362);
  assert.equal(t.built_gw, 50.362);
  assert.equal(t.delivering_mw, 21500);
  assert.equal(t.share_pct, 42.7);
});

test('fmtPct / fmtGW format for display, with em-dash for non-finite', () => {
  assert.equal(fmtPct(53.1), '53.1%');
  assert.equal(fmtPct(NaN), '—');
  assert.equal(fmtGW(9408), '9.4 GW');
  assert.equal(fmtGW(940), '0.9 GW');
});

test('fmtPct0 rounds to a whole percent (the gauge stamps), em-dash for non-finite', () => {
  assert.equal(fmtPct0(76.5), '77%');   // round-half-up at .5
  assert.equal(fmtPct0(23.4), '23%');
  assert.equal(fmtPct0(NaN), '—');
});

test('reliableShareToColor — pale above the firm margin, full red below the arming floor', () => {
  const paper = [251, 251, 249], red = [214, 18, 31];
  assert.deepEqual(reliableShareToColor(0.70), paper);   // >= hi (0.65) → paper
  assert.deepEqual(reliableShareToColor(0.30), red);      // <= lo (0.40) → full red
  assert.deepEqual(reliableShareToColor(1.30), paper);    // net-export (>1) clamps to palest
});

test('reliableShareToColor — monotonic: a less-firm half-hour is never paler', () => {
  const redness = (s) => 251 - reliableShareToColor(s)[0];   // distance of R-channel from paper
  assert.ok(redness(0.40) >= redness(0.50));
  assert.ok(redness(0.50) >= redness(0.60));
});

test('reliableShareToColor — a gap (null) is grey, distinct from 0', () => {
  assert.deepEqual(reliableShareToColor(null), [232, 232, 230]);
  assert.notDeepEqual(reliableShareToColor(0), reliableShareToColor(null));
});

test('unreliableNowPct — 100 − firm, clamped, null when not finite', () => {
  assert.equal(unreliableNowPct(74), 26);
  assert.equal(unreliableNowPct(120), 0);      // net export → firm>100 → 0% unreliable
  assert.equal(unreliableNowPct(NaN), null);
});

test('rgbCss formats a triple', () => {
  assert.equal(rgbCss([1, 2, 3]), 'rgb(1,2,3)');
});

test('carpetCellColor — cf=0 paper, cf>=satFull saturated full colour, null grey, monotonic', () => {
  const blue = [31, 111, 192];
  const none = carpetCellColor(0, 0.55, blue);
  const full = carpetCellColor(0.55, 0.55, blue);
  const over = carpetCellColor(0.9, 0.55, blue);     // clamps to full
  assert.deepEqual(none, [251, 251, 249]);           // no output -> white paper
  assert.deepEqual(full, blue);                       // full output -> saturated source colour
  assert.deepEqual(over, full);
  assert.deepEqual(carpetCellColor(null, 0.55, blue), [232, 232, 230]);   // gap grey
  const mid = carpetCellColor(0.275, 0.55, blue);    // halfway (OKLab) -> between paper and full per channel
  assert.ok(mid[0] > full[0] && mid[0] < none[0]);
  assert.ok(mid[2] > full[2] && mid[2] < none[2]);
  // OKLab ramp is monotonic in lightness: each step toward full output is no lighter than the last.
  const lum = (c) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  let prev = lum(none);
  for (let cf = 0.05; cf <= 0.55; cf += 0.05) {
    const L = lum(carpetCellColor(cf, 0.55, blue));
    assert.ok(L <= prev + 1e-9, `lightness should not increase at cf=${cf.toFixed(2)}`);
    prev = L;
  }
});

test('gaugeCalibration — five ticks, 0% and 100% present, MW ends 0 and nameplate', () => {
  const t = gaugeCalibration(50362);
  assert.equal(t.length, 5);
  assert.deepEqual(t.map((x) => x.pct), [0, 25, 50, 75, 100]);
  assert.equal(t[0].label_pct, '0%');
  assert.equal(t[4].label_pct, '100%');
  assert.equal(t[0].label_mw, '0');
  assert.equal(t[4].label_mw, '50,362');
  assert.equal(t[2].label_mw, '25,181');       // 50% of 50,362
  assert.ok(Math.abs(t[2].frac - 0.5) < 1e-9);
});

test('gaugeCalibration(null) — percent ticks only, no MW labels', () => {
  const t = gaugeCalibration(null);
  assert.equal(t.length, 5);
  assert.deepEqual(t.map((x) => x.pct), [0, 25, 50, 75, 100]);
  assert.ok(t.every((x) => x.label_mw === null));
  assert.equal(t[2].label_pct, '50%');
});
