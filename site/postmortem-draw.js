import { reliableShareToColor, rgbCss, fmtPct, COL_WIND, COL_SOLAR, COL_IMPORTS } from './render.js';

export function activeCommentIndex(commentary, sp) {
  let idx = -1;
  for (let i = 0; i < commentary.length; i++) if (commentary[i].period <= sp) idx = i;
  return idx;
}

export function revealedPoints(frames, i) {
  const upto = frames.slice(0, i + 1).filter((f) => f.price_gbp_mwh != null);
  if (!upto.length) return [];
  const all = frames.filter((f) => f.price_gbp_mwh != null);
  const max = Math.max(...all.map((f) => f.price_gbp_mwh)) || 1;
  const n = frames.length;
  const out = [];
  frames.forEach((f, k) => {
    if (k > i || f.price_gbp_mwh == null) return;
    out.push({ x: n > 1 ? k / (n - 1) : 0, y: f.price_gbp_mwh / max });
  });
  return out;
}

const _londonParts = (t) =>
  new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit',
    day: '2-digit', month: 'short', weekday: 'short', hour12: false,
  }).formatToParts(new Date(t)).reduce((a, p) => ((a[p.type] = p.value), a), {});

export function formatClock(t) {
  const p = _londonParts(t);
  return `${p.hour}:${p.minute}`;
}

export function formatCalendar(t) {
  const p = _londonParts(t);
  return { day: p.day, month: p.month.toUpperCase(), weekday: p.weekday.toUpperCase() };
}

export function frameParts(frame) {
  const relColor = rgbCss(reliableShareToColor(frame.firm_pct / 100));
  return [
    { key: 'reliability', label: 'Reliable', value: frame.firm_pct, max: 100,
      valueText: fmtPct(frame.firm_pct), color: relColor },
    { key: 'wind', label: 'Wind', value: frame.wind_cf_pct ?? 0, max: 100,
      valueText: fmtPct(frame.wind_cf_pct), color: COL_WIND },
    { key: 'solar', label: 'Solar', value: frame.solar_cf_pct ?? 0, max: 100,
      valueText: fmtPct(frame.solar_cf_pct), color: COL_SOLAR },
    { key: 'imports', label: 'Imports', value: frame.import_cf_pct ?? 0, max: 100,
      valueText: fmtPct(frame.import_cf_pct), color: COL_IMPORTS },
  ];
}
