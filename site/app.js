// site/app.js — the Grid Margin dashboard renderer.
//
// Two sources, never blended on screen: the LIVE layer (resolveState in live.js, which
// recomputes the verdict in the browser and falls back to the build's latest.json), and
// the settled HISTORY (site/data/*.json from engine/derived.py). app.js owns only the
// presentation; every number it shows comes from one of those, and every figure carries
// its baked source line. Pure maths lives in render.js (unit-tested).
import { resolveState } from './live.js';
import { resolveWarnings } from './warnings.js';
import { windLullLamp, firmMajorityLamp, heavyImportsLamp, overcastLamp, scarcityLamp } from './conditions.js';
import {
  gaugeNeedleAngle, firmStatus, sourceArcModel, COL_EXPORT,
  fmtGW, fmtMW,
  unreliableNowPct, integerShares, reliablePct,
  carpetCellColor, gaugeCalibration, reliabilityColor,
  windDroughtColor, droughtSpikes, droughtCaption, carpetMonthTicks,
  importValueColor, importCostCaption, fmtRatePerH,
} from './render.js';

const $ = (id) => document.getElementById(id);

// Brand inks, single-sourced from the CSS custom properties (style.css :root) so the gauge drawing
// can never drift from the page palette. Same getComputedStyle pattern as the mono-font read below.
const _cssVar = (name, fallback) => (getComputedStyle(document.body).getPropertyValue(name).trim() || fallback);
const INK = _cssVar('--ink', '#15181c');
const RED = _cssVar('--red', '#d6121f');
const GREEN = _cssVar('--green', '#1b6e45');
const SLATE = _cssVar('--slate', '#565e66');
const POLL_MS = 5 * 60 * 1000;


async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return r.json();
}

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// Footer for a homepage group. "Sources & method →" is right-aligned on its row. Where the group has
// deeper-analysis page(s), a "Going further:" block below lists them. `further` = [{href, label}, …].
function entryFooter(section, further) {
  const has = further && further.length;
  const going = has ? '<span class="entry-foot-going">Going further:</span>' : '';
  const links = has
    ? `<div class="entry-further">${further.map((f) => `<a href="${f.href}">→ ${f.label}</a>`).join('')}</div>`
    : '';
  return `<div class="entry-foot entry-foot-legend">`
    + `<a class="entry-foot-src" href="methodology.html#interpreting-the-legend">Interpreting the legend →</a>`
    + `</div>`
    + `<div class="entry-foot">${going}`
    + `<a class="entry-foot-src" href="methodology.html#src-group-${section}">Sources &amp; method →</a>`
    + `</div>${links}`;
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
                                  ariaLabel = null, calUnit = ' MW',
                                  palette = { track: '#d7dbdf', band: '#b4bac1', core: '#7c838a' } } = {}) {
  const cx = 100, cy = 104, R = 86;
  const ticks = [];
  for (let v = 0; v <= max; v += max / 4) {   // ticks at 0/25/50/75/100, aligned with the labels
    const [ox, oy] = arcPoint(cx, cy, R + 3, v, max);
    const [ix, iy] = arcPoint(cx, cy, R - 6, v, max);
    ticks.push(`<line x1="${ox.toFixed(1)}" y1="${oy.toFixed(1)}" x2="${ix.toFixed(1)}" y2="${iy.toFixed(1)}" stroke="${SLATE}" stroke-width="1.4"/>`);
  }
  const [nx, ny] = arcPoint(cx, cy, R - 12, Math.min(value, max), max);
  const needleColor = armed ? RED : INK;
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
    median = `<line x1="${mx1.toFixed(1)}" y1="${my1.toFixed(1)}" x2="${mx2.toFixed(1)}" y2="${my2.toFixed(1)}" stroke="${INK}" stroke-width="2.2"/>`;
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
        cal += `<text x="${ox.toFixed(1)}" y="${(oy + 11).toFixed(1)}" class="g-mw" text-anchor="middle">${t.label_mw}${t.pct === 100 ? calUnit : ''}</text>`;
      } else if (t.pct === 50) {
        // The peak (50%-mark) power figure sits clearly above the dial, well clear of the "50%" label.
        const [ox, oy] = arcPoint(cx, cy, R + 18, v, max);
        cal += `<text x="${ox.toFixed(1)}" y="${(oy - 2).toFixed(1)}" class="g-mw" text-anchor="middle">${t.label_mw}</text>`;
      }
    }
  }
  return `
  <svg class="gauge" viewBox="-6 -12 232 130" role="img" aria-label="${esc(ariaLabel ?? `${label}: ${value.toFixed(1)} of ${max}`)}">
    ${trackArc}
    ${distArcs}
    ${seg(reliable, '#1f9d57')}
    ${seg(danger, RED)}
    ${ticks.join('')}
    ${median}
    ${cal}
    <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${needleColor}" stroke-width="3" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="5" fill="${needleColor}"/>
  </svg>`;
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
    svg += tick(model.arcTotal, INK, 16, 2.2);               // "demand met" divider
  }
  // Inner group-indicator arc, set in a little from the outer ring: green = reliable share of demand,
  // red = unreliable share. The outer ring now carries per-source colours, so this is the two-colour
  // reliable/unreliable read. firmMw = where reliable meets unreliable.
  const firmMw = model.slices.filter((s) => s.group === 'reliable').reduce((a, s) => a + s.mw, 0);
  const Ri = 66, IGAP = total * 0.006;
  const inner = (v0, v1, color) =>
    `<path d="${arcPath(cx, cy, Ri, v0, v1, total)}" fill="none" stroke="${color}" stroke-width="7"/>`;
  if (firmMw > IGAP) svg += inner(0, firmMw - IGAP / 2, GREEN);                            // reliable (green)
  if (model.arcTotal - firmMw > IGAP) svg += inner(firmMw + IGAP / 2, model.arcTotal, RED); // unreliable (red)
  // Needle points at the firm boundary; shortened to sit just inside the inner arc.
  const [nx, ny] = arcPoint(cx, cy, Ri - 6, firmMw, total);
  const ncol = armed ? RED : INK;
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
    </div>`;

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
  // Imports — magenta, matching the verdict gauge's interconnector slice (COL_IMPORTS #c2188f), so
  // "imports" reads the same hue across the dashboard. Bands luma-matched to the wind/solar shades.
  import: { track: '#f0d2e6', band: '#dc9ec8', core: '#c0589f', full: '#c2188f', fullRgb: [194, 24, 143] },
};


// Import-cost dial/legend — the cost-red family (cheaper = pale, costlier = deep red). Track and
// distribution bands tinted red so the central-tendency box reads as "cost" without a gradient track.
const IMPORT_DIAL_PALETTE = { track: '#e8dcda', band: '#d3a8a2', core: '#b15c52', full: '#8c0c14', fullRgb: [140, 12, 20] };

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
function legendFor(kind, cf, pal, dist, satFull, unitNoun, ramp, opts = {}) {
  // Value-scale variant (Entry 04 import cost): the SAME .carpet-legend skeleton and the SAME
  // central-tendency box-plot as wind/solar — p10–p90 whisker, p25–p75 usual half, mean tick, and a
  // live "now" caret — but positioned on a non-linear (sqrt) £ scale via opts.scale.posFn so the
  // costliest day on record (£94m) stays on-scale without crushing the cheap-day box into a sliver.
  // Numbers are £-formatted (opts.scale.fmt) instead of percentages.
  if (opts.scale) {
    const P = opts.scale.posFn, fmt = opts.scale.fmt;   // £ -> 0..100 bar position / display string
    const period = opts.scale.period || 'day';          // box-plot tooltip noun (day / half-hour)
    const d = dist;   // raw £ percentiles {p10,p25,p50,p75,p90,mean}
    const nowPos = P(cf);   // cf is the raw live £ value here
    let box = '';
    if (d) {
      box = `
        <span class="cl-box" aria-hidden="true" title="typical ${period}: average ${fmt(d.mean)}, usual half ${fmt(d.p25)}–${fmt(d.p75)}, 9-in-10 ${fmt(d.p10)}–${fmt(d.p90)}">
          <span class="cl-box-line" style="left:${P(d.p10).toFixed(1)}%; width:${(P(d.p90) - P(d.p10)).toFixed(1)}%; background:${pal.band}"></span>
          <span class="cl-box-iqr" style="left:${P(d.p25).toFixed(1)}%; width:${(P(d.p75) - P(d.p25)).toFixed(1)}%; background:${pal.core}"></span>
          <span class="cl-box-avg" style="left:${P(d.mean).toFixed(1)}%"></span>
        </span>
        ${numsRow([
          { pos: P(d.p10), txt: fmt(d.p10), color: pal.core, pr: 1 },
          { pos: P(d.mean), txt: fmt(d.mean), cls: 'cl-num-avg', pr: 2 },
          { pos: P(d.p90), txt: fmt(d.p90), color: pal.core, pr: 1 },
        ])}`;
    }
    return `
    <div class="carpet-legend">
      <span class="cl-lab">${esc(opts.lo)}</span>
      <span class="cl-bar-wrap">
        <span class="cl-bar" style="background:${opts.barCss}" aria-hidden="true"></span>
        <span class="cl-now" style="left:${nowPos.toFixed(1)}%" title="At the current rate: ${fmt(cf)}">now</span>
        ${box}
      </span>
      <span class="cl-lab">${esc(opts.hi)}</span>
    </div>`;
  }
  const noun = unitNoun || 'capacity';
  const boxBand = ramp ? '#9aa3ab' : pal.band, boxCore = ramp ? '#4b535b' : pal.core;
  const barCss = ramp ? ramp.css : `linear-gradient(90deg in oklab, #fbfbf9, ${pal.full})`;
  // End labels: the ramp's (reliability), or caller overrides (opts.lo/opts.hi — imports use
  // "No imports"/"Full capacity"), else the wind/solar default.
  const loLab = ramp ? ramp.lo : (opts.lo || 'No output'), hiLab = ramp ? ramp.hi : (opts.hi || 'Full output');
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
        <span class="cl-now" style="left:${pos.toFixed(1)}%" title="Now: ${opts.nowPctLabel ?? Math.round(cf * 100)}% of ${noun}">now</span>
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

// The shared metric block: full-width source label row, the live dial (1/3 column) beside its
// half-hourly carpet (2/3 column), then an aligned row of source lines. Closes over no Entry-02
// globals — everything comes from `cfg` — so a later entry can reuse it with its own palette,
// nameplate and series. Returns the HTML string; the CALLER paints the carpet canvas afterwards.
function renderMetricBlock(cfg) {
  const pal = cfg.palette;
  // A block has a carpet either via the default hour×month series (cfg.days) or via a pluggable
  // carpet markup string (cfg.carpetHtml — Entry 04's year×day-of-year carpet, painted by the caller).
  const hasCarpet = !!cfg.carpetHtml || !!(cfg.days && cfg.days.length);
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
  // The dial: the default %-of-capacity gauge, or a caller-supplied gauge string (Entry 04's
  // £-rate ramp dial, which has its own scale and readout). cfg.gaugeExtra hangs under the dial
  // (Entry 04's live-imports receipt line).
  const gaugeLabel = cfg.gaugeLabel ?? `${cfg.label} output as a share of installed capacity`;
  const gauge = cfg.gaugeHtml != null ? cfg.gaugeHtml : buildGauge((cfg.liveCf ?? 0) * 100, 100, {
    label: gaugeLabel,
    // When a label is pinned (the reliability dial), announce that integer so the dial's accessible
    // value matches the verdict gauge stamp instead of the continuous needle value.
    ariaLabel: cfg.nowPctLabel == null ? null : `${gaugeLabel}: ${cfg.nowPctLabel} of 100`,
    calibration: gaugeCalibration(cfg.nameplateMw), dist: cfg.dist, palette: pal,
    trackRamp: cfg.rampFn || null,
  });
  const srcP = (cls, txt) => txt
    ? `<p class="src trap-src ${cls}">Source: ${esc(txt)} · <a href="methodology.html#${cfg.methodAnchor}">→ method</a></p>`
    : '';
  const defaultCarpet = `
        <div class="carpet-stage">
          <div class="carpet-yaxis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>
          <canvas id="carpet-${cfg.kind}" class="carpet" role="img"
            aria-label="${esc(cfg.carpetAria ?? `${cfg.label} capacity factor, every half-hour of the last year. Date runs left to right; time of day runs top (00:00) to bottom (24:00). White = no output, deepening colour = toward full capacity.`)}"></canvas>
        </div>
        <div class="carpet-xaxis" id="carpet-${cfg.kind}-x"></div>`;
  // gaugeExtra (the import live-receipt line) renders as its OWN column-1 grid item below the dial,
  // NOT inside the gauge cell — so the gauge cell stays the same height as the wind/solar dials and
  // the carpet beside it bottom-aligns to the dial baseline. Emitted after the carpet in DOM order so
  // grid auto-placement keeps the carpet in the dial's row (row 2, col 2). Absent for wind/solar/
  // reliability (no gaugeExtra), so their markup is unchanged.
  const gaugeExtra = cfg.gaugeExtra ? `<div class="trap-gauge-extra">${cfg.gaugeExtra}</div>` : '';
  const strip = hasCarpet ? `
      <div class="carpet-cell">
        ${cfg.carpetHtml ?? defaultCarpet}
      </div>
      ${gaugeExtra}
      ${srcP('trap-src-gauge', cfg.gaugeSrc)}
      ${srcP('trap-src-strip', cfg.carpetSrc)}
      ${cfg.stripExtra ? `<div class="trap-extra">${cfg.stripExtra}</div>` : ''}`
    : `${gaugeExtra}${srcP('trap-src-gauge', cfg.gaugeSrc)}`;
  return `
      ${cfg.label ? `<p class="trap-label">${esc(cfg.label)}</p>` : ''}
      ${hasCarpet ? (cfg.legendHtml ?? legendFor(cfg.kind, cfg.liveCf, pal, cfg.dist, cfg.sat, cfg.unitNoun, ramp, { ...(cfg.legendLabels || {}), nowPctLabel: cfg.nowPctLabel })) : ''}
      <div class="trap-gauge-cell"><div class="gauge-block">${gauge}</div></div>
      ${strip}
      ${cfg.keyNote ?? ''}`;
}

// A quiet reading under a live dial: the live flow in MW and its share of `denom`, labelled `noun`.
// The only place the §02/§03 panels print the live MW. §02 (wind/solar) reads its share of CAPACITY
// (nameplate) — the same capacity factor as the dial/carpet/legend/WIND-LULL lamp, so the panel speaks
// one basis; §03 imports reads its share of demand (the exposure). A 2px metric-hue tick (--now-rgb).
function dialNowLine(kind, mw, denom, noun) {
  const rgb = (DIAL_PALETTE[kind] || {}).fullRgb;
  if (!rgb) return '';
  const tint = `--now-rgb:${rgb[0]},${rgb[1]},${rgb[2]}`;
  if (Number.isFinite(mw) && mw < 0) {   // a net export (imports only) — the cables run the other way
    const ex = Math.round(-mw).toLocaleString('en-GB');
    return `<p class="dial-now" style="${tint}">Exporting <strong class="num">${ex} MW</strong> · cables reversed</p>`;
  }
  if (!Number.isFinite(mw) || !denom) return '';
  const mwTxt = Math.round(mw).toLocaleString('en-GB');
  const pct = Math.round(mw / denom * 100);
  return `<p class="dial-now" style="${tint}"><strong class="num">${mwTxt} MW</strong>`
    + ` · <span class="dial-now-sub"><span class="num">${pct}%</span> of ${noun}</span></p>`;
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
  const cfgFor = (kind, label, sourceMw, capMw, keyNote = '') => {
    const days = has ? CAPACITY[kind].days : null;
    const dist = has ? distForDays(CAPACITY[kind], days) : null;
    return {
      kind, label, palette: DIAL_PALETTE[kind], nameplateMw: capMw,
      sat: has ? CAPACITY.sat[kind] : 1, days, dist,
      liveCf: capMw ? (sourceMw / capMw) : 0,
      keyNote,   // the shared box-plot key is shown once, under the first box-plot panel (Wind §02)
      gaugeExtra: dialNowLine(kind, sourceMw, capMw, 'capacity'),   // live MW + capacity factor (matches the dial/lamp)
    };
  };
  // Wind and solar are two distinct methodological groups: each its own block + "Sources & method →",
  // with wind's drought detail link beneath its own. Imports (§03) follows the same source→deeper scheme.
  $('trap-body').innerHTML = `
    <div class="trap-grid${has ? '' : ' gauge-only'}">
      ${renderMetricBlock(cfgFor('wind', 'Wind', v.wind_mw || 0, windCapMw, KEY_NOTE_HTML))}
    </div>
    ${entryFooter('wind', [{ href: 'wind.html', label: 'When the wind stops, it stops for days — the whole wind record since 2016' }])}
    <div class="trap-grid${has ? '' : ' gauge-only'}">
      ${renderMetricBlock(cfgFor('solar', 'Solar', v.solar_mw || 0, solarCapMw))}
    </div>
    ${entryFooter('solar')}`;
  if (has) {
    syncBlockHeights();
    drawCarpetCanvas('carpet-wind', CAPACITY.wind.days, CAPACITY.sat.wind, DIAL_PALETTE.wind.fullRgb);
    drawCarpetCanvas('carpet-solar', CAPACITY.solar.days, CAPACITY.sat.solar, DIAL_PALETTE.solar.fullRgb);
  }
}

// The reliability strip's legend: the KEY to the strip's three background bands, NOT a gradient. Three
// solid zones on the 0–100% reliable axis — red below the firm-share p25, amber across the usual half
// (p25–p75), green above p75 — split at the very same percentiles the strip bands use. Green and red are
// the shared dial inks (reliabilityColor(1)/(0) = the verdict gauge's green/red), so the strip inherits
// the main dial's simplicity and only adds the amber middle. The "now" caret marks the live firm share;
// the two split points are labelled with their percentile values, so the legend also serves as the
// percentile readout the other panels show via a box-plot.
function reliabilityLegend(liveCf, dist, nowLabel) {
  const rgb = (t) => { const [r, g, b] = reliabilityColor(t); return `rgb(${r},${g},${b})`; };
  const RED = rgb(0), AMBER = rgb(0.5), GREEN = rgb(1);
  const clamp = (x) => Math.max(0, Math.min(100, x));
  const p25 = dist ? clamp(dist.p25) : 25;
  const p75 = dist ? clamp(dist.p75) : 75;
  const bar = `linear-gradient(90deg, ${RED} 0%, ${RED} ${p25}%, ${AMBER} ${p25}%, `
    + `${AMBER} ${p75}%, ${GREEN} ${p75}%, ${GREEN} 100%)`;
  const nowPos = liveCf == null ? null : clamp(liveCf * 100);
  const nowCaret = nowPos == null ? ''
    : `<span class="cl-now" style="left:${nowPos.toFixed(1)}%" title="Now: ${nowLabel == null ? Math.round(nowPos) : nowLabel}% firm">now</span>`;
  const splits = dist ? `
        <span class="cl-nums">
          <span class="cl-num" style="left:${p25.toFixed(1)}%">${Math.round(dist.p25)}%</span>
          <span class="cl-num" style="left:${p75.toFixed(1)}%">${Math.round(dist.p75)}%</span>
        </span>` : '';
  return `
    <div class="carpet-legend rel-legend">
      <span class="cl-lab">Unreliable</span>
      <span class="cl-bar-wrap">
        <span class="cl-bar" style="background:${bar}" aria-hidden="true"></span>
        ${nowCaret}
        ${splits}
      </span>
      <span class="cl-lab">Reliable</span>
    </div>`;
}

// Entry 01: the reliability record, rendered under the gauge+receipt into #reliability-body.
// The verdict gauge above already reads the live firm share, so this block drops the (duplicate) dial
// and shows the RECORD instead: a full-width line of the daily MINIMUM firm share — the firm
// (dispatchable) share of demand in each settled day's WORST half-hour — across the rolling year, with
// a 0.5 alarm line. The background is banded by the half-hourly firm-share p25/p75: green where a day's
// worst half-hour still sits in the year's top quartile (reliable all day), red where it drops into the
// bottom quartile, amber between. Because a daily MINIMUM is by definition at the low end, most days
// read red. The legend above is the KEY to those bands: three solid zones split at the same p25/p75
// (red · amber · green) — its green and red are the SAME two inks as the main dial, so the only new
// idea is the amber middle; no gradient, no box-plot.
//   REL_CARPET stores the UNRELIABLE share per half-hour; firm = 1 − it, so the day's worst half-hour is
// 1 − the highest unreliable reading, and the legend's split points mirror the carpet's percentiles onto
// the reliable axis (reliable = 100 − unreliable, so the order reverses).
let REL_CARPET = null;   // site/data/reliability_carpet.json (days x 48 of unreliable share; firm = 1 − it)

function renderReliabilityBlock(v) {
  const host = $('reliability-body');
  if (!host) return;
  const has = !!(REL_CARPET && REL_CARPET.days && REL_CARPET.days.length);
  const m = v ? sourceArcModel(v) : null;
  const u = m ? unreliableNowPct(m.firmPct) : null;        // unreliable share now, 0..100 (clamped)
  const nowPct = u == null ? null : 100 - u;               // RELIABLE share now — the legend "now" caret
  // The number DISPLAYED is the verdict gauge's integer reliable share (largest-remainder, so it matches
  // the receipt), NOT round(nowPct): the two adjacent reliability readings must never differ by a point.
  const nowLabel = m ? reliablePct(m) : null;
  const days = has ? REL_CARPET.days : null;
  // The legend box-plot is the reliable-share distribution: mirror the carpet's UNRELIABLE percentiles
  // onto the reliable axis (reliable = 100 − unreliable, so the percentile order reverses).
  const uDist = has ? distForDays(REL_CARPET, days) : null;
  const dist = uDist ? {
    p10: 100 - uDist.p90, p25: 100 - uDist.p75, p50: 100 - uDist.p50,
    p75: 100 - uDist.p25, p90: 100 - uDist.p10, mean: 100 - uDist.mean,
  } : null;
  const liveCf = nowPct == null ? null : nowPct / 100;
  const legend = has ? reliabilityLegend(liveCf, dist, nowLabel) : '';
  const chart = has ? `
      <div class="rel-line-wrap">
        <canvas id="carpet-reliability" class="rel-line-canvas" role="img"
          aria-label="The firm (dispatchable) share of GB national demand in each day's WORST half-hour, over the last year. Date runs left to right; the ratio runs 0 at the bottom to 1 at the top. The dashed line marks the 0.5 alarm. The background is green where the worst half-hour still sits in the year's top quarter of readings, amber in the middle half, red where it falls into the bottom quarter."></canvas>
        <span class="rel-y rel-y-top" aria-hidden="true">1</span>
        <span class="rel-line-alarm-lab">0.5 alarm</span>
        <span class="rel-y rel-y-bot" aria-hidden="true">0</span>
      </div>
      <div class="carpet-xaxis" id="carpet-reliability-x"></div>` : '';
  host.innerHTML = `
    <div class="reliability-line">
      <p class="trap-label">Reliability — firm share in the day's worst half-hour</p>
      ${legend}
      ${chart}
    </div>
    ${entryFooter('reliability')}`;
  if (has) drawReliabilityLine('carpet-reliability', REL_CARPET.days);
}

// Match each carpet to the VISIBLE DIAL height beside it (the semicircle arc, not the gauge's full
// SVG box, which carries the calibration labels above/below). The arc spans radius R of the viewBox
// width, so its rendered height is gaugeWidth × R/viewBoxWidth. Mirrored onto the grid as --carpet-h
// before drawCarpetCanvas so the canvas measures the right height. Iterates EVERY block grid (so a
// later Entry-01 metric block also gets sized), keying each to the dial beside it within that grid.
const DIAL_ARC_RATIO = 86 / 232;   // buildGauge R / viewBox width — keep in sync with buildGauge
function syncBlockHeights() {
  let trapH = 0;
  document.querySelectorAll('.trap-grid').forEach((grid) => {
    const gauge = grid.querySelector('.trap-gauge-cell .gauge');
    if (!gauge) return;
    const h = Math.round(gauge.getBoundingClientRect().width * DIAL_ARC_RATIO);
    if (h > 0) { grid.style.setProperty('--carpet-h', `${h}px`); trapH = h; }
  });
  // The dial-less reliability strip (Entry 01) has no gauge of its own to key off, so it borrows the
  // wind/solar/import carpet height (they all share one dial width) — set on :root so it survives the
  // strip's per-poll re-render. renderTrap runs this BEFORE renderReliabilityBlock, and the resize
  // handler runs it before the strip's redraw, so the height is always current when the line is drawn.
  if (trapH > 0) document.documentElement.style.setProperty('--rel-strip-h', `${trapH}px`);
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
let SOLAR_OVERCAST = null;   // site/data/solar_overcast.json (conditional clear-sky grid for OVERCAST)

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

// Entry 01 reliability line: the daily MINIMUM firm share (the firm/dispatchable share of demand in the
// day's worst half-hour) across the rolling year, over a green/amber/red background banded by the
// half-hourly firm-share p25/p75 — the SAME percentiles as the box-plot legend above (computed the same
// way as distForDays, so the bands line up with its markers). A day is green when even its worst
// half-hour stays in the year's top quartile, red when the worst half-hour drops into the bottom
// quartile, amber between; a dashed 0.5 alarm line runs across. DPR-aware; redrawn on resize with its
// month axis re-laid out. Replaces the old half-hourly heatmap carpet.
function drawReliabilityLine(canvasId, days) {
  const canvas = $(canvasId);
  if (!canvas || !days || !days.length) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
  if (!cssW || !cssH) return;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const n = days.length;
  // Daily minimum firm share = 1 − the worst (highest) unreliable half-hour that day; null if the day
  // has no readings (so the line breaks and the band goes clear rather than reading a false 0).
  const firmMin = days.map((d) => {
    let mx = -Infinity;
    for (const uu of d.cf) if (uu != null && uu > mx) mx = uu;
    return mx === -Infinity ? null : 1 - mx;
  });
  // Band thresholds: p25/p75 of EVERY half-hour's firm share over the year (not of the daily minima),
  // matched to distForDays' quantile so they line up with the legend's box-plot markers.
  const hh = [];
  for (const d of days) for (const uu of d.cf) if (uu != null) hh.push(1 - uu);
  hh.sort((a, b) => a - b);
  const q = (p) => (hh.length ? hh[Math.min(hh.length - 1, Math.floor(p * hh.length))] : p);
  const lo = q(0.25), hi = q(0.75);

  const tint = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;
  const GREEN_T = tint(reliabilityColor(1), 0.18);    // reliable end of the shared ramp
  const AMBER_T = tint(reliabilityColor(0.5), 0.18);
  const RED_T = tint(reliabilityColor(0), 0.14);      // unreliable end
  const colorAt = (i) => {
    const f = firmMin[i];
    if (f == null) return null;
    if (f >= hi) return GREEN_T;
    if (f < lo) return RED_T;
    return AMBER_T;
  };
  const xLeft = (i) => (i / n) * cssW;
  const yOf = (f) => (1 - f) * cssH;

  // 1. background bands — consecutive same-colour days merged into one rect so translucent fills never
  //    seam or double-darken at day boundaries.
  let runStart = 0, runCol = colorAt(0);
  for (let i = 1; i <= n; i++) {
    const c = i < n ? colorAt(i) : null;
    if (i === n || c !== runCol) {
      if (runCol) { ctx.fillStyle = runCol; ctx.fillRect(xLeft(runStart), 0, xLeft(i) - xLeft(runStart), cssH); }
      runStart = i; runCol = c;
    }
  }

  // 2. the 0.5 alarm line — dashed red.
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = RED;
  ctx.lineWidth = 1;
  const ya = Math.round(yOf(0.5)) + 0.5;
  ctx.beginPath(); ctx.moveTo(0, ya); ctx.lineTo(cssW, ya); ctx.stroke();
  ctx.restore();

  // 3. the data line — daily minimum firm share, ink, with gaps breaking the stroke.
  ctx.strokeStyle = INK;
  ctx.lineWidth = 1.4;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  let pen = false;
  for (let i = 0; i < n; i++) {
    const f = firmMin[i];
    if (f == null) { pen = false; continue; }
    const x = ((i + 0.5) / n) * cssW, y = yOf(f);
    if (pen) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pen = true; }
  }
  ctx.stroke();

  layoutCarpetAxis(canvasId.replace('carpet-', ''), days);
}

// ============================================================ the GRID CONDITIONS rail
// Two independent update paths: the three computed lamps refresh on the live verdict poll
// (updateComputedLamps, from refreshLive); the official scarcity lamp refreshes on the SYSWARN poll
// (updateScarcityLamp). A failure on either path degrades only its own lamps — never a sibling, never
// the verdict. ?cond=wind:18,firm,import,scarcity:emn forces states for previewing.

function condOverride() {
  const v = new URLSearchParams(window.location.search).get('cond');
  if (v == null) return null;
  const set = new Set(v.split(',').map((s) => s.trim()));
  const find = (k) => [...set].find((s) => s === k || s.startsWith(k + ':'));
  const arg = (s) => (s && s.includes(':') ? s.split(':')[1] : null);
  const out = {};
  const w = find('wind'); if (w) out.wind = { state: 'active', cfPct: Number(arg(w)) || 14 };
  if (find('firm')) out.firm = { state: 'active', firmPct: 38 };
  if (find('import')) out.import = { state: 'active', pct: 29 };
  const so = find('solar');
  if (so) out.solar = arg(so) === 'dark' ? { state: 'dark' }
    : { state: 'active', clearFrac: (Number(arg(so)) / 100) || 0.28 };
  const sc = find('scarcity'); if (sc) out.scarcity = { state: 'in_force', type: (arg(sc) || 'emn').toUpperCase(), label: 'Electricity Margin Notice' };
  return out;
}

const _round = (x) => (Number.isFinite(x) ? Math.round(x) : '—');

function setLamp(id, state, statusHtml, aria) {
  const el = $(id);
  if (!el) return;
  el.dataset.state = state;
  const status = el.querySelector('.cond-status');
  if (status) status.innerHTML = statusHtml;
  if (aria) el.setAttribute('aria-label', aria);
}

function _windStatus(l) {
  if (l.state === 'unavailable') return 'unavailable';
  // A lull IS a capacity-factor story, so the lamp READS the live wind capacity factor itself — the
  // very wind ÷ nameplate it trips on, against the §02 dial's P25. No demand term, so nothing to
  // apportion or de-rate and it cannot disagree with the receipt. Nominal: just "Nominal".
  return l.state === 'active'
    ? `<b>${_round(l.cfPct)}%</b> of capacity`
    : 'Nominal';
}
function _firmStatus(l) {
  if (l.state === 'unavailable') return 'unavailable';
  // The lamp logic tracks the RELIABLE (firm) share — low is the alarm — but the DISPLAY reads the
  // UNRELIABLE share (100 − firm = wind + solar + imports), so the number climbs with the alarm and
  // agrees with the "UNRELIABLE" title. The label makes a leading "Active" redundant.
  const u = Number.isFinite(l.firmPct) ? 100 - l.firmPct : NaN;
  return l.state === 'active'
    ? `<b>${_round(u)}%</b> weather and imports`
    : 'Nominal';
}
function _importStatus(l) {
  if (l.state === 'unavailable') return 'unavailable';
  // The lamp TRIPS on cable utilisation (> P75 of capacity, set in updateComputedLamps), but the
  // READING is the EXPOSURE: net imports as a share of supply — how much we are leaning on neighbours
  // who may stop selling. (Cable-fullness sizes the pipe; the share of supply sizes the hole if it
  // stops.) Signed: an export hour reads as export. Falls back to l.pct for the ?cond= preview override.
  const d = Number.isFinite(l.demandPct) ? l.demandPct : l.pct;
  if (d < 0) return `Nominal · <b>${_round(Math.abs(d))}%</b> export`;
  // Nominal reads a bare "Nominal", matching the wind / firm / overcast lamps; only the active state
  // carries the share-of-supply number.
  return l.state === 'active'
    ? `<b>${_round(d)}%</b> of supply`
    : 'Nominal';
}
function _overcastStatus(l) {
  if (l.state === 'dark') return 'After dark';
  if (l.state === 'unavailable') return 'unavailable';
  // Active (overcast): the "% of a clear day" reading; nominal: just "Nominal" (the long tail
  // overflowed the cell and the number isn't needed when it isn't cloudy) — same as the wind lamp.
  return l.state === 'active'
    ? `<b>${_round((l.clearFrac ?? 0) * 100)}%</b> of a clear day`
    : 'Nominal';
}
function _scarcityStatus(l) {
  if (l.state === 'in_force') return `${esc(l.type)} in force · NESO`;
  if (l.state === 'clear') return 'All clear · NESO';
  return 'unavailable · NESO';
}

// Current (week-of-year 0..51, settlement period 1..48) for a snapshot in UK LOCAL time — the same
// indexing as solar_overcast.json (engine week_index + SP1 = 00:00 local). Intl gives the Europe/London
// wall clock so BST/GMT is handled without a hardcoded offset.
function londonWeekSP(d) {
  const p = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(d).reduce((o, x) => (o[x.type] = x.value, o), {});
  const y = +p.year, m = +p.month, day = +p.day;
  let hour = +p.hour; if (hour === 24) hour = 0;
  const doy = Math.floor((Date.UTC(y, m - 1, day) - Date.UTC(y, 0, 1)) / 86400000) + 1;
  return { week: Math.min(51, Math.floor((doy - 1) / 7)), sp: hour * 2 + (+p.minute >= 30 ? 2 : 1) };
}

// Each computed lamp trips when "now" leaves the usual half (IQR) of its panel's box-plot — the
// threshold percentile is read LIVE from the same distribution the panel draws (distForDays of the
// wind / reliability / import panels), so a lamp can never disagree with the box beside it. Wind & firm
// are low-is-bad (< P25); imports is high-is-bad (> P75). A distribution that hasn't loaded yet leaves
// its lamp 'unavailable' (the conditions.js guard), degrading only that lamp.
function updateComputedLamps(verdict) {
  const ov = condOverride() || {};
  // live wind capacity factor = live wind output / DUKES total wind nameplate — the SAME figure as
  // the Entry-02 dial, against the P25 of that dial's box-plot.
  const windNameplateMw = (NAMEPLATE ? NAMEPLATE.wind_gw : 32.082) * 1000;
  const windCf = verdict ? (verdict.wind_mw / windNameplateMw) * 100 : NaN;
  const windDist = (CAPACITY && CAPACITY.wind) ? distForDays(CAPACITY.wind, CAPACITY.wind.days) : null;
  const wind = ov.wind || windLullLamp(windCf, windDist ? windDist.p25 : NaN);
  // The lamp both trips on and READS the wind capacity factor (windCf, carried as wind.cfPct) — no
  // demand term, so no apportionment/export question and nothing to attach here.
  // firm share P25: the reliability carpet stores UNRELIABLE share, so firm = 100 − unreliable and
  // P25(firm) = 100 − P75(unreliable).
  const uDist = REL_CARPET ? distForDays(REL_CARPET, REL_CARPET.days) : null;
  const firmP25 = uDist ? 100 - uDist.p75 : NaN;
  const firm = ov.firm || firmMajorityLamp(verdict ? verdict.firm_pct : NaN, firmP25);
  // imports: signed net-import share of interconnector capacity (the Entry-03 needle's basis), against
  // the P75 of that panel's box-plot. Same capacity denominator the panel uses.
  const ipData = window.__importPowerData;
  const impDist = (ipData && ipData.days) ? distForDays(ipData, ipData.days) : null;
  const impCapMw = (ipData && ipData.capacity_mw) || 10300;
  const impPct = (verdict && Number.isFinite(verdict.net_import_mw))
    ? (verdict.net_import_mw / impCapMw) * 100 : NaN;
  const imp = ov.import || heavyImportsLamp(impPct, impDist ? impDist.p75 : NaN);
  // Trip is on capacity (above), but the lamp READS the exposure — net imports as a share of supply
  // (demand) — so attach that for _importStatus. The trigger stays tied to the §03 panel's box-plot.
  const impDemandPct = (verdict && Number.isFinite(verdict.net_import_mw)
    && Number.isFinite(verdict.national_demand_mw) && verdict.national_demand_mw > 0)
    ? (verdict.net_import_mw / verdict.national_demand_mw) * 100 : NaN;
  if (!ov.import && Number.isFinite(impDemandPct)) imp.demandPct = impDemandPct;
  // overcast (solar): conditioned on solar geometry. Live solar CF on the SAME basis as the Entry-02
  // solar dial (solar ÷ latest NESO embedded-solar capacity), looked up against this (week, SP) cell
  // of the conditional grid. A null cell (night) → dark; missing grid/verdict → unavailable.
  let solar = ov.solar;
  if (!solar) {
    const grid = SOLAR_OVERCAST && SOLAR_OVERCAST.grid;
    const solarCapMw = (CAPACITY && CAPACITY.gauge && CAPACITY.gauge.solar_nameplate_mw) || NaN;
    const solarCf = (verdict && Number.isFinite(verdict.solar_mw) && solarCapMw > 0)
      ? verdict.solar_mw / solarCapMw : NaN;
    if (!grid || !verdict) {
      solar = { state: 'unavailable' };
    } else {
      const { week, sp } = londonWeekSP(new Date(verdict.snapshot));
      solar = overcastLamp(solarCf, (grid[week] && grid[week][sp - 1]) || null);
    }
  }
  const windStatus = _windStatus(wind);
  setLamp('cond-wind', wind.state, windStatus, `Wind lull — ${windStatus.replace(/<[^>]+>/g, '')}`);
  const firmStatus = _firmStatus(firm);
  setLamp('cond-firm', firm.state, firmStatus, `Unreliable — ${firmStatus.replace(/<[^>]+>/g, '')}`);
  const importStatus = _importStatus(imp);
  setLamp('cond-import', imp.state, importStatus, `Heavy imports — ${importStatus.replace(/<[^>]+>/g, '')}`);
  const overcastStatus = _overcastStatus(solar);
  setLamp('cond-solar', solar.state, overcastStatus, `Overcast — ${overcastStatus.replace(/<[^>]+>/g, '')}`);
  const wrap = $('conditions');
  if (wrap) wrap.removeAttribute('data-loading');
}

async function updateScarcityLamp() {
  const ov = condOverride();
  let l;
  try {
    l = (ov && ov.scarcity) || scarcityLamp(await resolveWarnings({}));
  } catch {
    l = { state: 'unavailable' };
  }
  setLamp('cond-scarcity', l.state, _scarcityStatus(l), `Scarcity notice — ${_scarcityStatus(l).replace(/<[^>]+>/g, '')}`);
}

// ============================================================ shared years×day-of-year carpet drawer
// Shared by Entry 03 (wind) and Entry 04 (import). DPR-aware.
// cellColorFn: (cellValue) => [r,g,b]. opts: { cellH=22, yAxisId, xAxisId, hatchYears=[] }.
function drawYearDoyCarpet(canvasId, carpet, cellColorFn, opts = {}) {
  const { cellH = 22, yAxisId, xAxisId, hatchYears = [] } = opts;
  const cv = $(canvasId); if (!cv) return;
  const { years, doy, rows } = carpet ?? {};
  if (!years || !doy || !rows) return;
  const cols = doy.length, nRows = years.length;
  const cssW = cv.clientWidth || 960, cssH = nRows * cellH;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(cssW * dpr); cv.height = Math.round(cssH * dpr); cv.style.height = cssH + 'px';
  const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
  const cw = cssW / cols;
  const hatchSet = new Set(hatchYears.map(String));
  years.forEach((y, r) => {
    const row = rows[String(y)];
    if (!row) return;
    for (let c = 0; c < cols; c++) {
      const [rr, gg, bb] = cellColorFn(row[c]);
      ctx.fillStyle = `rgb(${rr},${gg},${bb})`;
      ctx.fillRect(c * cw, r * cellH, Math.ceil(cw) + 0.5, cellH - 1);
    }
    // Partial year: diagonal hatch over the whole row so "year to date" reads at a glance.
    // Transparent enough that null (grey) cells are barely affected.
    if (hatchSet.has(String(y))) {
      ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.32)';
      ctx.lineWidth = 0.8;
      const y0 = r * cellH, h = cellH - 1;
      ctx.beginPath();
      for (let d = -h; d < cssW + h; d += 3) {
        ctx.moveTo(d, y0); ctx.lineTo(d + h, y0 + h);
      }
      ctx.stroke();
      ctx.restore();
    }
  });
  const yAxisEl = yAxisId ? $(yAxisId) : null;
  if (yAxisEl) yAxisEl.innerHTML = years.map((y) => `<span>${y}</span>`).join('');
  const xAxisEl = xAxisId ? $(xAxisId) : null;
  if (xAxisEl) xAxisEl.innerHTML = carpetMonthTicks().map((t) =>
    `<span style="left:${(t.frac * 100).toFixed(2)}%">${t.label}</span>`).join('');
}

// ============================================================ wind unreliability (Entry 03)
function drawWindCarpet(data) {
  window.__windData = data;
  // Same colour as Entry 02 wind carpet: pale = low output (calm), deepening to blue at full output.
  // Anchor 1.0 + DIAL_PALETTE.wind.fullRgb match Entry 02 exactly so the two carpets read consistently.
  drawYearDoyCarpet('wind-carpet', data.carpet, (c) => carpetCellColor(c, 1, DIAL_PALETTE.wind.fullRgb),
    { yAxisId: 'wind-carpet-y', xAxisId: 'wind-carpet-x' });
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
    ctx.fillStyle = INK;
    ctx.fillText(`${rec.days} days`, Math.min(cssW - 48, rx + 4),
      Math.max(12, plotH - (rec.days / maxDays) * plotH - 4));
  }
}

function renderWindUnreliability(data) {
  $('wind-body').innerHTML = `
    <p class="wind-howto"><strong>Every day since 2016.</strong> One row per year (2016 at the top), reading January on the left to December on the right. The colour is that day's wind output — pale when the wind barely turned, deepening to blue when it blew hard (the same key as the carpet in section 02). So the pale patches are the calm spells, and you can see them cluster in some seasons and some years more than others.</p>
    <div class="wind-carpet-cell">
      <div class="wind-yaxis" id="wind-carpet-y"></div>
      <canvas id="wind-carpet" class="wind-carpet" role="img"
        aria-label="Wind daily output for every day since 2016. One row per year (2016 at the top), columns run 1 January (left) to 31 December (right). Pale = a near-calm day with little output; deep blue = a windy day at high output — the same colour key as the section 02 wind carpet."></canvas>
    </div>
    <div class="wind-carpet-x" id="wind-carpet-x"></div>
    <p class="wind-howto"><strong>How long the calm lasts.</strong> Each spike below is a spell when wind output stayed below a tenth of its capacity for one or more days running — taller spikes lasted longer, darker red spikes fell further. The guide lines mark three days, a week and a fortnight.</p>
    <canvas id="wind-drought" class="wind-drought" role="img"
      aria-label="${esc(droughtCaption(data.summary))}"></canvas>
    <p class="wind-caption">${esc(droughtCaption(data.summary))}</p>
    ${entryFooter('wind')}`;
  drawWindCarpet(data);
  drawDroughtPlot(data);
}

// ============================================================ import cost (Entry 04)
function drawImportCarpet(data) {
  const carpet = data?.carpet ?? {};
  const { years, doy } = carpet;
  const capGbp = data.scale?.cap_gbp ?? 10e6;
  drawYearDoyCarpet('import-carpet', carpet, (c) => importValueColor(c, capGbp), {
    yAxisId: 'import-carpet-y',
    xAxisId: 'import-carpet-x',
    hatchYears: data.partial_years || [],
  });
  // Annotation overlay — worked events (painted on top of the carpet)
  const annEl = $('import-carpet-annotations');
  if (annEl && years && doy) {
    annEl.innerHTML = _importAnnotationsHtml(data, years, doy, doy.length, 22);
  }
}

// Build the dot-marker overlay for the import carpet: one subtle spot per costliest day, with no
// text labels — so the carpet stays clean and the spots correspond one-to-one with the table below.
// Dots sit inside .import-carpet-wrap (position:relative) so left/top are relative to the canvas.
function _importAnnotationsHtml(data, years, doy, cols, cellH) {
  // x as % of canvas width, anchored at the left edge of doyIdx column
  const colX = (doyIdx) => ((doyIdx / cols) * 100).toFixed(2) + '%';
  // y in px at the top of yearIdx row
  const rowTop = (yearIdx) => (yearIdx * cellH) + 'px';

  const parts = [];

  // A spot on each of the eight costliest days listed in the table (events[0..7]); events[0] is the
  // record day (data.summary.worst_day). Each dot carries the date + £ as a hover/aria tooltip.
  const dotOffset = (cellH / 2 - 2.5).toFixed(1) + 'px'; // centres dot vertically in the cell
  if (Array.isArray(data.events)) {
    for (const ev of data.events.slice(0, 8)) {
      if (!ev?.date) continue;
      const [eYear, eMon, eDay] = ev.date.split('-');
      const edoyStr = `${eMon}-${eDay}`;
      const edoyIdx = doy.indexOf(edoyStr);
      const eYearIdx = years.indexOf(Number(eYear));
      if (edoyIdx < 0 || eYearIdx < 0) continue;
      const eMon3 = new Date(ev.date + 'T12:00Z').toLocaleString('en-GB', { month: 'short' });
      const eLabel = `${Number(eDay)} ${eMon3} ${eYear} · £${(ev.value_gbp / 1e6).toFixed(1)}m`;
      parts.push(
        `<div class="import-ann-dot" ` +
        `style="left:${colX(edoyIdx)};top:${rowTop(eYearIdx)};transform:translateX(-50%) translateY(${dotOffset})" ` +
        `title="${esc(eLabel)}" aria-label="${esc(eLabel)}"></div>`
      );
    }
  }

  return parts.join('');
}

// Format an events entry as 'D Mon YYYY £X.Xm' for the costliest-days list.
// The live net-imports receipt under the import dial (shared by the homepage rate panel and the
// detail-page daily panel): MW imported, share of demand, and the system price, or an honest
// feed-state note when the live block is absent (the dial still reads £0, never a placeholder).
// The receipt under the import-page dials shows two distinct readings, never conflated: the LIVE net
// imports right now (the same instantaneous figure the homepage Imports panel shows), and the latest
// SETTLED half-hour — which is what the £ valuation prices, since only settled half-hours carry a
// system price. `settled` is the build-snapshot import block; `liveVerdict` is the live verdict.
function _importReceiptHtml(settled, liveVerdict) {
  let liveLine = '';
  if (liveVerdict && Number.isFinite(liveVerdict.net_import_mw)) {
    const lmw = Math.round(liveVerdict.net_import_mw).toLocaleString('en-GB');
    const lpct = (Number.isFinite(liveVerdict.national_demand_mw) && liveVerdict.national_demand_mw > 0)
      ? `(<span class="num">${(liveVerdict.net_import_mw / liveVerdict.national_demand_mw * 100).toFixed(1)}%</span> of demand)`
      : '';
    liveLine = `<p class="import-receipt-line">Live now: <strong class="num">${lmw} MW</strong> ${lpct}</p>`;
  }
  if (!settled) {
    return liveLine || `<p class="import-unavail">Live import rate not yet returned — dial shows £0.</p>`;
  }
  const mw = settled.net_import_mw != null ? Math.round(settled.net_import_mw).toLocaleString('en-GB') : '—';
  const pct = settled.import_pct != null ? settled.import_pct.toFixed(1) : '—';
  const price = settled.price_per_mwh != null ? `£${settled.price_per_mwh.toFixed(2)}/MWh` : '—';
  const stamp = settled.price_stamp ? `<span class="import-stamp">${esc(settled.price_stamp)}</span>` : '';
  return `${liveLine}
      <p class="import-receipt-line">
        Latest settled half-hour: <strong class="num">${mw} MW</strong>
        (<span class="num">${pct}%</span> of demand)
        · at <strong class="num">${price}</strong>
      </p>
      ${stamp}`;
}

// Import-page money analysis — the rolling-year spend RATE (£/h): a linear, ring-calibrated dial (NO
// big value call-out) beside the rolling-year hour×date rate carpet, with the same box-plot legend.
// Lives on import.html (#import-rate-body); the homepage shows the power/capacity sibling instead.
function renderImportRate(data, live, liveVerdict) {
  window.__importRateData = data;
  const cap = data.cap_per_h || 1e6;
  const dist = data.distribution || null;            // raw £/h percentiles {p10..p90, mean}
  const pal = IMPORT_DIAL_PALETTE;
  const P = (v) => Math.max(0, Math.min(100, (Math.max(v, 0) / cap) * 100));   // linear £/h -> bar %

  // Live "now" = the current import-spend rate (£/h) from the build snapshot; £0 when Britain was
  // exporting (the £ value floors at zero) or when there is no live rate.
  const liveRate = (live && Number.isFinite(live.rate_per_h)) ? Math.max(0, live.rate_per_h) : 0;

  // No dial here. A £/h spend rate is unbounded and signed, so a half-dial (which reads as a bounded
  // fraction of a fixed full-scale) is the wrong instrument — its 0–100% ring is meaningless and it
  // only restates the horizontal bar + box-plot to the right. The left column leads with the rate
  // itself, read against the year's typical (mean); the live + settled receipt hangs below it.
  const typical = dist && Number.isFinite(dist.mean) ? Math.max(0, dist.mean) : null;
  let rateSub;
  if (liveRate <= 0) {
    rateSub = 'no import spend — Britain was a net exporter';
  } else if (typical && typical > 0) {
    const r = liveRate / typical;
    rateSub = r >= 1.15 ? `${r.toFixed(1)}× the year's typical ${fmtRatePerH(typical)}`
            : r <= 0.85 ? `below the year's typical ${fmtRatePerH(typical)}`
            : "about the year's typical rate";
  } else {
    rateSub = 'latest settled half-hour';
  }
  const gaugeHtml = `<p class="import-rate-readout">${fmtRatePerH(liveRate)}</p>`
    + `<p class="import-rate-sub">${rateSub}</p>`;

  // Legend bar sampled from the SAME linear carpet ramp (carpetCellColor) so a position's colour
  // matches the carpet cell of the rate that sits there. £/h formatting, box-plot on the rate dist.
  const N = 24;
  const barCss = `linear-gradient(to right, ${Array.from({ length: N }, (_, i) => {
    const t = i / (N - 1);
    const [r, g, b] = carpetCellColor(t * cap, cap, pal.fullRgb);
    return `rgb(${r},${g},${b}) ${(t * 100).toFixed(1)}%`;
  }).join(', ')})`;
  const legendHtml = legendFor('import', liveRate, pal, dist, null, null, null,
    { scale: { posFn: P, fmt: fmtRatePerH, period: 'half-hour' }, barCss, lo: '£0', hi: fmtRatePerH(cap) });

  $('import-rate-body').innerHTML = `
    <div class="trap-grid">
      ${renderMetricBlock({
        kind: 'import', label: 'Spend rate', palette: pal, days: data.days,
        gaugeHtml, gaugeExtra: _importReceiptHtml(live, liveVerdict), legendHtml,
        carpetAria: 'GB import-spend rate, every half-hour of the last year. Date runs left to right; time of day runs top (00:00) to bottom (24:00). Pale = little or no import spend; deepening red = paying more to import.',
      })}
    </div>
    ${entryFooter('imports')}`;
  syncBlockHeights();
  drawCarpetCanvas('carpet-import', data.days, cap, pal.fullRgb, { keepWorstHigh: true });
}

// Homepage Imports panel — net imports as a share of GB interconnector capacity: a true §02 (wind/
// solar) sibling. % inner ring + MW outer ring (to the full ~10.3 GW fleet), the rolling-year hour×
// date capacity-factor carpet, the standard box-plot legend, magenta (the verdict's import hue). The
// live needle reads the SAME verdict the gauge + conditions lamp use; the £ cost story lives on
// import.html. Re-rendered each poll via updateImportPowerPanel.
function renderImportPower(data, verdict) {
  window.__importPowerData = data;
  const has = !!(data && data.days && data.days.length);
  const capMw = (data && data.capacity_mw) || 10300;
  const days = has ? data.days : null;
  const dist = has ? distForDays(data, days) : null;
  const liveNet = verdict && Number.isFinite(verdict.net_import_mw) ? Math.max(0, verdict.net_import_mw) : 0;
  const netRaw = verdict && Number.isFinite(verdict.net_import_mw) ? verdict.net_import_mw : null;
  const demandMw = verdict && Number.isFinite(verdict.national_demand_mw) ? verdict.national_demand_mw : null;
  $('import-body').innerHTML = `
    <div class="trap-grid${has ? '' : ' gauge-only'}">
      ${renderMetricBlock({
        kind: 'import', label: 'Imports', palette: DIAL_PALETTE.import,
        nameplateMw: capMw, sat: has ? data.sat : 1, days, dist,
        liveCf: capMw ? liveNet / capMw : 0,
        unitNoun: 'interconnector capacity',
        legendLabels: { lo: 'No imports', hi: 'Full capacity' },
        gaugeExtra: dialNowLine('import', netRaw, demandMw, 'demand'),   // live net imports + share of demand (exposure)
        gaugeLabel: 'Imports — net imports as a share of interconnector capacity',
        carpetAria: 'Net imports as a share of GB interconnector capacity, every half-hour of the last year. Date runs left to right; time of day runs top (00:00) to bottom (24:00). Pale = little or no import; deepening magenta = leaning harder on imports.',
      })}
    </div>
    ${entryFooter('imports', [{ href: 'import.html', label: 'What those imports cost: the £ history since 2016' }])}`;
  if (has) {
    syncBlockHeights();
    drawCarpetCanvas('carpet-import', data.days, data.sat, DIAL_PALETTE.import.fullRgb, { keepWorstHigh: true });
  }
}

// Re-render the homepage import-power panel from the live verdict each poll, so its needle reads the
// same net-import snapshot as the verdict gauge + conditions lamp.
function updateImportPowerPanel(v) {
  if (!window.__importPowerData || !$('import-body')) return;
  renderImportPower(window.__importPowerData, v);
}

function renderImportCost(data, live) {
  const capGbp = data.scale?.cap_gbp ?? 20e6;
  const dist = data.distribution || null;
  const pal = IMPORT_DIAL_PALETTE;

  // One shared non-linear (sqrt) £/day scale for the dial, legend and carpet, capped at the record
  // day so the £94m extreme is on-scale. norm maps £ -> 0..1 along the scale; P -> 0..100 bar %.
  const norm = (v) => Math.sqrt(Math.min(Math.max(v, 0), capGbp) / capGbp);
  const P = (v) => Math.max(0, Math.min(100, norm(v) * 100));
  const fmtGbp = (v) => {
    const m = v / 1e6;
    if (m >= 1000) return `£${(m / 1000).toFixed(1)}bn`;
    if (m >= 10) return `£${Math.round(m)}m`;
    return `£${m.toFixed(1)}m`;
  };

  // Today's run-rate (the current £/h projected over 24h) — only used to mark the "now" caret on the
  // legend scale; this section has no dial (the spend-rate section above carries the live receipt).
  const liveRateH = (live && Number.isFinite(live.rate_per_h)) ? Math.max(0, live.rate_per_h) : 0;
  const runRate = liveRateH * 24;

  // The carpet (year x day-of-year) markup — painted by drawImportCarpet after insertion.
  const carpetHtml = `
        <div class="import-carpet-cell">
          <div class="import-yaxis" id="import-carpet-y"></div>
          <div class="import-carpet-wrap">
            <canvas id="import-carpet" class="import-carpet" role="img"
              aria-label="Daily GB net import cost since 2016. One row per year, columns run January to December. Pale = cheap or no imports; deep red = expensive import day."></canvas>
            <div class="import-carpet-annotations" id="import-carpet-annotations" aria-hidden="true"></div>
          </div>
        </div>
        <div class="import-carpet-x" id="import-carpet-x"></div>`;

  // The legend: the shared legendFor box-plot, on the sqrt £ scale. The bar samples the carpet ramp
  // at t^2 (positions are sqrt, importValueColor is sqrt) so bar colour at each position matches the
  // carpet cell of the value that sits there.
  const N = 24;
  const barCss = `linear-gradient(to right, ${Array.from({ length: N }, (_, i) => {
    const t = i / (N - 1);
    const [r, g, b] = importValueColor(t * t * capGbp, capGbp);
    return `rgb(${r},${g},${b}) ${(t * 100).toFixed(1)}%`;
  }).join(', ')})`;
  const legendHtml = legendFor('import', runRate, pal, dist, null, null, null,
    { scale: { posFn: P, fmt: fmtGbp }, barCss, lo: 'cheaper', hi: 'costlier' });

  // Caption, source line and costliest-days table — stacked under the full-width carpet.
  const costliestHtml = (Array.isArray(data.events) && data.events.length > 0)
    ? `<table class="costliest-table">
        <caption>Costliest days since 2016</caption>
        <tbody>${data.events.slice(0, 8).map((ev) => {
          const [y, , d] = ev.date.split('-');
          const mon = new Date(ev.date + 'T12:00Z').toLocaleString('en-GB', { month: 'short' });
          return `<tr><td>${Number(d)} ${mon} ${y}</td><td class="n">£${(ev.value_gbp / 1e6).toFixed(1)}m</td></tr>`;
        }).join('')}</tbody>
      </table>`
    : '';
  const stripExtra = `
      <p class="wind-caption">${esc(importCostCaption(data.summary))}</p>
      ${costliestHtml}`;

  // No dial in this section — the daily-cost carpet spans full width, the box-plot legend above it.
  $('import-detail-body').innerHTML = `
    <div class="import-full">
      ${legendHtml}
      ${carpetHtml}
      ${stripExtra}
    </div>
    ${entryFooter('imports')}`;

  drawImportCarpet(data);
}

// ============================================================ orchestration
// Console diagnostics for the live layer. Wind & solar come only from the NESO embedded feed
// (a separate origin from Elexon); when it fails the whole live reading falls back. Nothing was
// logged before, so those drops were invisible — this surfaces the mode and per-feed status each
// cycle so a real failure can be diagnosed from the browser console.
function logLiveCycle(state) {
  const feeds = state.feeds || {};
  const summary = Object.entries(feeds)
    .map(([k, f]) => `${k}:${f.status}${f.latencyMs != null ? `/${f.latencyMs}ms` : ''}`).join(' ');
  const line = `[grid] ${state.mode} · ${summary || 'no feed status'}${state.reason ? ` · ${state.reason}` : ''}`;
  if (state.mode === 'live') console.info(line);
  else console.warn(line, { lastUpdated: state.lastUpdated });
  return summary;
}

async function refreshLive() {
  try {
    const state = await resolveState({}, () => Date.now());
    const feedSummary = logLiveCycle(state);
    renderVerdict(state);
    updateComputedLamps(state.verdict);
    updateImportPowerPanel(state.verdict);
    $('clockstrip').textContent = `${state.lastUpdated}`;
    const dot = $('live-dot');   // live = the normal state: show nothing; only surface a degraded state
    dot.textContent = state.mode === 'live' ? '' : state.mode === 'fallback' ? 'Last good' : 'Offline';
    dot.title = state.mode === 'live' ? '' : `${state.reason || state.lastUpdated} — feeds ${feedSummary}`;
    dot.hidden = state.mode === 'live';
  } catch (e) {
    console.error('[grid] live layer threw', e);
    $('verdict-body').innerHTML = `<p class="warn">Live layer error — no current reading. ${esc(e.message || e)}</p>`;
    $('entry-trap').hidden = true;
    updateComputedLamps(null);
  }
}

// One app.js drives three pages, each rendering only the blocks whose host elements are present:
// the homepage (live verdict + reliability + capacity + the rolling-year Imports rate panel),
// wind.html (the wind-unreliability detail), and import.html (the all-time daily import-cost detail).
// Each section fetches its own data and degrades independently; the live layer + polling run on the
// homepage only (detected by #verdict-body).
async function main() {
  const isHome = !!$('verdict-body');

  // Shared anchor: DUKES nameplate (the capacity-trap denominator + the wind carpet's basis).
  try {
    NAMEPLATE = await getJSON('data/nameplate.json');
  } catch (e) { /* nameplate failure is non-fatal; defaults apply */ }

  if (isHome) {
    // The reliability carpet (Entry 01, under the gauge) is independent: its own fetch so a missing
    // file omits only the carpet, never the live gauge above it. renderReliabilityBlock runs from
    // renderVerdict each poll, so loading the data here is enough.
    try { REL_CARPET = await getJSON('data/reliability_carpet.json'); }
    catch (e) { REL_CARPET = null; }
    // capacity carpets (Entry 02 right panels) — independent fetch so a missing file degrades
    // only the carpets, never the gauge or the other history entries.
    try { CAPACITY = await getJSON('data/capacity_carpets.json'); }
    catch (e) { CAPACITY = null; }
    // Conditional solar 'overcast' grid (OVERCAST lamp) — independent fetch; a miss just leaves the
    // lamp unavailable.
    try { SOLAR_OVERCAST = await getJSON('data/solar_overcast.json'); }
    catch (e) { SOLAR_OVERCAST = null; }
  }

  // Wind-unreliability detail (wind.html, #wind-body) — independent fetch.
  if ($('wind-body')) {
    try {
      const windData = await getJSON('data/wind_unreliability.json');
      renderWindUnreliability(windData);
    } catch (e) {
      $('wind-body').innerHTML = `<p class="warn">Wind unreliability data unavailable. ${esc(e.message || e)}</p>`;
    }
  }

  // The live import price block (build snapshot) feeds the import-page money analyses.
  const importLive = async () => {
    try { return (await getJSON('data/latest.json')).import ?? null; }
    catch (e) { return null; }   // price block unavailable — the dial reads £0, never a placeholder
  };

  // The live verdict — the SAME instantaneous net-imports figure the homepage Imports needle shows —
  // gives the import page its "Live now" line, beside the settled half-hour the £ valuation prices.
  // Computed once here; if the live layer is unavailable the receipt falls back to the settled line.
  let importLiveVerdict = null;
  if ($('import-detail-body') || $('import-rate-body')) {
    try { importLiveVerdict = (await resolveState({}, () => Date.now())).verdict ?? null; }
    catch (e) { /* live verdict unavailable — the receipt shows the settled line only */ }
  }

  // Import-cost detail (import.html, #import-detail-body) — the all-time daily £ carpet + £94m record.
  if ($('import-detail-body')) {
    try {
      const importData = await getJSON('data/import_cost.json');
      window.__importData = importData;
      renderImportCost(importData, await importLive());
    } catch (e) {
      $('import-detail-body').innerHTML = `<p class="warn">Import-cost data unavailable. ${esc(e.message || e)}</p>`;
    }
  }

  // Import-page money analysis (import.html, #import-rate-body) — the rolling-year £/h spend rate.
  if ($('import-rate-body')) {
    try {
      const rateData = await getJSON('data/import_rate.json');
      renderImportRate(rateData, await importLive(), importLiveVerdict);
    } catch (e) {
      $('import-rate-body').innerHTML = `<p class="warn">Import-rate data unavailable. ${esc(e.message || e)}</p>`;
    }
  }

  // Homepage Imports panel (#import-body) — net imports as a share of interconnector capacity (the §02
  // sibling). The carpet is settled; the dial needle is kept live by refreshLive (updateImportPowerPanel)
  // off the same verdict as the gauge + conditions lamp. First paint uses the build-snapshot verdict.
  if ($('import-body')) {
    try {
      window.__importPowerData = await getJSON('data/import_power.json');
      let v0 = null;
      try { v0 = (await getJSON('data/latest.json')).verdict ?? null; } catch (e) { /* dial reads 0 */ }
      renderImportPower(window.__importPowerData, v0);
    } catch (e) {
      $('import-body').innerHTML = `<p class="warn">Import data unavailable. ${esc(e.message || e)}</p>`;
    }
  }

  if (isHome) {
    await refreshLive();
    setInterval(refreshLive, POLL_MS);
    updateScarcityLamp();
    setInterval(updateScarcityLamp, POLL_MS);
  }

  let t;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => {
    if (CAPACITY && CAPACITY.sat) syncBlockHeights();
    if (CAPACITY && CAPACITY.wind && CAPACITY.sat) drawCarpetCanvas('carpet-wind', CAPACITY.wind.days, CAPACITY.sat.wind, DIAL_PALETTE.wind.fullRgb);
    if (CAPACITY && CAPACITY.solar && CAPACITY.sat) drawCarpetCanvas('carpet-solar', CAPACITY.solar.days, CAPACITY.sat.solar, DIAL_PALETTE.solar.fullRgb);
    if (REL_CARPET && REL_CARPET.days) drawReliabilityLine('carpet-reliability', REL_CARPET.days);
    if (window.__windData) { drawWindCarpet(window.__windData); drawDroughtPlot(window.__windData); }
    if (window.__importData) drawImportCarpet(window.__importData);
    if (window.__importRateData) { syncBlockHeights(); drawCarpetCanvas('carpet-import', window.__importRateData.days, window.__importRateData.cap_per_h, IMPORT_DIAL_PALETTE.fullRgb, { keepWorstHigh: true }); }
    if (window.__importPowerData) { syncBlockHeights(); drawCarpetCanvas('carpet-import', window.__importPowerData.days, window.__importPowerData.sat, DIAL_PALETTE.import.fullRgb, { keepWorstHigh: true }); }
  }, 150); });
}

main();
