// Pure render helpers for the Grid Margin dashboard — node --test, run under `uv run pytest`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  gaugeNeedleAngle, firmStatus, firmShares,
  capacityTrapStatic, fmtPct, fmtPct0, fmtGW, sourceArcModel,
  reliableShareToColor, unreliableNowPct, rgbCss, RELIABILITY_RAMP,
  carpetCellColor, gaugeCalibration, unreliabilityColor, reliabilityColor, windDroughtColor, droughtSpikes,
  droughtCaption, carpetMonthTicks,
  importRatePerHour,
  importValueColor, importRateAngle, importCostCaption,
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

test('unreliabilityColor — green at 0, amber mid, red at 1, gap grey, hue progresses green->red', () => {
  const green = unreliabilityColor(0), amber = unreliabilityColor(0.5), red = unreliabilityColor(1);
  assert.deepEqual(green, [27, 110, 69]);            // fully reliable -> green endpoint verbatim (#1b6e45)
  assert.deepEqual(amber, [230, 160, 25]);           // midpoint -> amber endpoint verbatim
  assert.deepEqual(red, [214, 18, 31]);              // fully unreliable -> red endpoint verbatim
  assert.deepEqual(unreliabilityColor(null), [232, 232, 230]);  // gap grey
  assert.deepEqual(unreliabilityColor(1.5), red);    // clamps above 1
  assert.deepEqual(unreliabilityColor(-1), green);   // clamps below 0
  // Lower half (green->amber): a quarter-point sits between the two endpoints per channel — redder
  // (higher R) and less blue than green, not yet amber.
  const q1 = unreliabilityColor(0.25);
  assert.ok(q1[0] > green[0] && q1[0] < amber[0], 'q1 red between green and amber');
  assert.ok(q1[2] < green[2] && q1[2] > amber[2], 'q1 blue between green and amber');
  // Upper half (amber->red): a three-quarter point loses green channel toward red but stays warm.
  const q3 = unreliabilityColor(0.75);
  assert.ok(q3[1] < amber[1] && q3[1] > red[1], 'q3 green channel between amber and red');
  assert.ok(q3[0] > 150, 'q3 stays warm (high red channel)');
});
test('reliabilityColor — the unreliability ramp reversed: red at 0% reliable, green at 100%', () => {
  // The Entry-01 block reads RELIABILITY: 0 (none reliable) is the alarm (red), 1 (all firm) is green.
  // It is exactly unreliabilityColor read from the other end, so red/amber/green endpoints match verbatim.
  assert.deepEqual(reliabilityColor(0), [214, 18, 31]);            // 0% reliable -> red
  assert.deepEqual(reliabilityColor(0.5), [230, 160, 25]);         // midpoint -> amber
  assert.deepEqual(reliabilityColor(1), [27, 110, 69]);            // 100% reliable -> green (#1b6e45)
  assert.deepEqual(reliabilityColor(0.25), unreliabilityColor(0.75)); // mirror identity, mid-low sample
  assert.deepEqual(reliabilityColor(null), [232, 232, 230]);       // gap grey, distinct from 0
  assert.deepEqual(reliabilityColor(-1), [214, 18, 31]);           // clamps below 0 -> red
  assert.deepEqual(reliabilityColor(1.5), [27, 110, 69]);          // clamps above 1 -> green (#1b6e45)
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

test('windDroughtColor — windy is pale, calm is deep red, null is grey, monotonic', () => {
  const pale = [251, 251, 249], deep = [140, 12, 20];
  assert.deepEqual(windDroughtColor(0.45), pale);   // at/above anchor -> pale
  assert.deepEqual(windDroughtColor(0.60), pale);   // clamps
  assert.deepEqual(windDroughtColor(0), deep);       // dead calm -> deepest red
  assert.deepEqual(windDroughtColor(null), [232, 232, 230]);
  // redness rises monotonically as CF falls (R stays high, G/B fall).
  const g = (cf) => windDroughtColor(cf)[1];
  assert.ok(g(0.05) < g(0.20) && g(0.20) < g(0.40));
});

test('droughtSpikes — maps start date to x, days to height, flags minor (<2d)', () => {
  const x0 = Date.parse('2020-01-01'), x1 = Date.parse('2020-12-31');
  const lulls = [
    { start: '2020-01-01', days: 1, min_cf: 0.07, severe: false },
    { start: '2020-07-01', days: 10, min_cf: 0.03, severe: true },
  ];
  const s = droughtSpikes(lulls, { x0ms: x0, x1ms: x1, w: 1000, h: 200, maxDays: 20 });
  assert.equal(s[0].x, 0);            // first day -> left edge
  assert.ok(s[0].minor === true);     // 1-day -> minor
  assert.equal(s[0].h, 200 / 20);     // 1/20 of height
  assert.ok(s[1].x > 480 && s[1].x < 520);  // ~midyear -> ~middle
  assert.equal(s[1].h, 100);          // 10/20 -> half height
  assert.ok(s[1].severe === true && s[1].minor === false);
});

test('droughtCaption — neutral sentence from counts and the record lull', () => {
  const s = { counts: { ge_3d: 42 }, record_lull: { days: 12, start: '2021-07-03' } };
  const txt = droughtCaption(s);
  assert.ok(txt.includes('42'));
  assert.ok(txt.includes('12 days'));
  assert.ok(/July 2021/.test(txt));
});

test('carpetMonthTicks — 12 months, Jan at 0, ascending fractions', () => {
  const t = carpetMonthTicks();
  assert.equal(t.length, 12);
  assert.equal(t[0].label, 'J');
  assert.equal(t[0].frac, 0);
  for (let i = 1; i < 12; i++) assert.ok(t[i].frac > t[i - 1].frac && t[i].frac < 1);
});

test('importRatePerHour golden: 6890 MW × £800/MWh → £5,512,000/h', () => {
  assert.equal(importRatePerHour(6890, 800), 5512000);
});

test('importRatePerHour export floor: negative net MW → £0/h', () => {
  assert.equal(importRatePerHour(-500, 800), 0);
});

test('importRatePerHour negative price: 6890 MW × −£50/MWh → £0/h (floor)', () => {
  assert.equal(importRatePerHour(6890, -50), 0);
});

// --- import-cost carpet + gauge helpers (Task 9) --------------------------------

test('importValueColor — paper at £0, deep red at/above cap, grey on null', () => {
  assert.deepEqual(importValueColor(0), [251, 251, 249]);          // £0 → paper (cheap)
  assert.deepEqual(importValueColor(10e6), [140, 12, 20]);         // at cap → deep red
  assert.deepEqual(importValueColor(20e6), [140, 12, 20]);         // above cap → clamps to deep red
  assert.deepEqual(importValueColor(null), [232, 232, 230]);       // null → gap grey
});

test('importValueColor — monotone: redness increases with cost (luminance falls)', () => {
  const lum = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const [c1, c5, c10] = [1e6, 5e6, 10e6].map((v) => importValueColor(v));
  assert.ok(lum(c1) > lum(c5), 'less expensive should be lighter');
  assert.ok(lum(c5) > lum(c10), 'less expensive should be lighter');
  assert.notDeepEqual(c1, c5);
  assert.notDeepEqual(c5, c10);
});

test('importRateAngle — -90 at £0/h, +90 at/above cap, 0 at half-cap', () => {
  assert.equal(importRateAngle(0), -90);
  assert.equal(importRateAngle(5e6), 90);
  assert.equal(importRateAngle(10e6), 90);   // clamps above cap
  assert.equal(importRateAngle(2.5e6), 0);   // half-cap → straight up
});

test('importCostCaption — contains £m figure and formatted date; fallback when summary missing', () => {
  const s = { worst_day: { value_gbp: 94400000, date: '2021-09-09' } };
  const txt = importCostCaption(s);
  assert.ok(txt.includes('£94.4m'), `expected £94.4m in: "${txt}"`);
  assert.ok(txt.includes('9 Sep 2021'), `expected "9 Sep 2021" in: "${txt}"`);
  // fallback: null, undefined, empty object
  const fb = importCostCaption(null);
  assert.ok(typeof fb === 'string' && fb.length > 0, 'fallback should be a non-empty string');
  const fb2 = importCostCaption({});
  assert.ok(typeof fb2 === 'string' && fb2.length > 0, 'empty-object fallback should be non-empty');
});
