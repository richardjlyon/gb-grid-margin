// site/app.js — the Grid Gauge dashboard renderer.
//
// Two sources, never blended on screen: the LIVE layer (resolveState in live.js, which
// recomputes the verdict in the browser and falls back to the build's latest.json), and
// the settled HISTORY (site/data/*.json from engine/derived.py). app.js owns only the
// presentation; every number it shows comes from one of those, and every figure carries
// its baked source line. Pure maths lives in render.js (unit-tested).
import { resolveState } from './live.js';
import { resolveWarnings } from './warnings.js';
import { shareButtons } from './share.js';
import {
  gaugeNeedleAngle, cfToInk, tallyGroups, firmStatus, sourceArcModel, COL_EXPORT,
  capacityTrapStatic, fmtPct, fmtGW, fmtMW,
} from './render.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 5 * 60 * 1000;

// Gauge view (Using / Generating), persisted like the Subsidy Clock's nominal/real switch.
const VIEW_KEY = 'gg-gauge-view';
const getGaugeView = () => {
  try { return localStorage.getItem(VIEW_KEY) === 'generating' ? 'generating' : 'using'; } catch { return 'using'; }
};
const setGaugeView = (val) => { try { localStorage.setItem(VIEW_KEY, val); } catch { /* private mode */ } };
let LAST_STATE = null;   // last live state, so the toggle can re-render without a refetch

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return r.json();
}

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const srcLine = (txt, anchor) =>
  `<p class="src">Source: ${esc(txt)} · <a href="methodology.html#${anchor}">→ method</a></p>`;

// A full, honest UTC stamp from an ISO instant: "25 Jun 2026 23:35 UTC" (or "" if unparseable).
// Used so every public figure carries a complete timestamp, not a bare HH:MM.
const _MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmtUTC(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getUTCDate())} ${_MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} `
    + `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

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
function buildGauge(value, max, { armed = false, danger = null, reliable = null, label = 'gauge' } = {}) {
  const cx = 100, cy = 104, R = 86;
  const ticks = [];
  for (let v = 0; v <= max; v += max / 6) {
    const [ox, oy] = arcPoint(cx, cy, R + 3, v, max);
    const [ix, iy] = arcPoint(cx, cy, R - 6, v, max);
    ticks.push(`<line x1="${ox.toFixed(1)}" y1="${oy.toFixed(1)}" x2="${ix.toFixed(1)}" y2="${iy.toFixed(1)}" stroke="#565e66" stroke-width="1.4"/>`);
  }
  const [nx, ny] = arcPoint(cx, cy, R - 12, Math.min(value, max), max);
  const needleColor = armed ? '#d6121f' : '#15181c';
  // Coloured zones (firm gauge): red danger below the threshold, green reliable above it.
  // Drawn solid over the grey track; the trap gauge passes neither, so it stays grey.
  const seg = (band, color) => band
    ? `<path d="${arcPath(cx, cy, R, band[0], band[1], max)}" fill="none" stroke="${color}" stroke-width="7"/>`
    : '';
  return `
  <svg class="gauge" viewBox="0 0 200 118" role="img" aria-label="${esc(label)}: ${value.toFixed(1)} of ${max}">
    <path d="${arcPath(cx, cy, R, 0, max, max)}" fill="none" stroke="#d7dbdf" stroke-width="7"/>
    ${seg(reliable, '#1f9d57')}
    ${seg(danger, '#d6121f')}
    ${ticks.join('')}
    <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${needleColor}" stroke-width="3" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="5" fill="${needleColor}"/>
  </svg>`;
}

// The source-mix arc: each slice ∝ output, reliable (green) from the left, unreliable (red) to the
// right, then the magenta export tail beyond the demand mark. `model` is sourceArcModel(v, view).
function buildSourceArc(model, { armed = false } = {}) {
  const cx = 100, cy = 104, R = 86;
  const using = model.view === 'using';
  const ss = model.selfSufficiencyMw;                         // signed net flow (+import / −export)
  // 'using': arc is demand; a surplus spills as a tail beyond it. 'generating': arc is generation;
  // demand is marked on it, with the beyond-demand surplus (export) or the gap to demand (import)
  // flagged on the OUTER edge so the green/red source slices underneath stay intact.
  const demandMw = using ? model.arcTotal : model.arcTotal + ss;
  const total = (using ? model.arcTotal + model.exportMw : model.arcTotal + Math.max(0, ss)) || 1;
  const GAP = total * 0.004;
  const band = (v0, v1, color) =>
    `<path d="${arcPath(cx, cy, R, v0, v1, total)}" fill="none" stroke="${color}" stroke-width="12"/>`;
  const outer = (v0, v1, color) =>
    `<path d="${arcPath(cx, cy, R + 10, v0, v1, total)}" fill="none" stroke="${color}" stroke-width="3.5"/>`;
  const tick = (val, color, len, w) => {
    const [ox, oy] = arcPoint(cx, cy, R + len / 2, val, total);
    const [ix, iy] = arcPoint(cx, cy, R - len / 2, val, total);
    return `<line x1="${ox.toFixed(1)}" y1="${oy.toFixed(1)}" x2="${ix.toFixed(1)}" y2="${iy.toFixed(1)}" stroke="${color}" stroke-width="${w}"/>`;
  };
  let svg = `<path d="${arcPath(cx, cy, R, 0, total, total)}" fill="none" stroke="#eceef0" stroke-width="12"/>`;
  let cum = 0;
  for (const s of model.slices) {
    if (s.mw <= 0) continue;
    const lo = s.mw > GAP * 1.5 ? cum + GAP / 2 : cum;
    const hi = s.mw > GAP * 1.5 ? cum + s.mw - GAP / 2 : cum + s.mw;
    svg += band(lo, hi, s.color);
    cum += s.mw;
  }
  if (using && model.exportMw > 0) {                          // surplus spills beyond the demand arc
    svg += band(model.arcTotal + GAP / 2, total, COL_EXPORT);
    svg += tick(model.arcTotal, '#15181c', 16, 2.2);         // "demand met" divider
  } else if (!using && Math.abs(ss) >= 1) {                   // generating: mark demand + flag the trade
    svg += (ss < 0)
      ? outer(demandMw, model.arcTotal, COL_EXPORT)           // generation beyond demand → exported
      : outer(model.arcTotal, demandMw, '#7d1420');           // generation short of demand → imports filled it
    svg += tick(demandMw, '#15181c', 16, 2.2);               // demand marker
  }
  // Needle points at the firm boundary (where green meets red) — the headline firm share.
  const firmMw = model.slices.filter((s) => s.group === 'reliable').reduce((a, s) => a + s.mw, 0);
  const [nx, ny] = arcPoint(cx, cy, R - 14, firmMw, total);
  const ncol = armed ? '#d6121f' : '#15181c';
  svg += `<line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${ncol}" stroke-width="3" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="5" fill="${ncol}"/>`;
  const basis = model.view === 'using' ? 'share of demand' : 'share of generation';
  return `<svg class="gauge" viewBox="0 0 200 118" role="img" aria-label="Source mix — ${basis}, firm ${model.firmPct}%">${svg}</svg>`;
}

// ============================================================ live entries
let NAMEPLATE = null; // DUKES anchor (sound capacity-trap denominator)

function renderVerdict(state) {
  LAST_STATE = state;   // so the Using/Generating toggle can re-render without a refetch
  const badge = state.mode === 'live' ? 'live'
    : `<span class="modebadge ${state.mode}">${state.mode}</span>`;
  $('verdict-mode').innerHTML = badge;

  if (!state.verdict) {
    $('verdict-body').innerHTML =
      `<p class="warn">No current reading. ${esc(state.reason || state.lastUpdated || '')}</p>`;
    $('entry-trap').hidden = true;
    return;
  }
  const v = state.verdict;
  const view = getGaugeView();
  const m = sourceArcModel(v, view);
  const status = firmStatus(m.firmPct);
  const using = view === 'using';
  // One integer pair so the two stamps always sum to 100 (no 80% + 21% rounding artefact).
  const firmInt = Number.isFinite(m.firmPct) ? Math.round(m.firmPct) : null;
  const firmStamp = firmInt == null ? '—' : `${firmInt}%`;
  const weatherStamp = firmInt == null ? '—' : `${100 - firmInt}%`;

  // Receipt rows derive from the SAME model the arc draws, so the table and the gauge never disagree.
  const rel = m.slices.filter((s) => s.group === 'reliable');
  const unr = m.slices.filter((s) => s.group === 'unreliable');
  const sumMw = (a) => a.reduce((s, x) => s + x.mw, 0);
  const pctOf = (mw) => (m.arcTotal > 0 ? Math.round((mw / m.arcTotal) * 1000) / 10 : NaN);
  const toRow = (s) => ({ fuel: s.label, mw: s.mw, pct: pctOf(s.mw), color: s.color });
  const firmRows = rel.map(toRow);
  const varRows = unr.map(toRow);
  const maxPct = Math.max(...[...firmRows, ...varRows].map((r) => r.pct).filter(Number.isFinite), 1);
  // Each row's bar is its slice colour in the arc, so the receipt doubles as the gauge legend.
  const row = (r) => Number.isFinite(r.pct) ? `
    <tr>
      <td class="fuel">${esc(r.fuel)}</td>
      <td class="n">${fmtMW(r.mw)}</td>
      <td class="n">${fmtPct(r.pct)}</td>
      <td class="bar-cell"><div class="bar" style="width:${(Math.max(0, r.pct) / maxPct * 100).toFixed(0)}%;background:${r.color}"></div></td>
    </tr>` : '';
  const groupHead = (label, mw, pct, red) => `
    <tr class="group ${red ? 'fail' : ''}"><td class="fuel">${label}</td>
      <td class="n">${fmtMW(mw)}</td><td class="n">${fmtPct(pct)}</td><td class="bar-cell"></td></tr>`;

  const netImp = m.selfSufficiencyMw;
  const weatherLabel = using ? 'Weather &amp; imports' : 'Wind &amp; solar';
  const totalLabel = using ? 'National demand' : 'Total generation';
  const ssline = using
    ? (m.exportMw > 0 ? `<p class="ssline export">Exporting ${fmtGW(m.exportMw)} surplus — generated beyond demand</p>` : '')
    : `<p class="ssline">${netImp >= 0 ? `Importing ${fmtGW(netImp)} — short of self-sufficiency` : `Exporting ${fmtGW(-netImp)} — beyond self-sufficiency`}</p>`;
  // The interconnection row has no proportional bar (it isn't part of the 100%), so its bar cell
  // carries a fixed colour swatch as the legend key: magenta for exported surplus, import-red
  // (matching the Imports slice, render.js COL_IMPORTS) for net imports.
  const extra = using
    ? (m.exportMw > 0 ? { label: 'Exported (surplus)', mw: m.exportMw, color: COL_EXPORT } : null)
    : (netImp < 0 ? { label: 'Net exports', mw: -netImp, color: COL_EXPORT }
      : { label: 'Net imports', mw: netImp, color: '#7d1420' });
  const extraRow = extra
    ? `<tr class="export-row"><td class="fuel">${extra.label}</td><td class="n">${fmtMW(extra.mw)}</td><td class="n">—</td><td class="bar-cell"><div class="bar" style="width:16px;background:${extra.color}"></div></td></tr>`
    : '';
  const toggle = `
    <div class="gauge-toggle" role="group" aria-label="Gauge view">
      <button type="button" data-view="using" aria-pressed="${using}"${using ? ' class="on"' : ''}>Using</button>
      <button type="button" data-view="generating" aria-pressed="${!using}"${!using ? ' class="on"' : ''}>Generating</button>
    </div>`;

  $('verdict-body').innerHTML = `
    ${toggle}
    <div class="verdict-cols">
      <div class="verdict-gauge">
        <div class="gauge-block">
          ${buildSourceArc(m, { armed: status.armed })}
          <div class="gauge-zonelabels"><span>Reliable</span><span>Unreliable</span></div>
        </div>
        <div class="stamp-pair">
          <div class="stamp"><span class="stamp-val">${firmStamp}</span>
            <span class="stamp-label">gas/nuclear/biofuel/hydro</span></div>
          <div class="stamp"><span class="stamp-val ${status.armed ? 'red' : ''}">${weatherStamp}</span>
            <span class="stamp-label">${weatherLabel}</span></div>
        </div>
        <p class="status-line ${status.armed ? 'armed' : ''}">Status: ${status.label}</p>
        ${ssline}
      </div>
      <div class="verdict-receipt">
        <table class="receipt">
          <caption>The receipt — ${using ? "what's meeting demand right now" : 'what Britain is generating right now'}</caption>
          <thead><tr><th>Source</th><th>Output</th><th>Share</th><th class="bar-cell"></th></tr></thead>
          <tbody>
            ${groupHead('Gas/nuclear/biofuel/hydro', sumMw(rel), pctOf(sumMw(rel)), false)}
            ${firmRows.map((r) => row(r)).join('')}
            ${groupHead(weatherLabel, sumMw(unr), pctOf(sumMw(unr)), true)}
            ${varRows.map((r) => row(r)).join('')}
            <tr class="total"><td class="fuel">${totalLabel}</td><td class="n">${fmtMW(m.arcTotal)}</td><td class="n">100% ✓</td><td class="bar-cell"></td></tr>
            ${extraRow}
          </tbody>
        </table>
      </div>
    </div>
    ${srcLine(`Elexon FUELINST + NESO embedded · snapshot ${fmtUTC(v.snapshot) || `${String(v.snapshot).slice(11, 16)}Z`}`, 'verdict')}`;

  // share the live firm-power card
  $('verdict-body').insertAdjacentHTML('beforeend', shareButtons(
    { slug: 'firm-now', figure: `${Math.round(m.firmPct)}% firm`,
      label: "of Britain's grid is firm power right now" }));

  $('verdict-body').querySelectorAll('.gauge-toggle button').forEach((b) =>
    b.addEventListener('click', () => { setGaugeView(b.dataset.view); renderVerdict(LAST_STATE); }));

  renderTrap(v);
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

// ============================================================ the reliability stripe (Entry 01, under the gauge)
// The same firm-share measure as the live gauge, every half-hour of the last year. Single red ink,
// inverted: pale (paper) = firm carried demand, deep red = the grid leaned on weather + imports.
// Identical formula to the dial by construction (engine.reliability reuses compute_verdict), so the
// stripe and the gauge above it can never disagree. Canvas, re-binned to its container on resize.
let RELIABILITY = null;
// Firm-share ramp, anchored to the gauge's own 50% arming line: pale only with a clear firm margin
// (>=65%), saturating to full red at/below 40% — so red means "at or past the level where the dial
// itself declares the grid unreliable". Linear, so the key reads as the true transfer function.
const _REL = { LO: 0.40, HI: 0.65, GAMMA: 1.0 };

// firm share s -> colour. Pale at s>=HI (firm carries demand), red at s<=LO. Gaps in grey (distinct
// from 0). s can exceed 1 on net-export half-hours — clamped to the palest (most-reliable) end.
function relColour(s) {
  if (s == null) return '#e8e8e6';
  let t = Math.max(0, Math.min(1, (_REL.HI - s) / (_REL.HI - _REL.LO)));
  t = Math.pow(t, _REL.GAMMA);
  const paper = [251, 251, 249], red = [214, 18, 31];
  const c = [0, 1, 2].map((k) => Math.round(paper[k] + (red[k] - paper[k]) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function drawReliabilityKey() {
  const cv = $('reliability-key');
  if (!cv) return;
  const ctx = cv.getContext('2d'), W = cv.width, H = cv.height;
  // left = 0% unreliable (firm = 1, pale) … right = 100% unreliable (firm = 0, red)
  for (let i = 0; i < W; i++) { ctx.fillStyle = relColour(1 - i / (W - 1)); ctx.fillRect(i, 0, 1, H); }
}

function layoutReliabilityAxis(cssW) {
  const months = $('reliability-months'), years = $('reliability-years');
  if (!months || !years) return;
  months.innerHTML = ''; years.innerHTML = '';
  const start = Date.parse(RELIABILITY.start_utc), step = RELIABILITY.step_minutes * 60000, n = RELIABILITY.values.length;
  let lastX = -999, lastYr = null;
  for (let i = 0; i < n; i++) {
    const d = new Date(start + i * step);
    if (i === 0 || (d.getUTCDate() === 1 && d.getUTCHours() === 0 && d.getUTCMinutes() === 0)) {
      const x = (i / n) * cssW;
      if (x - lastX >= 30) {                              // responsive thinning so labels never collide
        lastX = x;
        const m = document.createElement('span');
        m.textContent = _MONTHS[d.getUTCMonth()].toLowerCase();
        m.style.left = `${x}px`;
        months.appendChild(m);
      }
      if (d.getUTCFullYear() !== lastYr) {                // year marker on every year change
        lastYr = d.getUTCFullYear();
        const y = document.createElement('span');
        y.textContent = lastYr;
        y.style.left = `${x}px`;
        years.appendChild(y);
      }
    }
  }
}

function drawReliabilityStripe() {
  if (!RELIABILITY) return;
  const canvas = $('reliability-canvas');
  if (!canvas) return;
  const vals = RELIABILITY.values, n = vals.length;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  // one column per CSS pixel; mean of the half-hours that fall in it (null where all-blank → gap grey).
  for (let sx = 0; sx < cssW; sx++) {
    const i0 = Math.floor((sx / cssW) * n);
    const i1 = Math.max(i0 + 1, Math.floor(((sx + 1) / cssW) * n));
    let sum = 0, cnt = 0;
    for (let i = i0; i < i1 && i < n; i++) { if (vals[i] != null) { sum += vals[i]; cnt++; } }
    ctx.fillStyle = relColour(cnt ? sum / cnt : null);
    ctx.fillRect(sx, 0, 1, cssH);
  }
  layoutReliabilityAxis(cssW);
}

function renderReliabilityStripe() {
  if (!RELIABILITY) return;
  const r = RELIABILITY;
  $('reliability-body').innerHTML = `
    <div class="rel-strip">
      <div class="rel-head">
        <p class="rel-cap">The same measure, every half-hour of the last year — <strong>pale</strong> where firm power carried demand, <strong>red</strong> where the grid leaned on weather and imports.</p>
        <div class="rel-key">
          <span class="rel-key-lab">unreliable share of demand</span>
          <div class="rel-key-wrap">
            <canvas id="reliability-key" width="300" height="18"></canvas>
            <span class="rel-now" id="reliability-now" hidden>now</span>
          </div>
          <div class="rel-key-ticks"><span>0%</span><span>100%</span></div>
        </div>
      </div>
      <canvas id="reliability-canvas" role="img"
        aria-label="Reliable (firm) share of GB demand, every half-hour from ${esc(r.range.from)} to ${esc(r.range.to)}: pale where firm power carried demand, red where it leaned on weather and imports."></canvas>
      <div class="rel-axis"><div class="rel-months" id="reliability-months"></div><div class="rel-years" id="reliability-years"></div></div>
      <p class="caveat"><strong>Settled history, about three weeks behind live.</strong> The stripe is settled Elexon FUELHH with NESO's embedded outturn estimates; the live gauge and the ‘now’ marker read NESO's embedded <em>forecast</em> — the same measure, a slight forecast-vs-settlement seam, so read ‘now’ as indicative.</p>
      ${srcLine(r.source, 'reliability')}
    </div>`;
  drawReliabilityKey();
  drawReliabilityStripe();
}

// Place the "now" caret on the key at the live reading's position. The stripe is always the
// share-of-demand (Using) basis, so we read firmPct on that basis regardless of the gauge toggle.
// unreliable = 100 − firm; the key runs 0%→100% unreliable left→right, so left% IS that value.
function updateReliabilityNow(state) {
  const el = $('reliability-now');
  if (!el) return;
  const v = state && state.verdict;
  const m = v ? sourceArcModel(v, 'using') : null;
  if (!m || !Number.isFinite(m.firmPct)) { el.hidden = true; return; }
  const unreliable = Math.max(0, Math.min(100, 100 - m.firmPct));
  el.style.left = `${unreliable}%`;
  el.setAttribute('aria-label', `Now: ${Math.round(unreliable)}% unreliable`);
  el.hidden = false;
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

// ============================================================ the live warning light
// Independent of the verdict layer: a warnings fetch failure never touches the verdict, and
// vice versa. Lit only while a scarcity-class notice is in force; otherwise quietly dormant.
// ?warn=force|clear|unavailable forces a state for previewing without waiting for a live notice.
function warnOverride() {
  const v = new URLSearchParams(window.location.search).get('warn');
  if (v === 'force') return { status: 'in_force', type: 'EMN', typeLabel: 'Electricity Margin Notice',
    issuedAt: new Date().toISOString(), window: { from: '19:00', to: '22:00', date: '26/06/2026' } };
  if (v === 'clear') return { status: 'clear' };
  if (v === 'unavailable') return { status: 'unavailable' };
  return null;
}

function renderWarningLight(w) {
  const strip = $('warnstrip');
  const el = $('warning-light');
  strip.dataset.status = w.status;
  if (w.status === 'in_force') {
    const win = w.window ? ` covering ${esc(w.window.from)}–${esc(w.window.to)}, ${esc(w.window.date)}` : '';
    const issued = w.issuedAt && fmtUTC(w.issuedAt) ? ` · issued ${fmtUTC(w.issuedAt)}` : '';
    el.setAttribute('role', 'alert');
    el.innerHTML = `<span class="wl-lamp" aria-hidden="true"></span>
      <span class="wl-text"><strong>${esc(w.typeLabel)} in force</strong>${win}.
        <span class="wl-src">Elexon SYSWARN${issued}</span></span>`;
  } else {
    el.removeAttribute('role');
    const txt = w.status === 'unavailable' ? 'Grid warning status unavailable' : 'No active grid warnings';
    el.innerHTML = `<span class="wl-lamp" aria-hidden="true"></span><span class="wl-text wl-muted">${txt}</span>`;
  }
}

async function refreshWarnings() {
  try {
    renderWarningLight(warnOverride() || await resolveWarnings({}));
  } catch (e) {
    renderWarningLight({ status: 'unavailable' });
  }
}

// ============================================================ orchestration
async function refreshLive() {
  try {
    const state = await resolveState({}, () => Date.now());
    renderVerdict(state);
    updateReliabilityNow(state);
    $('clockstrip').textContent =
      `${state.lastUpdated}`;
    $('freshness').textContent =
      `Live layer: ${state.lastUpdated}. History rebuilt ${STRIPE ? new Date(STRIPE.generated_utc).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : ''}.`;
    $('live-dot').textContent = state.mode === 'live' ? 'Live' : state.mode === 'fallback' ? 'Last good' : 'Offline';
  } catch (e) {
    $('verdict-body').innerHTML = `<p class="warn">Live layer error — no current reading. ${esc(e.message || e)}</p>`;
    $('entry-trap').hidden = true;
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
  // The reliability stripe (Entry 01, under the gauge) is independent: its own fetch so a missing
  // file omits only the stripe, never the live gauge above it.
  try {
    RELIABILITY = await getJSON('data/reliability_year.json');
    renderReliabilityStripe();
  } catch (e) {
    $('reliability-body').innerHTML = '';
  }
  await refreshLive();
  setInterval(refreshLive, POLL_MS);
  refreshWarnings();
  setInterval(refreshWarnings, POLL_MS);
  let t;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => { drawStripe(); drawReliabilityStripe(); }, 150); });
}

main();
