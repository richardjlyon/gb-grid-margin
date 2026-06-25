// site/app.js — the Grid Gauge dashboard renderer.
//
// Two sources, never blended on screen: the LIVE layer (resolveState in live.js, which
// recomputes the verdict in the browser and falls back to the build's latest.json), and
// the settled HISTORY (site/data/*.json from engine/derived.py). app.js owns only the
// presentation; every number it shows comes from one of those, and every figure carries
// its baked source line. Pure maths lives in render.js (unit-tested).
import { resolveState } from './live.js';
import {
  gaugeNeedleAngle, cfToInk, tallyGroups, firmStatus, firmShares,
  capacityTrapStatic, gasVsWindMultiple, fmtPct, fmtGW, fmtMW,
} from './render.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 5 * 60 * 1000;

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return r.json();
}

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const srcLine = (txt, anchor) =>
  `<p class="src">Source: ${esc(txt)} · <a href="methodology.html#${anchor}">→ method</a></p>`;

// ============================================================ the half-dial gauge
function arcPoint(cx, cy, R, value, max) {
  const rad = (gaugeNeedleAngle(value, max) * Math.PI) / 180;
  return [cx + R * Math.sin(rad), cy - R * Math.cos(rad)];
}
function arcPath(cx, cy, R, a, b, max) {
  const [x1, y1] = arcPoint(cx, cy, R, a, max);
  const [x2, y2] = arcPoint(cx, cy, R, b, max);
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}

// A flat half-dial: quiet base arc, an optional red danger arc, hairline ticks, one needle.
// `danger` is a [lo, hi] band shaded red on the dial face; `armed` flips the needle red.
function buildGauge(value, max, { armed = false, danger = null, label = 'gauge' } = {}) {
  const cx = 100, cy = 104, R = 86;
  const ticks = [];
  for (let v = 0; v <= max; v += max / 6) {
    const [ox, oy] = arcPoint(cx, cy, R + 3, v, max);
    const [ix, iy] = arcPoint(cx, cy, R - 6, v, max);
    ticks.push(`<line x1="${ox.toFixed(1)}" y1="${oy.toFixed(1)}" x2="${ix.toFixed(1)}" y2="${iy.toFixed(1)}" stroke="#565e66" stroke-width="1.4"/>`);
  }
  const [nx, ny] = arcPoint(cx, cy, R - 12, Math.min(value, max), max);
  const needleColor = armed ? '#d6121f' : '#15181c';
  const dangerArc = danger
    ? `<path d="${arcPath(cx, cy, R, danger[0], danger[1], max)}" fill="none" stroke="#d6121f" stroke-width="7" opacity="0.18"/>`
    : '';
  return `
  <svg class="gauge" viewBox="0 0 200 118" role="img" aria-label="${esc(label)}: ${value.toFixed(1)} of ${max}">
    <path d="${arcPath(cx, cy, R, 0, max, max)}" fill="none" stroke="#d7dbdf" stroke-width="7"/>
    ${dangerArc}
    ${ticks.join('')}
    <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${needleColor}" stroke-width="3" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="5" fill="${needleColor}"/>
  </svg>`;
}

// ============================================================ live entries
let NAMEPLATE = null; // DUKES anchor (sound capacity-trap denominator)

function renderVerdict(state) {
  const badge = state.mode === 'live' ? 'live'
    : `<span class="modebadge ${state.mode}">${state.mode}</span>`;
  $('verdict-mode').innerHTML = badge;

  if (!state.verdict) {
    $('verdict-body').innerHTML =
      `<p class="warn">No current reading. ${esc(state.reason || state.lastUpdated || '')}</p>`;
    $('entry-trap').hidden = true;
    $('entry-duel').hidden = true;
    return;
  }
  const v = state.verdict;
  const f = firmShares(v);                 // robust to a pre-firm fallback latest.json
  const status = firmStatus(f.firm_pct);
  const d = v.national_demand_mw;
  const share = (mw, pct) => (Number.isFinite(pct) ? pct : (d ? Math.round((mw / d) * 1000) / 10 : NaN));

  // Receipt grouped by the reliability cut: firm (dispatchable, weather-independent) over
  // weather & imports (the correlated-failure bucket). Each group carries a subtotal; the
  // weather & imports subtotal is the red one, tying back to the gauge.
  const firmRows = [
    { fuel: 'Gas (CCGT + OCGT)', mw: v.gas_mw, pct: share(v.gas_mw, v.gas_pct) },
    { fuel: 'Nuclear', mw: v.nuclear_mw, pct: share(v.nuclear_mw, v.nuclear_pct) },
    { fuel: 'Biomass', mw: v.biomass_mw, pct: share(v.biomass_mw, v.biomass_pct) },
    { fuel: 'Hydro & other firm', mw: v.other_mw, pct: share(v.other_mw, v.other_pct) },
  ];
  const varRows = [
    { fuel: 'Wind', mw: v.wind_mw, pct: share(v.wind_mw, v.wind_pct) },
    { fuel: 'Solar', mw: v.solar_mw, pct: share(v.solar_mw, v.solar_pct) },
    { fuel: 'Imports (net)', mw: v.net_import_mw, pct: share(v.net_import_mw, v.import_pct) },
  ];
  const maxPct = Math.max(...[...firmRows, ...varRows].map((r) => r.pct).filter(Number.isFinite), 1);
  const row = (r, red) => Number.isFinite(r.pct) ? `
    <tr>
      <td class="fuel">${esc(r.fuel)}</td>
      <td class="n">${fmtMW(r.mw)}</td>
      <td class="n">${fmtPct(r.pct)}</td>
      <td class="bar-cell"><div class="bar ${red ? 'red' : ''}" style="width:${(Math.max(0, r.pct) / maxPct * 100).toFixed(0)}%"></div></td>
    </tr>` : '';
  const groupHead = (label, mw, pct, red) => `
    <tr class="group ${red ? 'fail' : ''}"><td class="fuel">${label}</td>
      <td class="n">${fmtMW(mw)}</td><td class="n">${fmtPct(pct)}</td><td class="bar-cell"></td></tr>`;

  $('verdict-body').innerHTML = `
    <div class="gauge-block">
      ${buildGauge(f.firm_pct, 100, { armed: status.armed, danger: [0, 40], label: 'Firm power share of demand' })}
      <div class="gauge-zonelabels"><span>Exposed</span><span>Stretched</span><span>Firm</span></div>
    </div>
    <div class="stamp-pair">
      <div class="stamp"><span class="stamp-val">${fmtPct(f.firm_pct)}</span>
        <span class="stamp-label">Firm power</span></div>
      <div class="stamp"><span class="stamp-val ${status.armed ? 'red' : ''}">${fmtPct(f.notfirm_pct)}</span>
        <span class="stamp-label">Weather &amp; imports</span></div>
    </div>
    <p class="status-line ${status.armed ? 'armed' : ''}">Status: ${status.label}</p>
    <table class="receipt">
      <caption>The receipt — what's meeting demand right now</caption>
      <thead><tr><th>Source</th><th>Output</th><th>Share</th><th class="bar-cell"></th></tr></thead>
      <tbody>
        ${groupHead('Firm power', f.firm_mw, f.firm_pct, false)}
        ${firmRows.map((r) => row(r, false)).join('')}
        ${groupHead('Weather &amp; imports', f.notfirm_mw, f.notfirm_pct, true)}
        ${varRows.map((r) => row(r, true)).join('')}
        <tr class="total"><td class="fuel">National demand</td><td class="n">${fmtMW(v.national_demand_mw)}</td><td class="n">100% ✓</td><td class="bar-cell"></td></tr>
      </tbody>
    </table>
    ${srcLine(`Elexon FUELINST + NESO embedded · snapshot ${String(v.snapshot).slice(11, 16)}Z`, 'verdict')}`;

  renderTrap(v);
  renderDuel(v);
}

function renderTrap(v) {
  $('entry-trap').hidden = false;
  const built = NAMEPLATE ? NAMEPLATE.wind_plus_solar_gw : 50.362;
  const delivering = (v.wind_mw || 0) + (v.solar_mw || 0);
  const t = capacityTrapStatic(delivering, built);
  $('trap-body').innerHTML = `
    <div class="gauge-block">
      ${buildGauge(t.share_pct, 100, { label: 'Wind and solar output as a share of installed capacity' })}
    </div>
    <p class="duel-punch">Britain has built <strong>${built.toFixed(1)} GW</strong> of wind and solar.
      Right now the whole fleet is delivering <strong>${fmtGW(delivering)}</strong> — just
      <strong>${fmtPct(t.share_pct)}</strong> of what's installed.</p>
    ${srcLine('Elexon FUELINST + NESO embedded output ÷ DUKES 6.2 nameplate (UK, end-2024)', 'capacity-trap')}`;
}

function renderDuel(v) {
  // Shown only while the gas fleet genuinely out-produces all wind (never a false claim).
  if (!(Number.isFinite(v.gas_mw) && Number.isFinite(v.wind_mw) && v.gas_mw > v.wind_mw)) {
    $('entry-duel').hidden = true;
    return;
  }
  $('entry-duel').hidden = false;
  const scale = Math.max(v.gas_mw, v.wind_mw, 1);
  const mult = gasVsWindMultiple(v.gas_mw, v.wind_mw);
  $('duel-body').innerHTML = `
    <div class="duel">
      <div class="duel-row"><span class="lab">Every wind farm</span>
        <div class="duel-bar red" style="width:${(v.wind_mw / scale * 100).toFixed(0)}%"></div>
        <span class="amt">${fmtGW(v.wind_mw)}</span></div>
      <div class="duel-row"><span class="lab">Gas fleet</span>
        <div class="duel-bar" style="width:${(v.gas_mw / scale * 100).toFixed(0)}%"></div>
        <span class="amt">${fmtGW(v.gas_mw)}</span></div>
    </div>
    <p class="duel-punch">Every wind farm in Britain is delivering ${fmtGW(v.wind_mw)}.
      The gas fleet is delivering ${fmtGW(v.gas_mw)}${mult ? ` — <strong>${mult.toFixed(1)}× more</strong>` : ''}.</p>
    ${srcLine('Elexon FUELINST — total WIND vs CCGT + OCGT, same snapshot', 'gas-vs-wind')}`;
}

// ============================================================ the wind stripe
let STRIPE = null;
function drawStripe() {
  if (!STRIPE) return;
  const canvas = $('stripe-canvas');
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const days = STRIPE.days;
  const n = days.length;
  const railH = 14;                       // foot-tick rail
  const bandH = cssH - railH;
  const colW = cssW / n;

  // band: one ink-ramp column per day. Darkest-wins downsample so a sub-pixel calm day
  // is never averaged out of existence.
  const px = Math.max(1, Math.floor(colW));
  for (let sx = 0; sx < cssW; sx++) {
    const i0 = Math.floor((sx / cssW) * n);
    const i1 = Math.max(i0 + 1, Math.floor(((sx + 1) / cssW) * n));
    let minCf = Infinity;
    for (let i = i0; i < i1 && i < n; i++) minCf = Math.min(minCf, days[i].cf);
    if (!Number.isFinite(minCf)) continue;
    ctx.fillStyle = cfToInk(minCf);
    ctx.fillRect(sx, 0, 1, bandH);
  }

  // foot-tick rail: every sub-10% day a red tick; sub-5% a taller deep-red tick.
  for (let i = 0; i < n; i++) {
    const cf = days[i].cf;
    if (cf >= 0.10) continue;
    const x = i * colW;
    const sub5 = cf < 0.05;
    ctx.fillStyle = sub5 ? '#a8101b' : '#d6121f';
    ctx.fillRect(x, bandH + (sub5 ? 0 : 4), Math.max(0.6, colW), sub5 ? railH : railH - 4);
  }

  // per-year mean step-line over the band (ink), 0–0.55 scale.
  const means = STRIPE.per_year_mean_cf;
  ctx.strokeStyle = '#15181c';
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < n; i++) {
    const yr = days[i].date.slice(0, 4);
    const m = means[yr];
    if (m == null) continue;
    const x = i * colW;
    const y = bandH - Math.min(1, m / 0.55) * bandH;
    if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
  }
  ctx.stroke();

  // today marker: the latest settled day, tying the history hero to the live edge.
  ctx.strokeStyle = '#d6121f';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cssW - 0.75, 0);
  ctx.lineTo(cssW - 0.75, bandH);
  ctx.stroke();
}

function renderStripe() {
  if (!STRIPE) return;
  const yrs = Object.keys(STRIPE.per_year_mean_cf);
  const meanRow = yrs.map((y) => {
    const partial = (STRIPE.partial_years || []).includes(Number(y));
    return `${y.slice(2)} <b>${STRIPE.per_year_mean_cf[y].toFixed(3)}</b>${partial ? '*' : ''}`;
  }).join(' · ');
  const axisYears = yrs.filter((_, i) => i % 2 === 0).map((y) => `<span>’${y.slice(2)}</span>`).join('');

  $('stripe-body').innerHTML = `
    <div class="stripe-wrap">
      <div class="stripe-meanrow"><span>Per-year mean capacity factor:</span> ${meanRow}
        ${(STRIPE.partial_years || []).length ? '<span>(* part-year)</span>' : ''}</div>
      <canvas id="stripe-canvas" role="img"
        aria-label="Daily wind capacity factor, ${esc(STRIPE.range.from)} to ${esc(STRIPE.range.to)}: dark columns are low-wind days. Mean ${STRIPE.mean_cf}."></canvas>
      <div class="stripe-axis">${axisYears}<span>today</span></div>
      <div class="stripe-legend">
        <span><span class="swatch" style="background:#15181c"></span>calm (low wind)</span>
        <span><span class="swatch" style="background:#eaecee"></span>windy</span>
        <span><span class="tick-mark"></span>day below 10% of capacity</span>
        <span><span class="tick-mark deep"></span>below 5%</span>
        <span>— ink line: each year's mean</span>
      </div>
    </div>
    <p class="caveat"><strong>Read within a year, not across.</strong> ${esc(STRIPE.cross_year_caveat)}</p>
    <p class="src">Mean CF ${STRIPE.mean_cf} · <strong>conservative lower bound</strong> ·
      ${esc(STRIPE.source)} · <a href="methodology.html#stripe">→ method</a></p>`;
  drawStripe();
}

// ============================================================ the tally + records
function renderTally(counters, records) {
  const years = Object.keys(counters.years);
  const rows = years.map((y) => {
    const c = counters.years[y];
    const partial = (counters.partial_years || []).includes(Number(y));
    // gate-of-five strokes for sub-10% days; the last sub-5% of them struck red.
    const groups = tallyGroups(c.below_10pct);
    let drawn = 0;
    const redFrom = c.below_10pct - c.below_5pct;
    const marks = groups.map((g) => {
      let span = '';
      for (let k = 0; k < g; k++) { span += `<span class="mark ${drawn >= redFrom ? 'sub5' : ''}"></span>`; drawn++; }
      return span;
    }).join('<span class="mark-gap"></span>');
    return `<tr class="${partial ? 'partial' : ''}">
      <td class="year">${y}</td>
      <td class="marks">${marks}</td>
      <td class="n">${c.below_10pct}</td>
      <td class="n red">${c.below_5pct}</td></tr>`;
  }).join('');

  const r = records;
  $('tally-body').innerHTML = `
    <table class="tally">
      <thead><tr><th>Year</th><th>Days below 10% (red strokes: below 5%)</th><th>&lt;10%</th><th>&lt;5%</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="records">
      <p class="rec">Lowest day ever: <b>${(r.lowest_cf_day.cf * 100).toFixed(1)}%</b> of capacity on ${esc(r.lowest_cf_day.date)}.</p>
      <p class="rec">Longest run below 10%: <b>${r.longest_sub10pct_run.days} days</b> (${esc(r.longest_sub10pct_run.start)} → ${esc(r.longest_sub10pct_run.end)}).</p>
      <p class="caveat"><strong>Both fall in the earliest, most-understated years.</strong> ${esc(records.cross_year_caveat)}</p>
    </div>
    ${srcLine(`${counters.source} · conservative lower bound`, 'stripe')}`;
}

// ============================================================ orchestration
async function refreshLive() {
  try {
    const state = await resolveState({}, () => Date.now());
    renderVerdict(state);
    $('clockstrip').textContent =
      `${state.lastUpdated}`;
    $('freshness').textContent =
      `Live layer: ${state.lastUpdated}. History rebuilt ${STRIPE ? new Date(STRIPE.generated_utc).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : ''}.`;
    $('live-dot').textContent = state.mode === 'live' ? 'Live' : state.mode === 'fallback' ? 'Last good' : 'Offline';
  } catch (e) {
    $('verdict-body').innerHTML = `<p class="warn">Live layer error — no current reading. ${esc(e.message || e)}</p>`;
    $('entry-trap').hidden = true; $('entry-duel').hidden = true;
  }
}

async function main() {
  // History first (static, always available); then the live layer on top.
  try {
    const [stripe, counters, records, nameplate] = await Promise.all([
      getJSON('data/stripe.json'), getJSON('data/counters.json'),
      getJSON('data/records.json'), getJSON('data/nameplate.json'),
    ]);
    STRIPE = stripe; NAMEPLATE = nameplate;
    renderStripe();
    renderTally(counters, records);
  } catch (e) {
    // Any history feed failing degrades both history entries gracefully — never a blank
    // section. The live layer below still renders independently.
    const msg = `<p class="warn">History data unavailable — the live readings below are unaffected. ${esc(e.message || e)}</p>`;
    $('stripe-body').innerHTML = msg;
    $('tally-body').innerHTML = msg;
  }
  await refreshLive();
  setInterval(refreshLive, POLL_MS);
  let t;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(drawStripe, 150); });
}

main();
