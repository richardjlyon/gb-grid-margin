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
  gaugeNeedleAngle, cfToInk, tallyGroups, firmStatus, sourceArcModel, COL_EXPORT,
  fmtGW, fmtMW,
  reliableShareToColor, rgbCss, unreliableNowPct,
  binSeriesToColumns, reliabilityAxisTicks,
  carpetCellColor, gaugeCalibration,
} from './render.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 5 * 60 * 1000;

let LAST_STATE = null;   // last live state, so the reliability caret can re-place without a refetch

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
function buildGauge(value, max, { armed = false, danger = null, reliable = null,
                                  calibration = null, label = 'gauge', dist = null,
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
    const arc = (lo, hi, color) => `<path d="${arcPath(cx, cy, R, lo, hi, max)}" fill="none" stroke="${color}" stroke-width="7"/>`;
    distArcs = arc(dist.p10, dist.p90, palette.band) + arc(dist.p25, dist.p75, palette.core);  // 9-in-10, then the usual half
    const c = Number.isFinite(dist.mean) ? dist.mean : dist.p50;   // central tick = the average (load factor)
    const [mx1, my1] = arcPoint(cx, cy, R + 5, c, max);
    const [mx2, my2] = arcPoint(cx, cy, R - 5, c, max);
    median = `<line x1="${mx1.toFixed(1)}" y1="${my1.toFixed(1)}" x2="${mx2.toFixed(1)}" y2="${my2.toFixed(1)}" stroke="#15181c" stroke-width="2.2"/>`;
  }
  let cal = '';
  if (calibration) {
    for (const t of calibration) {
      const v = t.frac * max;
      const [ix, iy] = arcPoint(cx, cy, R - 17, v, max);
      cal += `<text x="${ix.toFixed(1)}" y="${(iy + 3).toFixed(1)}" class="g-pct" text-anchor="middle">${t.label_pct}</text>`;
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
    <path d="${arcPath(cx, cy, R, 0, max, max)}" fill="none" stroke="${palette.track}" stroke-width="7"/>
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
  LAST_STATE = state;   // cached so the reliability caret can re-place without a refetch
  const badge = state.mode === 'live' ? ''   // live is the normal state — no label, only flag the abnormal
    : `<span class="modebadge ${state.mode}">${state.mode}</span>`;
  $('verdict-mode').innerHTML = badge;

  if (!state.verdict) {
    $('verdict-body').innerHTML =
      `<p class="warn">No current reading. ${esc(state.reason || state.lastUpdated || '')}</p>`;
    $('entry-trap').hidden = true;
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
}

// Per-source colour identities. The dial bands use three shades (track / 9-in-10 / usual-half), luma-
// matched to the original greys (218/185/130) so perceived brightness is unchanged; `full` (+ fullRgb)
// is the saturated end of the carpet & legend ramp (white = no output → this hue = full output).
// Blue = wind, yellowy-orange = solar.
const DIAL_PALETTE = {
  wind: { track: '#cbdef0', band: '#9cbfe3', core: '#4e8dcd', full: '#1f6fc0', fullRgb: [31, 111, 192] },
  solar: { track: '#e8d9be', band: '#d4b684', core: '#b17c23', full: '#e0921a', fullRgb: [224, 146, 26] },
};

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

// Entry 02: one block per source (wind, then solar). Each block is a full-width source label row,
// then the live dial (1/3 column) beside its half-hourly carpet (2/3 column), then an aligned row
// of the two source lines. A single colour legend sits above. No combined/aggregate gauge — solar
// must not flatter the wind reading; each uses its own nameplate so dial and carpet share a basis.
function renderTrap(v) {
  $('entry-trap').hidden = false;
  const dukesWind = NAMEPLATE ? NAMEPLATE.wind_gw : 32.082;
  const dukesSolar = NAMEPLATE ? NAMEPLATE.solar_gw : 18.28;
  const g = (CAPACITY && CAPACITY.gauge) || {};
  const windCapMw = g.wind_nameplate_mw || Math.round(dukesWind * 1000);
  const solarCapMw = g.solar_nameplate_mw || Math.round(dukesSolar * 1000);
  const hasCarpets = !!(CAPACITY && CAPACITY.wind && CAPACITY.solar && CAPACITY.sat);

  // Per-source dial palettes — three shades each (track / 9-in-10 band / usual-half core), luma-
  // matched to the original greys (218/185/130) so perceived brightness is unchanged. Blue = wind,
  // yellowy-orange = solar.
  const gaugeFor = (sourceMw, capMw, label, dist, palette) => buildGauge(capMw ? (sourceMw / capMw) * 100 : 0, 100, {
    label, calibration: gaugeCalibration(capMw), dist, palette,
  });
  const srcP = (cls, txt) =>
    `<p class="src trap-src ${cls}">Source: ${esc(txt)} · <a href="methodology.html#capacity-trap">→ method</a></p>`;

  // Mean capacity factor over the rolling year (all half-hourly cells) — the "rarely tops a quarter"
  // fact, stated in the label row beside the live dial.
  const avgPct = (kind) => {
    if (!hasCarpets) return null;
    let s = 0, n = 0;
    for (const d of CAPACITY[kind].days) for (const cf of d.cf) if (cf != null) { s += cf; n += 1; }
    return n ? Math.round((s / n) * 100) : null;
  };

  // Output distribution over the rolling year (half-hourly cells) — painted onto the dial so "now"
  // reads against where output sits. The CENTRAL marker is the MEAN (= the load factor / annual
  // capacity factor), not the median: solar is dark over half the year, so its median is 0% — a fact
  // about the Earth's rotation, not about the panels. The mean is the fair, standard "what it
  // delivers" figure. The percentile band stays as the variability picture. Memoised on the payload.
  const distFor = (kind) => {
    if (!hasCarpets) return null;
    const node = CAPACITY[kind];
    if (node._dist) return node._dist;
    const vals = [];
    for (const d of node.days) for (const cf of d.cf) if (cf != null) vals.push(cf);
    if (!vals.length) return null;
    const mean = (vals.reduce((s, v) => s + v, 0) / vals.length) * 100;
    vals.sort((a, b) => a - b);
    const q = (p) => vals[Math.min(vals.length - 1, Math.floor(p * vals.length))] * 100;
    return (node._dist = { p10: q(0.1), p25: q(0.25), p50: q(0.5), p75: q(0.75), p90: q(0.9), mean });
  };

  // Each source gets its own colour legend, sharing its label's row in the stripe column (so it is
  // the same width as the stripe below it) and carrying a live "now" caret at the instantaneous
  // capacity-factor reading — the same value the dial needle points to.
  const legendFor = (kind, cf, pal, dist) => {
    const satFull = (CAPACITY && CAPACITY.sat && CAPACITY.sat[kind]) || 1;
    const L = (frac) => Math.max(0, Math.min(100, (frac / satFull) * 100));   // a 0..1 cf -> bar %
    const pos = L(cf);
    // distribution box-plot below the bar (same scale, recoloured into the source hue to match the
    // dial bands): p10–p90 whisker (pal.band), p25–p75 usual half (pal.core), and an AVERAGE tick
    // (ink) — the mean / load factor, not the median (see distFor). Numbers label the 9-in-10 ends
    // and the average.
    let box = '';
    if (dist) {
      const x = (pPct) => L(pPct / 100);   // dist percentiles are 0..100
      const [p10, p90] = [dist.p10, dist.p90].map(Math.round);
      const [p25, p75] = [dist.p25, dist.p75].map(Math.round);
      const avg = Math.round(dist.mean);
      box = `
        <span class="cl-box" aria-hidden="true" title="last year: average ${avg}%, usual half ${p25}–${p75}%, 9-in-10 ${p10}–${p90}% of capacity">
          <span class="cl-box-line" style="left:${x(dist.p10).toFixed(1)}%; width:${(x(dist.p90) - x(dist.p10)).toFixed(1)}%; background:${pal.band}"></span>
          <span class="cl-box-iqr" style="left:${x(dist.p25).toFixed(1)}%; width:${(x(dist.p75) - x(dist.p25)).toFixed(1)}%; background:${pal.core}"></span>
          <span class="cl-box-avg" style="left:${x(dist.mean).toFixed(1)}%"></span>
        </span>
        ${numsRow([
          { pos: x(dist.p10), txt: `${p10}%`, color: pal.core, pr: 1 },   // widest interval (9-in-10) ends
          { pos: x(dist.mean), txt: `${avg}%`, cls: 'cl-num-avg', pr: 2 },  // average (mean / load factor)
          { pos: x(dist.p90), txt: `${p90}%`, color: pal.core, pr: 1 },
        ])}`;
    }
    return `
    <div class="carpet-legend">
      <span class="cl-lab">No output</span>
      <span class="cl-bar-wrap">
        <span class="cl-bar" style="background:linear-gradient(90deg in oklab, #fbfbf9, ${pal.full})" aria-hidden="true"></span>
        <span class="cl-now" style="left:${pos.toFixed(1)}%" title="Now: ${Math.round(cf * 100)}% of capacity">now</span>
        ${box}
      </span>
      <span class="cl-lab">Full output</span>
    </div>`;
  };

  const block = (kind, label, sourceMw, capMw, gaugeSrc, carpetSrc) => {
    const pal = DIAL_PALETTE[kind];
    const gauge = gaugeFor(sourceMw, capMw, `${label} output as a share of installed capacity`, distFor(kind), pal);
    const avg = avgPct(kind);
    const avgNote = avg == null ? '' : `<span class="trap-avg">averages ${avg}% of capacity over the year</span>`;
    const cf = capMw ? (sourceMw / capMw) : 0;
    // A single annotation — under solar only, to conserve space — explaining the hybrid box-whisker
    // key that sits above each carpet (it serves both sources and the dial bands, same scheme).
    const keyNote = (hasCarpets && kind === 'solar')
      ? `<p class="trap-note">Reading the key above each carpet: the thin line spans the middle 9 in 10 half-hours over the last year, the thick bar the <strong>usual half</strong> (the middle 50% of readings), and the tick the <strong>average</strong>; the &#8220;now&#8221; caret and the dial needle mark the latest half-hour.</p>`
      : '';
    const strip = hasCarpets ? `
      <div class="carpet-cell">
        <div class="carpet-stage">
          <div class="carpet-yaxis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>
          <canvas id="carpet-${kind}" class="carpet" role="img"
            aria-label="${esc(label)} capacity factor, every half-hour of the last year. Date runs left to right; time of day runs top (00:00) to bottom (24:00). White = no output, deepening colour = toward full capacity."></canvas>
        </div>
        <div class="carpet-xaxis" id="carpet-${kind}-x"></div>
      </div>
      ${srcP('trap-src-gauge', gaugeSrc)}
      ${srcP('trap-src-strip', carpetSrc)}`
      : srcP('trap-src-gauge', gaugeSrc);
    return `
      <p class="trap-label">${esc(label)}${avgNote}</p>
      ${hasCarpets ? legendFor(kind, cf, pal, distFor(kind)) : ''}
      <div class="trap-gauge-cell"><div class="gauge-block">${gauge}</div></div>
      ${strip}
      ${keyNote}`;
  };

  const windGaugeSrc = 'Live: Elexon FUELINST + NESO embedded forecast / DUKES 6.2 wind nameplate';
  const solarGaugeSrc = 'Live: NESO embedded forecast / NESO embedded-solar capacity';
  const cWind = (CAPACITY && CAPACITY.source_wind) || windGaugeSrc;
  const cSolar = (CAPACITY && CAPACITY.source_solar) || solarGaugeSrc;

  $('trap-body').innerHTML = `
    <div class="trap-grid${hasCarpets ? '' : ' gauge-only'}">
      ${block('wind', 'Wind', v.wind_mw || 0, windCapMw, windGaugeSrc, cWind)}
      ${block('solar', 'Solar', v.solar_mw || 0, solarCapMw, solarGaugeSrc, cSolar)}
    </div>`;

  if (hasCarpets) {
    syncCarpetHeight();
    drawCarpet('carpet-wind', CAPACITY.wind.days, CAPACITY.sat.wind, DIAL_PALETTE.wind.fullRgb);
    drawCarpet('carpet-solar', CAPACITY.solar.days, CAPACITY.sat.solar, DIAL_PALETTE.solar.fullRgb);
  }
}

// Match each carpet to the VISIBLE DIAL height beside it (the semicircle arc, not the gauge's full
// SVG box, which carries the calibration labels above/below). The arc spans radius R of the viewBox
// width, so its rendered height is gaugeWidth × R/viewBoxWidth. Mirrored onto the grid as --carpet-h
// before drawCarpet so the canvas measures the right height.
const DIAL_ARC_RATIO = 86 / 232;   // buildGauge R / viewBox width — keep in sync with buildGauge
function syncCarpetHeight() {
  const gauge = document.querySelector('.trap-gauge-cell .gauge');
  const grid = document.querySelector('.trap-grid');
  if (!gauge || !grid) return;
  const h = Math.round(gauge.getBoundingClientRect().width * DIAL_ARC_RATIO);
  if (h > 0) grid.style.setProperty('--carpet-h', `${h}px`);
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

// ============================================================ the wind stripe
let STRIPE = null;
let CAPACITY = null;   // site/data/capacity_carpets.json (wind + solar half-hourly CF grids)
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

// A carpet plot: x = date (oldest left → newest right), y = time of day (SP1=00:00 top → SP48
// bottom). Each cell coloured by its half-hourly capacity factor (carpetCellColor): white = no
// output, deepening to `full` (the source hue) at full capacity. The date axis is lowest-output-wins
// downsampled so a sub-pixel calm spell (now palest) is never averaged out. DPR-aware; redrawn on
// resize, with its month axis re-laid out to match.
function drawCarpet(canvasId, days, satFull, full) {
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
      let minCf = Infinity, saw = false;
      for (let d = d0; d < d1 && d < nDays; d++) {
        const v = days[d].cf[p];               // oldest (first) day at the left
        if (v != null) { saw = true; if (v < minCf) minCf = v; }
      }
      const [r, g, b] = carpetCellColor(saw ? minCf : null, satFull, full);
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(sx, p * rowH, 1, Math.ceil(rowH));
    }
  }
  layoutCarpetAxis(canvasId.replace('carpet-', ''), days);
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
let REL_ROLLING = null, REL_ALL = null, REL_ALL_PROMISE = null, REL_MODE = 'rolling';
// (ramp constants live in render.js — RELIABILITY_RAMP, reliableShareToColor, rgbCss)
function relColour(s) { return rgbCss(reliableShareToColor(s)); }

function drawReliabilityKey() {
  const cv = $('reliability-key');
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = cv.clientWidth, cssH = cv.clientHeight;
  cv.width = Math.round(cssW * dpr);
  cv.height = Math.round(cssH * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  // left = 0% unreliable (firm = 1, pale) … right = 100% unreliable (firm = 0, red)
  for (let i = 0; i < cssW; i++) { ctx.fillStyle = relColour(1 - i / (cssW - 1)); ctx.fillRect(i, 0, 1, cssH); }
}

function layoutReliabilityAxis(cssW, mode = 'rolling') {
  const months = $('reliability-months'), years = $('reliability-years');
  if (!months || !years) return;
  months.innerHTML = ''; years.innerHTML = '';
  const ticks = reliabilityAxisTicks(Date.parse(RELIABILITY.start_utc), RELIABILITY.step_minutes * 60000,
    RELIABILITY.values.length, mode);
  let lastX = -999;
  for (const m of ticks.months) {
    const x = m.frac * cssW;
    if (x - lastX < 30) continue;                     // responsive thinning
    lastX = x;
    const el = document.createElement('span');
    el.textContent = m.label; el.style.left = `${x}px`; months.appendChild(el);
  }
  for (const y of ticks.years) {
    const el = document.createElement('span');
    el.textContent = y.label; el.style.left = `${y.frac * cssW}px`; years.appendChild(el);
  }
}

function drawReliabilityStripe() {
  if (!RELIABILITY) return;
  const canvas = $('reliability-canvas');
  if (!canvas) return;
  const vals = RELIABILITY.values;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  const cols = binSeriesToColumns(vals, cssW);
  for (let sx = 0; sx < cssW; sx++) {
    ctx.fillStyle = relColour(cols[sx]);
    ctx.fillRect(sx, 0, 1, cssH);
  }
  layoutReliabilityAxis(cssW, REL_MODE);
}

function renderReliabilityStripe() {
  if (!RELIABILITY) return;
  const r = RELIABILITY;
  $('reliability-body').innerHTML = `
    <div class="rel-strip">
      <div class="rel-head">
        <p class="rel-cap">The same measure, ${REL_MODE === 'all' ? 'every half-hour since 2016' : 'every half-hour of the last year'} — <strong>pale</strong> where firm power carried demand, <strong>red</strong> where the grid leaned on weather and imports.</p>
        <div class="rel-toggle" role="group" aria-label="Stripe range">
          <button type="button" data-range="rolling" aria-pressed="${REL_MODE === 'rolling'}"${REL_MODE === 'rolling' ? ' class="on"' : ''}>Rolling year</button>
          <button type="button" data-range="all" aria-pressed="${REL_MODE === 'all'}"${REL_MODE === 'all' ? ' class="on"' : ''}>Since 2016</button>
        </div>
        <div class="rel-key">
          <span class="rel-key-lab">unreliable share of demand</span>
          <div class="rel-key-wrap">
            <canvas id="reliability-key" width="300" height="18"></canvas>
            <span class="rel-now" id="reliability-now" hidden>now</span>
          </div>
          <div class="rel-key-ticks"><span>0%</span><span>100%</span></div>
          <p class="rel-key-note">scale saturates at 40% firm</p>
        </div>
      </div>
      <canvas id="reliability-canvas" role="img"
        aria-label="Reliable (firm) share of GB demand, every half-hour from ${esc(r.range.from)} to ${esc(r.range.to)}: pale where firm power carried demand, red where it leaned on weather and imports."></canvas>
      <div class="rel-axis"><div class="rel-months" id="reliability-months"></div><div class="rel-years" id="reliability-years"></div></div>
      <p class="caveat"><strong>Settled history, about three weeks behind live.</strong> The stripe is settled Elexon FUELHH with NESO’s embedded outturn estimates; the live gauge and the ‘now’ marker read NESO’s embedded <em>forecast</em> — the same measure, a slight forecast-vs-settlement seam, so read ‘now’ as indicative.</p>
      ${srcLine(r.source, 'reliability')}
    </div>`;
  drawReliabilityKey();
  drawReliabilityStripe();
  $('reliability-body').querySelectorAll('.rel-toggle button').forEach((b) =>
    b.addEventListener('click', () => switchReliabilityRange(b.dataset.range)));
}

async function switchReliabilityRange(range) {
  if (range === 'all' && !REL_ALL) {
    if (!REL_ALL_PROMISE) REL_ALL_PROMISE = getJSON('data/reliability_all.json');
    try { REL_ALL = await REL_ALL_PROMISE; }
    catch (e) { REL_ALL_PROMISE = null; return; } // keep current view if the big file is unavailable
  }
  REL_MODE = range;
  RELIABILITY = range === 'all' ? REL_ALL : REL_ROLLING;
  renderReliabilityStripe();
  updateReliabilityNow(LAST_STATE);             // re-place the caret (live value unchanged)
}

// Place the "now" caret on the key at the live reading's position. The stripe is always the
// share-of-demand (Using) basis, so we read firmPct on that basis regardless of the gauge toggle.
// unreliable = 100 − firm; the key runs 0%→100% unreliable left→right, so left% IS that value.
function updateReliabilityNow(state) {
  const el = $('reliability-now');
  if (!el) return;
  const v = state && state.verdict;
  const m = v ? sourceArcModel(v) : null;
  if (!m) { el.hidden = true; return; }
  const unreliable = unreliableNowPct(m.firmPct);
  if (unreliable == null) { el.hidden = true; return; }
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
    REL_ROLLING = await getJSON('data/reliability_year.json');
    RELIABILITY = REL_ROLLING;
    renderReliabilityStripe();
  } catch (e) {
    $('reliability-body').innerHTML = '';
  }
  // capacity carpets (Entry 02 right panels) — independent fetch so a missing file degrades
  // only the carpets, never the gauge or the other history entries.
  try { CAPACITY = await getJSON('data/capacity_carpets.json'); }
  catch (e) { CAPACITY = null; }
  await refreshLive();
  setInterval(refreshLive, POLL_MS);
  refreshWarnings();
  setInterval(refreshWarnings, POLL_MS);
  let t;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => {
    drawStripe(); drawReliabilityStripe(); drawReliabilityKey();
    if (CAPACITY && CAPACITY.sat) syncCarpetHeight();
    if (CAPACITY && CAPACITY.wind && CAPACITY.sat) drawCarpet('carpet-wind', CAPACITY.wind.days, CAPACITY.sat.wind, DIAL_PALETTE.wind.fullRgb);
    if (CAPACITY && CAPACITY.solar && CAPACITY.sat) drawCarpet('carpet-solar', CAPACITY.solar.days, CAPACITY.sat.solar, DIAL_PALETTE.solar.fullRgb);
  }, 150); });
}

main();
