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

// buildDom / wireControls / drawMiniGauge / drawPriceLine: see Task 11.
if (typeof document !== 'undefined') boot();
