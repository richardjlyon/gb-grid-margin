import { activeCommentIndex, revealedPoints, formatClock, formatCalendar, frameParts } from './postmortem-draw.js';

export class Transport {
  constructor(n, onChange) { this.n = n; this.index = 0; this.playing = false; this.onChange = onChange; }
  _set(i) { const c = Math.max(0, Math.min(this.n - 1, i)); if (c !== this.index) { this.index = c; this.onChange(c); } }
  step(d) { this._set(this.index + d); }
  seek(i) { this._set(i); }
  toStart() { this._set(0); }
  toEnd() { this._set(this.n - 1); }
  toggle() { this.playing = !this.playing; return this.playing; }
}

// ---- DOM bootstrap (skipped under node; runs in the browser) ----
async function boot() {
  const root = document.getElementById('pm-player');
  if (!root) return;
  const slug = document.querySelector('.postmortem').dataset.slug;
  const data = await fetch(`../data/scenario_${slug}.json`).then((r) => r.json());
  const frames = data.frames;
  buildDom(root, data);
  const gaugeCanvas = root.querySelectorAll('canvas.pm-gauge');
  const priceCanvas = root.querySelector('canvas.pm-price');
  const box = root.querySelector('.pm-commentary');
  const clockEl = root.querySelector('.pm-clock');
  const calEl = root.querySelector('.pm-cal');
  const readout = root.querySelector('.pm-readout');

  const render = (i) => {
    const f = frames[i];
    frameParts(f).forEach((p, k) => drawMiniGauge(gaugeCanvas[k], p));
    drawPriceLine(priceCanvas, revealedPoints(frames, i), f.price_gbp_mwh);
    const ci = activeCommentIndex(data.commentary, f.sp);
    box.textContent = ci >= 0 ? data.commentary[ci].text : '';
    clockEl.textContent = formatClock(f.t);
    const c = formatCalendar(f.t);
    calEl.innerHTML = `<span class="cal-wd">${c.weekday}</span><span class="cal-day">${c.day}</span><span class="cal-mo">${c.month}</span>`;
    readout.textContent = `Reliable ${f.firm_pct}% · wind ${f.wind_cf_pct ?? '—'}% · solar ${f.solar_cf_pct ?? '—'}% · imports ${f.import_cf_pct ?? '—'}% · £${f.price_gbp_mwh ?? '—'}/MWh`;
    scrub.value = String(i);
  };

  const transport = new Transport(frames.length, render);
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let timer = null;
  const stop = () => { clearInterval(timer); timer = null; transport.playing = false; playBtn.textContent = '▶'; };
  const play = () => {
    if (reduced) return;                     // step-only when reduced-motion
    transport.playing = true; playBtn.textContent = '⏸';
    timer = setInterval(() => {
      if (transport.index >= frames.length - 1) { stop(); return; }
      transport.step(1);
    }, 400);
  };
  const { playBtn, scrub } = wireControls(root, {
    toStart: () => { stop(); transport.toStart(); },
    back: () => { stop(); transport.step(-1); },
    toggle: () => (timer ? stop() : play()),
    fwd: () => { stop(); transport.step(1); },
    toEnd: () => { stop(); transport.toEnd(); },
    seek: (i) => { stop(); transport.seek(i); },
    markers: data.markers,
    jump: (i) => { stop(); transport.seek(i); },
  });
  render(0);
}

function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }

function buildDom(root, data) {
  root.removeAttribute('data-loading');
  root.innerHTML = '';
  // time display
  const time = el('div', 'pm-time');
  time.append(el('div', 'pm-cal'), el('div', 'pm-clock'));
  // four gauges
  const gauges = el('div', 'pm-gauges');
  ['Reliable', 'Wind', 'Solar', 'Imports'].forEach((label) => {
    const cell = el('div', 'pm-gauge-cell');
    const c = el('canvas', 'pm-gauge'); c.width = 180; c.height = 120;
    cell.append(c, el('div', 'pm-gauge-label', label));
    gauges.append(cell);
  });
  // price line
  const price = el('div', 'pm-price-wrap');
  const pc = el('canvas', 'pm-price'); pc.width = 720; pc.height = 160;
  price.append(el('div', 'pm-price-title', 'System price (£/MWh)'), pc);
  // commentary + readout
  const box = el('div', 'pm-commentary'); box.setAttribute('aria-live', 'polite');
  const readout = el('p', 'pm-readout visually-hidden'); readout.setAttribute('aria-live', 'polite');
  // transport
  const bar = el('div', 'pm-transport');
  bar.innerHTML = `
    <button class="pm-btn" data-act="toStart" aria-label="Rewind to start">⏮</button>
    <button class="pm-btn" data-act="back" aria-label="Step back">⏪</button>
    <button class="pm-btn pm-play" data-act="toggle" aria-label="Play or pause">▶</button>
    <button class="pm-btn" data-act="fwd" aria-label="Step forward">⏩</button>
    <button class="pm-btn" data-act="toEnd" aria-label="Jump to end">⏭</button>
    <input class="pm-scrub" type="range" min="0" max="${data.frames.length - 1}" value="0" step="1" aria-label="Scrub through the event">`;
  const markers = el('div', 'pm-markers');
  data.markers.forEach((m) => {
    const b = el('button', 'pm-marker', m.label); b.dataset.i = String(m.index); markers.append(b);
  });
  root.append(time, gauges, price, box, markers, bar, readout);
}

function wireControls(root, h) {
  root.querySelectorAll('.pm-btn').forEach((b) => b.addEventListener('click', () => h[b.dataset.act]()));
  const scrub = root.querySelector('.pm-scrub');
  scrub.addEventListener('input', () => h.seek(Number(scrub.value)));
  root.querySelectorAll('.pm-marker').forEach((b) => b.addEventListener('click', () => h.jump(Number(b.dataset.i))));
  const playBtn = root.querySelector('.pm-play');
  return { playBtn, scrub };
}

function drawMiniGauge(canvas, part) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, cx = w / 2, cy = h - 12, r = Math.min(cx, cy) - 10;
  ctx.clearRect(0, 0, w, h);
  // track (180° half-dial, left=0, right=max)
  ctx.lineWidth = 12; ctx.lineCap = 'round';
  ctx.strokeStyle = '#e6e3dc';
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI); ctx.stroke();
  // value arc
  const frac = Math.max(0, Math.min(1, part.value / part.max));
  ctx.strokeStyle = part.color;
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + Math.PI * frac); ctx.stroke();
  // value text
  ctx.fillStyle = '#15181C'; ctx.textAlign = 'center'; ctx.font = '600 20px "Space Grotesk", sans-serif';
  ctx.fillText(part.valueText, cx, cy - 6);
}

function drawPriceLine(canvas, points, currentPrice) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, pad = 24;
  ctx.clearRect(0, 0, w, h);
  // axis
  ctx.strokeStyle = '#d8d4cc'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, h - pad); ctx.lineTo(w - pad, h - pad); ctx.stroke();
  if (!points.length) return;
  const X = (x) => pad + x * (w - 2 * pad);
  const Y = (y) => (h - pad) - y * (h - 2 * pad);
  // revealed line
  ctx.strokeStyle = '#D6121F'; ctx.lineWidth = 2.5; ctx.lineJoin = 'round';
  ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(X(p.x), Y(p.y)) : ctx.moveTo(X(p.x), Y(p.y))));
  ctx.stroke();
  // leading dot + current value
  const last = points[points.length - 1];
  ctx.fillStyle = '#D6121F';
  ctx.beginPath(); ctx.arc(X(last.x), Y(last.y), 4, 0, 2 * Math.PI); ctx.fill();
  if (currentPrice != null) {
    ctx.fillStyle = '#15181C'; ctx.textAlign = 'right'; ctx.font = '600 16px "Space Grotesk", sans-serif';
    ctx.fillText(`£${Math.round(currentPrice)}`, X(last.x) - 8, Y(last.y) - 8);
  }
}

if (typeof document !== 'undefined') boot();
