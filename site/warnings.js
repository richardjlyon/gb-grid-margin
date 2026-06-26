// site/warnings.js — the live warning light.
//
// Reads Elexon's /system/warnings feed (active-only, CORS-open) and decides whether a
// SCARCITY-class operational notice is currently in force: EMN, CMN, or NISM. Everything else
// the feed carries (SO-SO TRADES, IT SYSTEMS OUTAGE, OTHER, NRAPM, DFS) is noise and is ignored.
// parseActiveWarnings is pure and the only thing with logic worth testing; resolveWarnings is a
// thin fetch wrapper around it. The lamp fails to UNKNOWN, never to a stale all-clear or alarm.

// Severity rank for picking the headline when several scarcity notices are active at once.
const LADDER = [
  { code: 'NISM', label: 'Notice of Insufficient System Margin', match: 'INSUFFICIENT SYSTEM MARGIN', rank: 3 },
  { code: 'EMN', label: 'Electricity Margin Notice', match: 'ELECTRICITY MARGIN NOTICE', rank: 2 },
  { code: 'CMN', label: 'Capacity Market Notice', match: 'CAPACITY MARKET NOTICE', rank: 1 },
];

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

// Fetch the active-warnings feed and map it to a render state. Fails to 'unavailable' (never a
// stale all-clear or alarm): on a network error OR a body whose `data` is not an array.
export async function resolveWarnings({ httpGet = httpGetReal, url = WARNINGS_URL } = {}) {
  let body;
  try {
    body = await httpGet(url, { timeoutMs: TIMEOUT_MS });
  } catch {
    return { status: 'unavailable' };
  }
  if (!Array.isArray(body?.data)) return { status: 'unavailable' };
  const active = parseActiveWarnings(body.data);
  return active.inForce ? { status: 'in_force', ...active } : { status: 'clear' };
}

// Given the active-warning rows from /system/warnings, return whether a scarcity notice is in
// force and, if so, the most severe one (tie-broken by most recent issue time).
export function parseActiveWarnings(rows) {
  if (!Array.isArray(rows)) return { inForce: false };
  const scarcity = rows
    .map((r) => ({ row: r, kind: classify(r?.warningType) }))
    .filter((x) => x.kind);
  if (scarcity.length === 0) return { inForce: false };
  scarcity.sort((a, b) => (b.kind.rank - a.kind.rank)
    || String(b.row.publishTime).localeCompare(String(a.row.publishTime)));
  const { row, kind } = scarcity[0];
  return {
    inForce: true,
    type: kind.code,
    typeLabel: kind.label,
    issuedAt: row.publishTime,
    window: parseWindow(row.warningText),
  };
}
