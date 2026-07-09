// site/warnings.js — the live warning light.
//
// Reads Elexon's /system/warnings feed (CORS-open) and decides whether a SCARCITY-class
// operational notice is currently IN FORCE: a Capacity Market Notice (CMN, the more severe) or an
// Electricity Margin Notice (EMN). Everything else the feed carries (SO-SO TRADES, IT SYSTEMS
// OUTAGE, OTHER, NRAPM, DFS) is noise and is ignored.
//
// The feed's no-params endpoint returns only the single LATEST message of ANY type, so an in-force
// EMN/CMN is missed whenever a newer non-scarcity notice lands after it. We therefore query PER
// TYPE (?warningType=<TYPE>), which returns the latest message of that type, and decide in-force
// from the record's own text. parseActiveWarnings is pure and the only thing with logic worth
// testing; resolveWarnings is the fetch wrapper around it. The lamp fails to 'unavailable', never
// to a stale all-clear or alarm. In-force parsing FAILS SAFE: when ambiguous, treat as NOT in force.

// Precedence for picking the headline when both scarcity notices are in force at once. NESO does
// NOT rank EMN against CMN (they signal different things to different parts of the market); this is
// an EDITORIAL precedence — the EMN, the operator's judgement-based margin call, leads. Two rungs
// only — NISM (the EMN's pre-2016 predecessor) was retired and never appears in the feed.
const LADDER = [
  { code: 'EMN', label: 'Electricity Margin Notice', match: 'ELECTRICITY MARGIN NOTICE', rank: 2 },
  { code: 'CMN', label: 'Capacity Market Notice', match: 'CAPACITY MARKET NOTICE', rank: 1 },
];

// URL-encoded warningType query value for each rung's per-type fetch.
const TYPE_QUERY = {
  CMN: 'CAPACITY%20MARKET%20NOTICE',
  EMN: 'ELECTRICITY%20MARGIN%20NOTICE',
};

function classify(warningType) {
  const t = String(warningType || '').toUpperCase();
  return LADDER.find((l) => t.includes(l.match)) || null;
}

// The covered window line: "from 19:00 hrs to 22:00 hrs on Friday   26/06/2026".
function parseWindow(warningText) {
  const m = /from\s+(\d{1,2}:\d{2})\s*hrs\s+to\s+(\d{1,2}:\d{2})\s*hrs\s+on\s+\w+\s+(\d{2}\/\d{2}\/\d{4})/i
    .exec(String(warningText || ''));
  return m ? { from: m[1], to: m[2], date: m[3] } : null;
}

// "now", and an EMN window end, reduced to the same comparable London-wall-clock integer
// (YYYYMMDDHHMM) so BST/GMT never has to be reasoned about — both sides are wall time.
function londonNowNum(now) {
  const p = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(now).reduce((o, x) => (o[x.type] = x.value, o), {});
  const hour = p.hour === '24' ? '00' : p.hour;
  return Number(`${p.year}${p.month}${p.day}${hour}${p.minute}`);
}

function emnEndNum(warningText) {
  const win = parseWindow(warningText);
  if (!win) return null;
  const [dd, mm, yyyy] = win.date.split('/');
  const [hh, mi] = win.to.split(':');
  return Number(`${yyyy}${mm}${dd}${hh.padStart(2, '0')}${mi}`);
}

// EMN in force = a covered window whose end is still ahead. Cancellation, or an unparseable window,
// fails safe to NOT in force (under-claim when ambiguous).
function emnInForce(warningText, now) {
  const t = String(warningText || '').toUpperCase();
  if (t.includes('NOTIFICATION CANCELLATION') || t.includes('HAS BEEN CANCELLED')) return false;
  const end = emnEndNum(warningText);
  if (end == null) return false;
  return londonNowNum(now) < end;
}

// CMN in force = text begins "Electricity Capacity Market Notice Currently Active"; a "Cancelled"
// record (or anything without the active marker) is NOT in force.
function cmnInForce(warningText) {
  const t = String(warningText || '').toUpperCase();
  if (t.includes('CAPACITY MARKET NOTICE CANCELLED')) return false;
  return t.includes('CAPACITY MARKET NOTICE CURRENTLY ACTIVE');
}

const ELEXON = 'https://data.elexon.co.uk/bmrs/api/v1';
const WARNINGS_URL = `${ELEXON}/system/warnings`;
const TIMEOUT_MS = 6000;

// Real network fetch of JSON with an AbortController timeout. Throws on !ok or timeout.
async function httpGetReal(url, { timeoutMs = TIMEOUT_MS } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// Fetch the latest message of EACH scarcity type and map to a render state. Fails to 'unavailable'
// (never a stale all-clear or alarm): on any network error OR a body whose `data` is not an array.
export async function resolveWarnings({ httpGet = httpGetReal, url = WARNINGS_URL, now = new Date() } = {}) {
  const rows = [];
  for (const entry of LADDER) {
    let body;
    try {
      body = await httpGet(`${url}?warningType=${TYPE_QUERY[entry.code]}`, { timeoutMs: TIMEOUT_MS });
    } catch {
      return { status: 'unavailable' };
    }
    if (!Array.isArray(body?.data)) return { status: 'unavailable' };
    rows.push(...body.data);
  }
  const active = parseActiveWarnings(rows, now);
  return active.inForce ? { status: 'in_force', ...active } : { status: 'clear' };
}

// Given warning rows (the per-type latest records, pooled), return whether a scarcity notice is IN
// FORCE and, if so, the most severe one (CMN over EMN; ties by most recent publishTime). Noise rows
// and expired/cancelled notices never light the lamp.
export function parseActiveWarnings(rows, now = new Date()) {
  if (!Array.isArray(rows)) return { inForce: false };
  const live = [];
  for (const entry of LADDER) {
    for (const row of rows) {
      if (!String(row?.warningType || '').toUpperCase().includes(entry.match)) continue;
      const inForce = entry.code === 'EMN'
        ? emnInForce(row.warningText, now)
        : cmnInForce(row.warningText);
      if (inForce) live.push({ entry, row });
    }
  }
  if (live.length === 0) return { inForce: false };
  live.sort((a, b) => (b.entry.rank - a.entry.rank)
    || String(b.row.publishTime).localeCompare(String(a.row.publishTime)));
  const { entry, row } = live[0];
  return {
    inForce: true,
    type: entry.code,
    typeLabel: entry.label,
    issuedAt: row.publishTime,
    window: parseWindow(row.warningText),
  };
}
