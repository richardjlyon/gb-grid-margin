// site/app.js — the Grid Gauge dashboard renderer.
//
// Two sources, never blended on screen: the LIVE layer (resolveState in live.js, which
// recomputes the verdict in the browser and falls back to the build's latest.json), and
// the settled HISTORY (site/data/*.json from engine/derived.py). app.js owns only the
// presentation; every number it shows comes from one of those, and every figure carries
// its baked source line. Pure maths lives in render.js (unit-tested).
import { resolveState } from './live.js';
import { resolveWarnings } from './warnings.js';
import {
  gaugeNeedleAngle, firmStatus, sourceArcModel, COL_EXPORT,
  fmtGW, fmtMW,
  unreliableNowPct,
  carpetCellColor, gaugeCalibration, unreliabilityColor,
  windDroughtColor, droughtSpikes, droughtCaption, carpetMonthTicks,
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

// A flat half-dial: quiet base arc, optional coloured zone arcs, hairline ticks, one needle.
// `danger` / `reliable` are [lo, hi] bands on the dial face; `armed` flips the needle red.
// `calibration` is the array from gaugeCalibration(nameplateMw): inner-% + outer-MW labels.
// `dist` = {p10,p25,p50,p75,p90} (percentages) paints the rolling-year output distribution onto the
// circumference: a faint p10–p90 arc (9 times in 10), a stronger p25–p75 arc (the usual half), and a
// median tick — so the live needle reads against where output normally sits.
// `trackRamp` (t in [0,1] -> [r,g,b]) paints the base arc as a green->amber->red gradient (the
// unreliability gauge): 0% = green/reliable, 100% = red/unreliable. When set, the percentile band
// arcs are suppressed (the gradient would muddy them; the legend box-plot carries the distribution),
// but the mean tick + needle stay so "now" still reads against the rolling-year average.
function buildGauge(value, max, { armed = false, danger = null, reliable = null,
                                  calibration = null, label = 'gauge', dist = null, trackRamp = null,
                                  palette = { track: '#d7dbdf', band: '#b4bac1', core: '#7c838a' } } = {}) {
  const cx = 100, cy = 104, R = 86;
  const ticks = [];
  for (let v = 0; v <= max; v += max / 4) {   // ticks at 0/25/50/75/100, aligned with the labels
    const [ox, oy] = arcPoint(cx, cy, R + 3, v, max);
    const [ix, iy] = arcPoint(cx, cy, R - 6, v, max);
    ticks.push(`<line x1="${ox.toFixed(1)}" y1="${oy.toFixed(1)}" x2="${ix.toFixed(1)}" y2="${iy.toFixed(1)}" stroke="#565e66" stroke-width="1.4"/>`);
  }
  const [nx, ny] = arcPoint(cx, cy, R - 12, Math.min(value, max), max);
  const needleColor = armed ? '#d6121f' : '#15181c';
  const seg = (band, color) => band
    ? `<path d="${arcPath(cx, cy, R, band[0], band[1], max)}" fill="none" stroke="${color}" stroke-width="7"/>`
    : '';
  let distArcs = '', median = '';
  if (dist) {
    if (!trackRamp) {   // percentile band arcs would muddy a gradient track — suppress them there
      const arc = (lo, hi, color) => `<path d="${arcPath(cx, cy, R, lo, hi, max)}" fill="none" stroke="${color}" stroke-width="7"/>`;
      distArcs = arc(dist.p10, dist.p90, palette.band) + arc(dist.p25, dist.p75, palette.core);  // 9-in-10, then the usual half
    }
    const c = Number.isFinite(dist.mean) ? dist.mean : dist.p50;   // central tick = the average (load factor)
    const [mx1, my1] = arcPoint(cx, cy, R + 5, c, max);
    const [mx2, my2] = arcPoint(cx, cy, R - 5, c, max);
    median = `<line x1="${mx1.toFixed(1)}" y1="${my1.toFixed(1)}" x2="${mx2.toFixed(1)}" y2="${my2.toFixed(1)}" stroke="#15181c" stroke-width="2.2"/>`;
  }
  // Base arc: a single quiet track, or a green->amber->red gradient (drawn as contiguous segments,
  // since SVG strokes can't follow an arc with a gradient) when trackRamp is given.
  let trackArc;
  if (trackRamp) {
    const N = 30, segs = [];
    for (let i = 0; i < N; i++) {
      const [r, g, b] = trackRamp((i + 0.5) / N);
      segs.push(`<path d="${arcPath(cx, cy, R, (i / N) * max, ((i + 1) / N) * max, max)}" fill="none" stroke="rgb(${r},${g},${b})" stroke-width="7"/>`);
    }
    trackArc = segs.join('');
  } else {
    trackArc = `<path d="${arcPath(cx, cy, R, 0, max, max)}" fill="none" stroke="${palette.track}" stroke-width="7"/>`;
  }
  let cal = '';
  if (calibration) {
    for (const t of calibration) {
      const v = t.frac * max;
      const [ix, iy] = arcPoint(cx, cy, R - 17, v, max);
      cal += `<text x="${ix.toFixed(1)}" y="${(iy + 3).toFixed(1)}" class="g-pct" text-anchor="middle">${t.label_pct}</text>`;
      // Skip the outer MW label when there is no nameplate (e.g. the reliability dial): keep the inner %.
      if (t.label_mw == null) continue;
      if (t.pct === 0 || t.pct === 100) {
        const [ox, oy] = arcPoint(cx, cy, R + 15, v, max);
        cal += `<text x="${ox.toFixed(1)}" y="${(oy + 11).toFixed(1)}" class="g-mw" text-anchor="middle">${t.label_mw}${t.pct === 100 ? ' MW' : ''}</text>`;
      } else if (t.pct === 50) {
        // The peak (50%-mark) power figure sits clearly above the dial, well clear of the "50%" label.
        const [ox, oy] = arcPoint(cx, cy, R + 18, v, max);
        cal += `<text x="${ox.toFixed(1)}" y="${(oy - 2).toFixed(1)}" class="g-mw" text-anchor="middle">${t.label_mw}</text>`;
      }
    }
  }
  return `
  <svg class="gauge" viewBox="-6 -12 232 130" role="img" aria-label="${esc(label)}: ${value.toFixed(1)} of ${max}">
    ${trackArc}
    ${distArcs}
    ${seg(reliable, '#1f9d57')}
    ${seg(danger, '#d6121f')}
    ${ticks.join('')}
    ${median}
    ${cal}
    <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${needleColor}" stroke-width="3" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="5" fill="${needleColor}"/>
  </svg>`;
}

// Whole-percent shares via largest remainder: floor each share, then hand the leftover percent(s) to
// the largest fractional parts (or claw back if the floors overshoot). Guarantees a column of integer
// percentages sums to exactly 100. Returns a Map keyed by the slice object.
function integerShares(slices, total) {
  const out = new Map();
  if (!(total > 0)) { slices.forEach((s) => out.set(s, 0)); return out; }
  const raw = slices.map((s) => (Math.max(0, s.mw) / total) * 100);
  const floor = raw.map(Math.floor);
  let rem = 100 - floor.reduce((a, b) => a + b, 0);
  const order = raw.map((r, i) => ({ i, frac: r - Math.floor(r) })).sort((a, b) => b.frac - a.frac);
  for (let k = 0; rem > 0 && k < order.length; k++) { floor[order[k].i] += 1; rem -= 1; }
  for (let k = order.length - 1; rem < 0 && k >= 0; k--) { if (floor[order[k].i] > 0) { floor[order[k].i] -= 1; rem += 1; } }
  slices.forEach((s, i) => out.set(s, floor[i]));
  return out;
}

// The source-mix arc (share of demand): each slice ∝ output, reliable (green) from the left,
// unreliable (red) to the right, then the magenta export tail beyond the demand mark when Britain is
// exporting a surplus. `model` is sourceArcModel(v).
function buildSourceArc(model, { armed = false } = {}) {
  const cx = 100, cy = 104, R = 86;
  const total = (model.arcTotal + model.exportMw) || 1;       // demand, plus any exported-surplus tail
  const GAP = total * 0.004;
  const band = (v0, v1, color) =>
    `<path d="${arcPath(cx, cy, R, v0, v1, total)}" fill="none" stroke="${color}" stroke-width="12"/>`;
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
  if (model.exportMw > 0) {                                   // surplus spills beyond the demand arc
    svg += band(model.arcTotal + GAP / 2, total, COL_EXPORT);
    svg += tick(model.arcTotal, '#15181c', 16, 2.2);         // "demand met" divider
  }
  // Inner group-indicator arc, set in a little from the outer ring: green = reliable share of demand,
  // red = unreliable share. The outer ring now carries per-source colours, so this is the two-colour
  // reliable/unreliable read. firmMw = where reliable meets unreliable.
  const firmMw = model.slices.filter((s) => s.group === 'reliable').reduce((a, s) => a + s.mw, 0);
  const Ri = 66, IGAP = total * 0.006;
  const inner = (v0, v1, color) =>
    `<path d="${arcPath(cx, cy, Ri, v0, v1, total)}" fill="none" stroke="${color}" stroke-width="7"/>`;
  if (firmMw > IGAP) svg += inner(0, firmMw - IGAP / 2, '#1b6e45');                       // reliable (green)
  if (model.arcTotal - firmMw > IGAP) svg += inner(firmMw + IGAP / 2, model.arcTotal, '#d6121f'); // unreliable (red)
  // Needle points at the firm boundary; shortened to sit just inside the inner arc.
  const [nx, ny] = arcPoint(cx, cy, Ri - 6, firmMw, total);
  const ncol = armed ? '#d6121f' : '#15181c';
  svg += `<line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${ncol}" stroke-width="3" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="5" fill="${ncol}"/>`;
  return `<svg class="gauge" viewBox="0 0 200 118" role="img" aria-label="Source mix — share of demand, firm ${model.firmPct}%">${svg}</svg>`;
}

// ============================================================ live entries
let NAMEPLATE = null; // DUKES anchor (sound capacity-trap denominator)

function renderVerdict(state) {
  const badge = state.mode === 'live' ? ''   // live is the normal state — no label, only flag the abnormal
    : `<span class="modebadge ${state.mode}">${state.mode}</span>`;
  $('verdict-mode').innerHTML = badge;

  if (!state.verdict) {
    $('verdict-body').innerHTML =
      `<p class="warn">No current reading. ${esc(state.reason || state.lastUpdated || '')}</p>`;
    $('entry-trap').hidden = true;
    renderReliabilityBlock(null);
    return;
  }
  const v = state.verdict;
  const m = sourceArcModel(v);
  const status = firmStatus(m.firmPct);

  // Receipt rows derive from the SAME model the arc draws, so the table and the gauge never disagree.
  const rel = m.slices.filter((s) => s.group === 'reliable');
  const unr = m.slices.filter((s) => s.group === 'unreliable');
  const sumMw = (a) => a.reduce((s, x) => s + x.mw, 0);
  // Whole-percent shares (largest remainder) so the displayed integers sum to exactly 100.
  const pctByKey = integerShares(m.slices, m.arcTotal);
  const groupPct = (a) => a.reduce((s, x) => s + (pctByKey.get(x) || 0), 0);
  const toRow = (s) => ({ fuel: s.label, mw: s.mw, pct: pctByKey.get(s) || 0, color: s.color });
  const firmRows = rel.map(toRow);
  const varRows = unr.map(toRow);
  const relPct = groupPct(rel);            // reliable + unreliable = 100 by construction
  const unrPct = groupPct(unr);
  const firmStamp = `${relPct}%`;
  const weatherStamp = `${unrPct}%`;
  const maxPct = Math.max(...[...firmRows, ...varRows].map((r) => r.pct), 1);
  // Each row's bar is its slice colour in the arc, so the receipt doubles as the gauge legend.
  const row = (r) => Number.isFinite(r.pct) ? `
    <tr>
      <td class="fuel">${esc(r.fuel)}</td>
      <td class="n">${fmtMW(r.mw)}</td>
      <td class="n">${r.pct}%</td>
      <td class="bar-cell"><div class="bar" style="width:${(Math.max(0, r.pct) / maxPct * 100).toFixed(0)}%;background:${r.color}"></div></td>
    </tr>` : '';
  const groupHead = (label, mw, pct, tone) => `
    <tr class="group ${tone || ''}"><td class="fuel">${label}</td>
      <td class="n">${fmtMW(mw)}</td><td class="n">${pct}%</td><td class="bar-cell"></td></tr>`;

  const weatherLabel = 'Weather &amp; imports';
  const totalLabel = 'National demand';
  const ssline = m.exportMw > 0
    ? `<p class="ssline export">Exporting ${fmtGW(m.exportMw)} surplus — generated beyond demand</p>` : '';
  // The interconnection row has no proportional bar (it isn't part of the 100%), so its bar cell
  // carries a fixed colour swatch as the legend key: magenta for an exported surplus (COL_EXPORT).
  const extra = m.exportMw > 0 ? { label: 'Exported (surplus)', mw: m.exportMw, color: COL_EXPORT } : null;
  const extraRow = extra
    ? `<tr class="export-row"><td class="fuel">${extra.label}</td><td class="n">${fmtMW(extra.mw)}</td><td class="n">—</td><td class="bar-cell"><div class="bar" style="width:16px;background:${extra.color}"></div></td></tr>`
    : '';

  $('verdict-body').innerHTML = `
    <div class="verdict-cols">
      <div class="verdict-gauge">
        <div class="gauge-block">
          ${buildSourceArc(m, { armed: status.armed })}
          <div class="gauge-zonelabels"><span>Reliable</span><span>Unreliable</span></div>
        </div>
        <div class="stamp-pair">
          <div class="stamp"><span class="stamp-val reliable">${firmStamp}</span>
            <span class="stamp-label">gas/nuclear/biofuel/hydro</span></div>
          <div class="stamp"><span class="stamp-val unreliable">${weatherStamp}</span>
            <span class="stamp-label">${weatherLabel}</span></div>
        </div>
        ${ssline}
      </div>
      <div class="verdict-receipt">
        <table class="receipt">
          <caption>The receipt — what's meeting demand right now</caption>
          <thead><tr><th>Source</th><th>Output</th><th>Share</th><th class="bar-cell"></th></tr></thead>
          <tbody>
            ${groupHead('Reliable', sumMw(rel), relPct, 'pass')}
            ${firmRows.map((r) => row(r)).join('')}
            ${groupHead('Unreliable', sumMw(unr), unrPct, 'fail')}
            ${varRows.map((r) => row(r)).join('')}
            <tr class="total"><td class="fuel">${totalLabel}</td><td class="n">${fmtMW(m.arcTotal)}</td><td class="n">100% ✓</td><td class="bar-cell"></td></tr>
            ${extraRow}
          </tbody>
        </table>
      </div>
    </div>
    ${srcLine(`Elexon FUELINST + NESO embedded · snapshot ${fmtUTC(v.snapshot) || `${String(v.snapshot).slice(11, 16)}Z`}`, 'verdict')}`;

  renderTrap(v);
  renderReliabilityBlock(v);
}

// Per-source colour identities. The dial bands use three shades (track / 9-in-10 / usual-half), luma-
// matched to the original greys (218/185/130) so perceived brightness is unchanged; `full` (+ fullRgb)
// is the saturated end of the carpet & legend ramp (white = no output → this hue = full output).
// Blue = wind, yellowy-orange = solar.
const DIAL_PALETTE = {
  wind: { track: '#cbdef0', band: '#9cbfe3', core: '#4e8dcd', full: '#1f6fc0', fullRgb: [31, 111, 192] },
  solar: { track: '#e8d9be', band: '#d4b684', core: '#b17c23', full: '#e0921a', fullRgb: [224, 146, 26] },
};

// Reliability dial/carpet — single red. Bands behind the needle are red-tinted greys (luma-matched
// to the wind/solar band greys); full = the gauge's unreliable red.
const REL_PALETTE = { track: '#e3d2d4', band: '#cda9ad', core: '#b3565d', full: '#d6121f', fullRgb: [214, 18, 31] };

// Entry 02 source lines + the box-whisker key note, lifted to module scope so the shared
// renderMetricBlock references them by name rather than closing over renderTrap.
const WIND_GAUGE_SRC = 'Live: Elexon FUELINST + NESO embedded forecast / DUKES 6.2 wind nameplate';
const SOLAR_GAUGE_SRC = 'Live: NESO embedded forecast / NESO embedded-solar capacity';
// A single annotation — under solar only, to conserve space — explaining the hybrid box-whisker
// key that sits above each carpet (it serves both sources and the dial bands, same scheme).
// A compact visual key for the box-plot under every carpet legend. Shown ONCE (under the first
// block on the page) rather than repeated as prose in each section: the mini-glyphs mirror the
// actual marks, so the legend reads itself. The full sentence lives in the aria-label for AT.
const KEY_NOTE_HTML = `<div class="legend-key" role="img" aria-label="Key to the box-plot below each carpet legend: the thin line spans the middle 9 in 10 half-hours over the last year; the thick bar the usual half (the middle 50% of readings); the tick the average; the now caret and the dial needle mark the latest half-hour.">
        <span class="lk-cap">The box-plot below each legend:</span>
        <span class="lk-item"><span class="lk-g lk-whisker"></span>9 in 10</span>
        <span class="lk-item"><span class="lk-g lk-bar"></span>usual half</span>
        <span class="lk-item"><span class="lk-g lk-avg"></span>average</span>
        <span class="lk-item"><span class="lk-g lk-now"></span>now &middot; dial needle</span>
      </div>`;

// Lay out the legend's numeric percentile markers (positions in bar-%), dropping any lower-priority
// label that would collide with a kept one — e.g. solar's all-hours median 0% sitting on top of its
// 0% lower quartile. Median wins (pr 2) over the quartile ends (pr 1).
const _NUM_MINGAP = 7;   // bar-% within which two labels would overlap
function numsRow(marks) {
  const kept = [];
  for (const m of [...marks].sort((a, b) => b.pr - a.pr)) {
    if (kept.every((k) => Math.abs(k.pos - m.pos) >= _NUM_MINGAP)) kept.push(m);
  }
  kept.sort((a, b) => a.pos - b.pos);
  const span = (m) => `<span class="cl-num ${m.cls || ''}" style="left:${m.pos.toFixed(1)}%${m.color ? `; color:${m.color}` : ''}">${m.txt}</span>`;
  return `<span class="cl-nums" aria-hidden="true">${kept.map(span).join('')}</span>`;
}

// Each source gets its own colour legend, sharing its label's row in the stripe column (so it is
// the same width as the stripe below it) and carrying a live "now" caret at the instantaneous
// capacity-factor reading — the same value the dial needle points to. `satFull` is the carpet's
// saturation anchor (CAPACITY.sat[kind] for Entry 02), passed in so the legend closes over nothing.
// `ramp` (optional) recolours the legend for the unreliability block: {css} is the green->amber->red
// gradient for the bar, {lo,hi} are the end labels ("Reliable" / "Unreliable" rather than the default
// "No output" / "Full output"). The box-plot then draws in neutral slate/ink so it reads cleanly over
// the coloured ramp instead of competing with it.
function legendFor(kind, cf, pal, dist, satFull, unitNoun, ramp) {
  const noun = unitNoun || 'capacity';
  const boxBand = ramp ? '#9aa3ab' : pal.band, boxCore = ramp ? '#4b535b' : pal.core;
  const barCss = ramp ? ramp.css : `linear-gradient(90deg in oklab, #fbfbf9, ${pal.full})`;
  const loLab = ramp ? ramp.lo : 'No output', hiLab = ramp ? ramp.hi : 'Full output';
  const L = (frac) => Math.max(0, Math.min(100, (frac / satFull) * 100));   // a 0..1 cf -> bar %
  const pos = L(cf);
  // distribution box-plot below the bar (same scale, recoloured into the source hue to match the
  // dial bands): p10–p90 whisker (pal.band), p25–p75 usual half (pal.core), and an AVERAGE tick
  // (ink) — the mean / load factor, not the median (see distForDays). Numbers label the 9-in-10 ends
  // and the average.
  let box = '';
  if (dist) {
    const x = (pPct) => L(pPct / 100);   // dist percentiles are 0..100
    const [p10, p90] = [dist.p10, dist.p90].map(Math.round);
    const [p25, p75] = [dist.p25, dist.p75].map(Math.round);
    const avg = Math.round(dist.mean);
    box = `
        <span class="cl-box" aria-hidden="true" title="last year: average ${avg}%, usual half ${p25}-${p75}%, 9-in-10 ${p10}-${p90}% of ${noun}">
          <span class="cl-box-line" style="left:${x(dist.p10).toFixed(1)}%; width:${(x(dist.p90) - x(dist.p10)).toFixed(1)}%; background:${boxBand}"></span>
          <span class="cl-box-iqr" style="left:${x(dist.p25).toFixed(1)}%; width:${(x(dist.p75) - x(dist.p25)).toFixed(1)}%; background:${boxCore}"></span>
          <span class="cl-box-avg" style="left:${x(dist.mean).toFixed(1)}%"></span>
        </span>
        ${numsRow([
          { pos: x(dist.p10), txt: `${p10}%`, color: boxCore, pr: 1 },   // widest interval (9-in-10) ends
          { pos: x(dist.mean), txt: `${avg}%`, cls: 'cl-num-avg', pr: 2 },  // average (mean / load factor)
          { pos: x(dist.p90), txt: `${p90}%`, color: boxCore, pr: 1 },
        ])}`;
  }
  return `
    <div class="carpet-legend">
      <span class="cl-lab">${loLab}</span>
      <span class="cl-bar-wrap">
        <span class="cl-bar" style="background:${barCss}" aria-hidden="true"></span>
        <span class="cl-now" style="left:${pos.toFixed(1)}%" title="Now: ${Math.round(cf * 100)}% of ${noun}">now</span>
        ${box}
      </span>
      <span class="cl-lab">${hiLab}</span>
    </div>`;
}

// Output distribution over the rolling year (half-hourly cells) — painted onto the dial so "now"
// reads against where output sits. The CENTRAL marker is the MEAN (= the load factor / annual
// capacity factor), not the median: solar is dark over half the year, so its median is 0% — a fact
// about the Earth's rotation, not about the panels. The mean is the fair, standard "what it
// delivers" figure. The percentile band stays as the variability picture. Memoised on `node._dist`.
function distForDays(node, days) {
  if (node._dist) return node._dist;
  if (!days || !days.length) return null;
  const vals = [];
  for (const d of days) for (const cf of d.cf) if (cf != null) vals.push(cf);
  if (!vals.length) return null;
  const mean = (vals.reduce((s, v) => s + v, 0) / vals.length) * 100;
  vals.sort((a, b) => a - b);
  const q = (p) => vals[Math.min(vals.length - 1, Math.floor(p * vals.length))] * 100;
  return (node._dist = { p10: q(0.1), p25: q(0.25), p50: q(0.5), p75: q(0.75), p90: q(0.9), mean });
}

// Mean capacity factor over the rolling year (all half-hourly cells) — the "rarely tops a quarter"
// fact, stated in the label row beside the live dial.
function avgFromDays(days) {
  if (!days) return null;
  let s = 0, n = 0;
  for (const d of days) for (const cf of d.cf) if (cf != null) { s += cf; n += 1; }
  return n ? Math.round((s / n) * 100) : null;
}

// The shared metric block: full-width source label row, the live dial (1/3 column) beside its
// half-hourly carpet (2/3 column), then an aligned row of source lines. Closes over no Entry-02
// globals — everything comes from `cfg` — so a later entry can reuse it with its own palette,
// nameplate and series. Returns the HTML string; the CALLER paints the carpet canvas afterwards.
function renderMetricBlock(cfg) {
  const pal = cfg.palette;
  const hasCarpet = !!(cfg.days && cfg.days.length);
  // A traffic-light block (reliability) supplies cfg.rampFn; the dial track, the carpet and the legend
  // bar then share that one ramp. The legend bar samples it at 0/25/50/75/100% so the CSS gradient
  // matches the OKLab canvas ramp; cfg.rampLabels relabels the bar ends (Reliable / Unreliable).
  const ramp = cfg.rampFn ? {
    css: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1].map((t) => {
      const [r, g, b] = cfg.rampFn(t); return `rgb(${r},${g},${b}) ${t * 100}%`;
    }).join(', ')})`,
    lo: cfg.rampLabels ? cfg.rampLabels.lo : 'No output',
    hi: cfg.rampLabels ? cfg.rampLabels.hi : 'Full output',
  } : null;
  const gauge = buildGauge((cfg.liveCf ?? 0) * 100, 100, {
    label: cfg.gaugeLabel ?? `${cfg.label} output as a share of installed capacity`,
    calibration: gaugeCalibration(cfg.nameplateMw), dist: cfg.dist, palette: pal,
    trackRamp: cfg.rampFn || null,
  });
  const avgNote = cfg.avgNote ? `<span class="trap-avg">${cfg.avgNote}</span>` : '';
  const srcP = (cls, txt) =>
    `<p class="src trap-src ${cls}">Source: ${esc(txt)} · <a href="methodology.html#${cfg.methodAnchor}">→ method</a></p>`;
  const strip = hasCarpet ? `
      <div class="carpet-cell">
        <div class="carpet-stage">
          <div class="carpet-yaxis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>
          <canvas id="carpet-${cfg.kind}" class="carpet" role="img"
            aria-label="${esc(cfg.carpetAria ?? `${cfg.label} capacity factor, every half-hour of the last year. Date runs left to right; time of day runs top (00:00) to bottom (24:00). White = no output, deepening colour = toward full capacity.`)}"></canvas>
        </div>
        <div class="carpet-xaxis" id="carpet-${cfg.kind}-x"></div>
      </div>
      ${srcP('trap-src-gauge', cfg.gaugeSrc)}
      ${srcP('trap-src-strip', cfg.carpetSrc)}`
    : srcP('trap-src-gauge', cfg.gaugeSrc);
  return `
      <p class="trap-label">${esc(cfg.label)}${avgNote}</p>
      ${hasCarpet ? legendFor(cfg.kind, cfg.liveCf, pal, cfg.dist, cfg.sat, cfg.unitNoun, ramp) : ''}
      <div class="trap-gauge-cell"><div class="gauge-block">${gauge}</div></div>
      ${strip}
      ${cfg.keyNote}`;
}

// Entry 02: one block per source (wind, then solar). A single colour legend sits above each. No
// combined/aggregate gauge — solar must not flatter the wind reading; each uses its own nameplate
// so dial and carpet share a basis. Built as two renderMetricBlock calls over per-source configs.
function renderTrap(v) {
  $('entry-trap').hidden = false;
  const g = (CAPACITY && CAPACITY.gauge) || {};
  const windCapMw = g.wind_nameplate_mw || Math.round((NAMEPLATE ? NAMEPLATE.wind_gw : 32.082) * 1000);
  const solarCapMw = g.solar_nameplate_mw || Math.round((NAMEPLATE ? NAMEPLATE.solar_gw : 18.28) * 1000);
  const has = !!(CAPACITY && CAPACITY.wind && CAPACITY.solar && CAPACITY.sat);
  const cfgFor = (kind, label, sourceMw, capMw, gaugeSrc, carpetSrc) => {
    const days = has ? CAPACITY[kind].days : null;
    const dist = has ? distForDays(CAPACITY[kind], days) : null;
    const avg = avgFromDays(days);
    return {
      kind, label, palette: DIAL_PALETTE[kind], nameplateMw: capMw,
      sat: has ? CAPACITY.sat[kind] : 1, days, dist,
      liveCf: capMw ? (sourceMw / capMw) : 0,
      avgNote: avg == null ? '' : `averages ${avg}% of capacity over the year`,
      keyNote: '',   // the shared box-plot key is shown once, under the Entry-01 reliability block
      gaugeSrc, carpetSrc, methodAnchor: 'capacity-trap',
    };
  };
  $('trap-body').innerHTML = `
    <div class="trap-grid${has ? '' : ' gauge-only'}">
      ${renderMetricBlock(cfgFor('wind', 'Wind', v.wind_mw || 0, windCapMw, WIND_GAUGE_SRC, (CAPACITY && CAPACITY.source_wind) || WIND_GAUGE_SRC))}
      ${renderMetricBlock(cfgFor('solar', 'Solar', v.solar_mw || 0, solarCapMw, SOLAR_GAUGE_SRC, (CAPACITY && CAPACITY.source_solar) || SOLAR_GAUGE_SRC))}
    </div>`;
  if (has) {
    syncBlockHeights();
    drawCarpetCanvas('carpet-wind', CAPACITY.wind.days, CAPACITY.sat.wind, DIAL_PALETTE.wind.fullRgb);
    drawCarpetCanvas('carpet-solar', CAPACITY.solar.days, CAPACITY.sat.solar, DIAL_PALETTE.solar.fullRgb);
  }
}

// Entry 01: the reliability metric block, rendered under the gauge+receipt into #reliability-body.
// Third consumer of renderMetricBlock. The dial/carpet show the UNRELIABLE share of demand (1 - firm):
// white = reliable, deep red = unreliable. No nameplate (the dial is a plain 0-100% share), so the
// MW calibration labels are suppressed. The live needle reads 1 - firm share, the same measure the
// gauge above it draws, so the two can never disagree.
let REL_CARPET = null;   // site/data/reliability_carpet.json (days x 48 of unreliable share)

function renderReliabilityBlock(v) {
  const host = $('reliability-body');
  if (!host) return;
  const has = !!(REL_CARPET && REL_CARPET.days && REL_CARPET.days.length);
  const m = v ? sourceArcModel(v) : null;
  const nowPct = m ? unreliableNowPct(m.firmPct) : null;   // 0..100 (clamped) or null
  const days = has ? REL_CARPET.days : null;
  const dist = has ? distForDays(REL_CARPET, days) : null;
  const avg = avgFromDays(days);
  const src = (REL_CARPET && REL_CARPET.source) || 'Elexon FUELHH (settled) + NESO embedded';
  host.innerHTML = `
    <div class="trap-grid${has ? '' : ' gauge-only'}">
      ${renderMetricBlock({
        kind: 'reliability', label: 'Unreliability', palette: REL_PALETTE,
        nameplateMw: null, sat: has ? REL_CARPET.sat : 1, days, dist,
        liveCf: nowPct == null ? null : nowPct / 100,
        avgNote: avg == null ? '' : `averaged ${avg}% of demand over the year`,
        keyNote: has ? KEY_NOTE_HTML : '',
        unitNoun: 'demand',
        rampFn: unreliabilityColor, rampLabels: { lo: 'Reliable', hi: 'Unreliable' },
        gaugeSrc: 'Live: Elexon FUELINST + NESO embedded forecast (1 - firm share)',
        carpetSrc: src, methodAnchor: 'reliability',
        gaugeLabel: 'Unreliability — unreliable share of national demand',
        carpetAria: 'Unreliable share of GB national demand, every half-hour of the last year. Date runs left to right; time of day runs top (00:00) to bottom (24:00). Green = demand fully met by firm power, through amber to deep red = increasingly leaning on weather and imports.',
      })}
    </div>`;
  if (has) {
    syncBlockHeights();
    drawCarpetCanvas('carpet-reliability', REL_CARPET.days, REL_CARPET.sat, null,
      { rampFn: unreliabilityColor, keepWorstHigh: true });
  }
}

// Match each carpet to the VISIBLE DIAL height beside it (the semicircle arc, not the gauge's full
// SVG box, which carries the calibration labels above/below). The arc spans radius R of the viewBox
// width, so its rendered height is gaugeWidth × R/viewBoxWidth. Mirrored onto the grid as --carpet-h
// before drawCarpetCanvas so the canvas measures the right height. Iterates EVERY block grid (so a
// later Entry-01 metric block also gets sized), keying each to the dial beside it within that grid.
const DIAL_ARC_RATIO = 86 / 232;   // buildGauge R / viewBox width — keep in sync with buildGauge
function syncBlockHeights() {
  document.querySelectorAll('.trap-grid').forEach((grid) => {
    const gauge = grid.querySelector('.trap-gauge-cell .gauge');
    if (!gauge) return;
    const h = Math.round(gauge.getBoundingClientRect().width * DIAL_ARC_RATIO);
    if (h > 0) grid.style.setProperty('--carpet-h', `${h}px`);
  });
}

// Month ticks for a carpet's date (X) axis: one label at each month boundary, positioned by its
// fractional offset along the day array. Oldest day is at the left (frac 0), newest at the right.
const _CARPET_MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function layoutCarpetAxis(kind, days) {
  const el = $(`carpet-${kind}-x`);
  if (!el || !days || !days.length) return;
  let last = null, html = '';
  for (let i = 0; i < days.length; i++) {
    const ds = days[i].date, mo = ds.slice(5, 7);
    if (mo === last) continue;
    last = mo;
    // Skip the partial leading month (the rolling window starts mid-month) — its label would
    // collide with the first full month's tick a few days to its right.
    if (i === 0 && parseInt(ds.slice(8, 10), 10) > 1) continue;
    const frac = i / days.length;
    if (frac > 0.96) continue;                 // drop a label that would collide with the right edge
    // Stamp the year on January (the rollover) so the timeline is unambiguous: months left of it are
    // the prior year, right of it the current — the right edge is the latest settled month (~3 weeks
    // behind today), so the current month is not yet in the settled carpet.
    const yr = mo === '01' ? ` <b>’${ds.slice(2, 4)}</b>` : '';
    html += `<span style="left:${(frac * 100).toFixed(2)}%">${_CARPET_MON[parseInt(mo, 10) - 1]}${yr}</span>`;
  }
  el.innerHTML = html;
}

let CAPACITY = null;   // site/data/capacity_carpets.json (wind + solar half-hourly CF grids)

// A carpet plot: x = date (oldest left → newest right), y = time of day (SP1=00:00 top → SP48
// bottom). Each cell coloured by its half-hourly capacity factor (carpetCellColor): white = no
// output, deepening to `full` (the source hue) at full capacity. The date axis is lowest-output-wins
// downsampled so a sub-pixel calm spell (now palest) is never averaged out. DPR-aware; redrawn on
// resize, with its month axis re-laid out to match.
// `opts.rampFn` (cf -> [r,g,b]) overrides the default paper->`full` colour (used by the unreliability
// carpet's green->amber->red ramp). `opts.keepWorstHigh` flips the downsample to keep the HIGHEST cf
// per spanned column instead of the lowest: for output carpets the worst case is LOW (calm), so the
// minimum is preserved; for the unreliability carpet the worst case is HIGH (most unreliable), so the
// maximum must be preserved — otherwise a screen-resolution downsample would silently drop the worst
// half-hours. Either way no worst-case spell is averaged out of existence.
function drawCarpetCanvas(canvasId, days, satFull, full, opts = {}) {
  const { rampFn = null, keepWorstHigh = false } = opts;
  const canvas = $(canvasId);
  if (!canvas || !days || !days.length) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  const nDays = days.length, P = 48;
  const rowH = cssH / P;                        // a row per half-hour (time of day)
  for (let sx = 0; sx < cssW; sx++) {           // a screen column per pixel; map to a date span
    const d0 = Math.floor((sx / cssW) * nDays);
    const d1 = Math.max(d0 + 1, Math.floor(((sx + 1) / cssW) * nDays));
    for (let p = 0; p < P; p++) {
      let worst = keepWorstHigh ? -Infinity : Infinity, saw = false;
      for (let d = d0; d < d1 && d < nDays; d++) {
        const v = days[d].cf[p];               // oldest (first) day at the left
        if (v != null) { saw = true; worst = keepWorstHigh ? Math.max(worst, v) : Math.min(worst, v); }
      }
      const cf = saw ? worst : null;
      const [r, g, b] = rampFn ? rampFn(cf) : carpetCellColor(cf, satFull, full);
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(sx, p * rowH, 1, Math.ceil(rowH));
    }
  }
  layoutCarpetAxis(canvasId.replace('carpet-', ''), days);
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

// ============================================================ wind unreliability (Entry 03)
// Tasks 10–11 replace these stubs with real canvas drawing.
function drawWindCarpet(data) {
  window.__windData = data;
  const cv = $('wind-carpet'); if (!cv) return;
  const { years, doy, rows } = data.carpet;
  const cols = doy.length, nRows = years.length;
  const cssW = cv.clientWidth || 960, cellH = 22, cssH = nRows * cellH;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(cssW * dpr); cv.height = Math.round(cssH * dpr); cv.style.height = cssH + 'px';
  const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
  const cw = cssW / cols;
  years.forEach((y, r) => {
    const row = rows[String(y)];
    if (!row) return;
    for (let c = 0; c < cols; c++) {
      const [rr, gg, bb] = windDroughtColor(row[c], data.windy_anchor_cf);
      ctx.fillStyle = `rgb(${rr},${gg},${bb})`;
      ctx.fillRect(c * cw, r * cellH, Math.ceil(cw) + 0.5, cellH - 1);
    }
  });
  $('wind-carpet-y').innerHTML = years.map((_, i) =>
    `<span>${years[i]}</span>`).join('');
  $('wind-carpet-x').innerHTML = carpetMonthTicks().map((t) =>
    `<span style="left:${(t.frac * 100).toFixed(2)}%">${t.label}</span>`).join('');
}
function drawDroughtPlot(data) {
  const cv = $('wind-drought'); if (!cv) return;
  const lulls = data.lulls || [];
  const x0ms = Date.parse(data.range.from), x1ms = Date.parse(data.range.to);
  const cssW = cv.clientWidth || 960, cssH = 220, padB = 18;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(cssW * dpr); cv.height = Math.round(cssH * dpr); cv.style.height = cssH + 'px';
  const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
  const plotH = cssH - padB;
  const maxDays = Math.max(14, ...lulls.map((l) => l.days));
  // reference lines at 3 / 7 / 14 days
  ctx.font = '500 10px ' + getComputedStyle(document.body).getPropertyValue('--mono');
  [[3, '3 days'], [7, '1 week'], [14, '2 weeks']].forEach(([d, lab]) => {
    const y = plotH - (d / maxDays) * plotH;
    ctx.strokeStyle = 'rgba(21,24,28,0.12)'; ctx.beginPath();
    ctx.moveTo(0, y); ctx.lineTo(cssW, y); ctx.stroke();
    ctx.fillStyle = 'rgba(21,24,28,0.45)'; ctx.fillText(lab, 2, y - 2);
  });
  const spikes = droughtSpikes(lulls, { x0ms, x1ms, w: cssW, h: plotH, maxDays });
  spikes.forEach((s, i) => {
    const [r, g, b] = windDroughtColor(lulls[i].min_cf, data.windy_anchor_cf);
    ctx.strokeStyle = s.minor ? 'rgba(140,12,20,0.25)' : `rgb(${r},${g},${b})`;
    ctx.lineWidth = s.minor ? 1 : 2;
    ctx.beginPath(); ctx.moveTo(s.x, plotH); ctx.lineTo(s.x, plotH - s.h); ctx.stroke();
  });
  // annotate the record
  const rec = data.summary?.record_lull;
  if (rec) {
    const rx = ((Date.parse(rec.start) - x0ms) / Math.max(1, x1ms - x0ms)) * cssW;
    ctx.fillStyle = '#15181c';
    ctx.fillText(`${rec.days} days`, Math.min(cssW - 48, rx + 4),
      Math.max(12, plotH - (rec.days / maxDays) * plotH - 4));
  }
}

function renderWindUnreliability(data) {
  $('wind-body').innerHTML = `
    <div class="wind-carpet-cell">
      <div class="wind-yaxis" id="wind-carpet-y"></div>
      <canvas id="wind-carpet" class="wind-carpet" role="img"
        aria-label="Wind daily capacity factor for every day since 2016. Rows are years (2016 at the top), columns are the day of the year (1 January at the left). Pale = a windy day; deep red = a near-calm day."></canvas>
    </div>
    <div class="wind-carpet-x" id="wind-carpet-x"></div>
    <canvas id="wind-drought" class="wind-drought" role="img"
      aria-label="${esc(droughtCaption(data.summary))}"></canvas>
    <p class="wind-caption">${esc(droughtCaption(data.summary))}</p>
    <p class="src">Source: ${esc(data.source)} · <a href="methodology.html#wind-unreliability">how this is measured</a></p>`;
  drawWindCarpet(data);
  drawDroughtPlot(data);
}

// ============================================================ orchestration
async function refreshLive() {
  try {
    const state = await resolveState({}, () => Date.now());
    renderVerdict(state);
    $('clockstrip').textContent =
      `${state.lastUpdated}`;
    $('freshness').textContent = `Live layer: ${state.lastUpdated}.`;
    const dot = $('live-dot');   // live = the normal state: show nothing; only surface a degraded state
    dot.textContent = state.mode === 'live' ? '' : state.mode === 'fallback' ? 'Last good' : 'Offline';
    dot.hidden = state.mode === 'live';
  } catch (e) {
    $('verdict-body').innerHTML = `<p class="warn">Live layer error — no current reading. ${esc(e.message || e)}</p>`;
    $('entry-trap').hidden = true;
  }
}

async function main() {
  // History first (static, always available); then the live layer on top.
  try {
    NAMEPLATE = await getJSON('data/nameplate.json');
  } catch (e) { /* nameplate failure is non-fatal; defaults apply */ }
  // The reliability carpet (Entry 01, under the gauge) is independent: its own fetch so a missing
  // file omits only the carpet, never the live gauge above it. renderReliabilityBlock runs from
  // renderVerdict each poll, so loading the data here is enough.
  try { REL_CARPET = await getJSON('data/reliability_carpet.json'); }
  catch (e) { REL_CARPET = null; }
  // capacity carpets (Entry 02 right panels) — independent fetch so a missing file degrades
  // only the carpets, never the gauge or the other history entries.
  try { CAPACITY = await getJSON('data/capacity_carpets.json'); }
  catch (e) { CAPACITY = null; }
  // wind unreliability (Entry 03) — independent fetch; a missing file degrades only this section.
  try {
    const windData = await getJSON('data/wind_unreliability.json');
    renderWindUnreliability(windData);
  } catch (e) {
    $('wind-body').innerHTML = `<p class="warn">Wind unreliability data unavailable. ${esc(e.message || e)}</p>`;
  }
  await refreshLive();
  setInterval(refreshLive, POLL_MS);
  refreshWarnings();
  setInterval(refreshWarnings, POLL_MS);
  let t;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => {
    if (CAPACITY && CAPACITY.sat) syncBlockHeights();
    if (CAPACITY && CAPACITY.wind && CAPACITY.sat) drawCarpetCanvas('carpet-wind', CAPACITY.wind.days, CAPACITY.sat.wind, DIAL_PALETTE.wind.fullRgb);
    if (CAPACITY && CAPACITY.solar && CAPACITY.sat) drawCarpetCanvas('carpet-solar', CAPACITY.solar.days, CAPACITY.sat.solar, DIAL_PALETTE.solar.fullRgb);
    if (REL_CARPET && REL_CARPET.days) drawCarpetCanvas('carpet-reliability', REL_CARPET.days, REL_CARPET.sat, null, { rampFn: unreliabilityColor, keepWorstHigh: true });
    if (window.__windData) { drawWindCarpet(window.__windData); drawDroughtPlot(window.__windData); }
  }, 150); });
}

main();
