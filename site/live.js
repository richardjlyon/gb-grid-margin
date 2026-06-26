// site/live.js — the browser orchestrator for the live layer.
//
// Fetches the three CORS-open feeds (FUELINST + NESO embedded required, demand outturn optional),
// recomputes the verdict via verdict.js (NEVER its own math), and falls back to the
// build-written latest.json when the live path can't be trusted. It never blends live and
// fallback on one screen, and never shows a number it cannot stand behind. The decision
// logic takes an injectable httpGet so it can be unit-tested without a network or DOM.
import {
  computeVerdict, latestSnapshot, validateSnapshot, embeddedInWindow, capacityTrap, roundHalfEven1,
} from './verdict.js';

const ELEXON = 'https://data.elexon.co.uk/bmrs/api/v1';
const NESO = 'https://api.neso.energy/api/3/action';
const NESO_RID = 'db6c038f-98af-4570-ab60-24d71ebd0ae5';
const LATEST_JSON = new URL('./data/latest.json', import.meta.url).href;
const BAD_URL = 'https://invalid.invalid/';

const SCHEMA_VERSION = 1;
const PER_FEED_TIMEOUT_MS = 6000;
const RECONCILE_TOL = 0.12;
const SKEW_TOL_MIN = 3;            // data this far in the future => device clock wrong
const LIVE_LAG_UNCERTAIN_MIN = 20; // a just-fetched live snapshot older than this => age uncertain
const STALE_MIN = 60;              // banner past this age (Richard: > 60 min)
const LIVE_TOO_OLD_MIN = 40;       // a "live" reading older than this (trusted clock) => failed fetch
const FALLBACK_NUMBERS_MAX_MIN = 120; // fallback snapshot older than this => show NO numbers (too old to be "now")
const UNAVAILABLE_AGE_MS = 12 * 60 * 60 * 1000; // fallback build older than 12 h => UNAVAILABLE
const FUELINST_WINDOW_MIN = 180;   // wide, future-buffered: capture the true latest despite clock skew
const POLL_MS = 5 * 60 * 1000;

const pad = (n) => String(n).padStart(2, '0');
const isoMinZ = (d) =>
  `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
  `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;

// Real network fetch of JSON with an AbortController timeout. Throws on !ok or timeout.
async function httpGetReal(url, { timeoutMs = PER_FEED_TIMEOUT_MS } = {}) {
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

function feedUrl(feed, faults, nowMs) {
  // 'fallback' breaks every live feed too, so the page actually reaches UNAVAILABLE.
  if (faults.break === feed || faults.break === 'all' || faults.break === 'fallback') return BAD_URL;
  if (feed === 'fuelinst') {
    const to = isoMinZ(new Date(nowMs + FUELINST_WINDOW_MIN * 60 * 1000));
    const from = isoMinZ(new Date(nowMs - FUELINST_WINDOW_MIN * 60 * 1000));
    return `${ELEXON}/datasets/FUELINST/stream?publishDateTimeFrom=${from}&publishDateTimeTo=${to}`;
  }
  if (feed === 'neso') return `${NESO}/datastore_search?resource_id=${NESO_RID}&limit=100`;
  if (feed === 'demand') {
    const day = isoMinZ(new Date(nowMs)).slice(0, 10);
    return `${ELEXON}/demand/outturn?settlementDateFrom=${day}&settlementDateTo=${day}`;
  }
  throw new Error(`unknown feed ${feed}`);
}

async function fetchFeed(feed, faults, nowMs, clockNow, httpGet) {
  const t0 = clockNow();
  if (faults.slow && faults.slow.feed === feed) {
    // Simulate a slow feed that the per-feed timeout must cut off (no hang).
    await new Promise((res, rej) => {
      const fail = setTimeout(() => rej(new Error('timeout (slow)')), PER_FEED_TIMEOUT_MS);
      setTimeout(() => { clearTimeout(fail); res(); }, faults.slow.ms);
    });
  }
  const body = await httpGet(feedUrl(feed, faults, nowMs), { timeoutMs: PER_FEED_TIMEOUT_MS });
  return { body, latencyMs: Math.round(clockNow() - t0) };
}

function pickEmbedded(records, anchorMs) {
  let best = null;
  let bestDiff = Infinity;
  for (const r of records) {
    const t = Date.parse(`${String(r.DATE_GMT).slice(0, 10)}T${r.TIME_GMT}Z`);
    const diff = Math.abs(t - anchorMs);
    if (diff < bestDiff) { bestDiff = diff; best = r; }
  }
  if (!best) throw new Error('NESO embedded returned no rows');
  return {
    time: `${String(best.DATE_GMT).slice(0, 10)}T${best.TIME_GMT}Z`,
    solar_mw: best.EMBEDDED_SOLAR_FORECAST,
    wind_mw: best.EMBEDDED_WIND_FORECAST,
    solar_capacity_mw: best.EMBEDDED_SOLAR_CAPACITY,
    wind_capacity_mw: best.EMBEDDED_WIND_CAPACITY,
  };
}

// Try the live path. Throws { reason, feeds } if it cannot produce a trustworthy verdict.
async function tryLive(faults, clockNow, httpGet) {
  const nowMs = clockNow();
  const [fuel, neso, demand] = await Promise.allSettled([
    fetchFeed('fuelinst', faults, nowMs, clockNow, httpGet),
    fetchFeed('neso', faults, nowMs, clockNow, httpGet),
    fetchFeed('demand', faults, nowMs, clockNow, httpGet),
  ]);
  const feeds = {
    fuelinst: fuel.status === 'fulfilled' ? { status: 'ok', latencyMs: fuel.value.latencyMs } : { status: 'failed' },
    neso: neso.status === 'fulfilled' ? { status: 'ok', latencyMs: neso.value.latencyMs } : { status: 'failed' },
    demand: demand.status === 'fulfilled' ? { status: 'ok', latencyMs: demand.value.latencyMs } : { status: 'failed' },
  };
  if (fuel.status !== 'fulfilled') throw { reason: 'FUELINST unavailable', feeds };
  if (neso.status !== 'fulfilled') throw { reason: 'NESO embedded unavailable', feeds };

  let { snapshot, mix } = latestSnapshot(fuel.value.body);
  if (faults.partial === 'fuelinst') { mix = { ...mix }; delete mix.CCGT; }

  // Embedded row nearest the SNAPSHOT time (server-stamped) — keeps numbers clock-independent.
  const embedded = pickEmbedded(neso.value.body.result.records, Date.parse(snapshot));
  if (faults.staleNeso) embedded.time = isoMinZ(new Date(Date.parse(snapshot) + 45 * 60 * 1000));
  if (faults.futureNeso) embedded.time = isoMinZ(new Date(nowMs + 90 * 60 * 1000));

  const verdict = computeVerdict(mix, embedded);
  verdict.snapshot = snapshot;

  if (!validateSnapshot(mix, verdict.national_demand_mw)) throw { reason: 'incomplete FUELINST snapshot', feeds };
  if (!embeddedInWindow(embedded.time, snapshot)) throw { reason: 'embedded estimate out of window', feeds };

  // INDO (national demand) reconcile tripwire — only a finite, positive reference can breach;
  // otherwise degrade. INDO, not ITSDO: ITSDO adds interconnector exports + station load + PS
  // pumping as demand, so it diverged from this national-demand reconstruction by the export
  // volume on an export night and false-alarmed. PARITY-LOCKED with grid_engine.sanity_check.
  let reconcileNote = '';
  const rows = demand.status === 'fulfilled' ? demand.value.body?.data : null;
  const lastWithIndo = Array.isArray(rows)
    ? [...rows].reverse().find((r) => Number.isFinite(r?.initialDemandOutturn)) : null;
  const indoMw = lastWithIndo ? lastWithIndo.initialDemandOutturn : null;
  const expected = Number.isFinite(indoMw) ? indoMw + embedded.solar_mw + embedded.wind_mw : null;
  if (expected != null && expected > 0) {
    if (Math.abs(verdict.national_demand_mw - expected) / expected > RECONCILE_TOL) {
      throw { reason: 'INDO reconciliation breached', feeds };
    }
  } else {
    reconcileNote = 'reconciliation check unavailable';
  }

  return { verdict, capacity: capacityTrap(verdict, embedded), snapshot, feeds, reconcileNote };
}

const fmtAge = (m) => (m < 90 ? `${Math.max(0, Math.round(m))} min ago` : `${(m / 60).toFixed(1)} h ago`);

// Age relative to a server-stamped time, using the device clock (there is no readable
// cross-origin server clock). The absolute UTC time is always shown; this relative age is a
// sanity-bounded convenience — implausible values degrade to "age uncertain".
function relAge(serverTimeMs, clientNowMs, uncertainAboveMin) {
  if (!Number.isFinite(serverTimeMs)) return { ageMin: null, text: 'age unknown — treat as stale', uncertain: true };
  const ageMin = (clientNowMs - serverTimeMs) / 60000;
  // TODO(stage3-audit L5): asymmetric tolerance (3 min future vs uncertainAbove past) tags a
  // fresh reading "uncertain" when the device clock is 3-20 min behind. Cosmetic. See NOTES §5.
  if (ageMin < -SKEW_TOL_MIN || ageMin > uncertainAboveMin) {
    return { ageMin, text: 'age uncertain — check device clock', uncertain: true };
  }
  return { ageMin, text: fmtAge(ageMin), uncertain: false };
}

async function fetchLatest(faults, httpGet) {
  if (faults.break === 'fallback') throw new Error('fallback broken (test)');
  return httpGet(LATEST_JSON, { timeoutMs: PER_FEED_TIMEOUT_MS });
}

// Orchestrate one render cycle. Pure given httpGet + clockNow — returns a structured state.
export async function resolveState(faults, clockNow, { httpGet = httpGetReal } = {}) {
  const clientNowMs = clockNow();
  // Best-effort: fetch latest.json once. It is both the freshness floor for the live path
  // (H1) and the source for the fallback render.
  let fallbackData = null;
  try { fallbackData = await fetchLatest(faults, httpGet); } catch { /* handled in buildFallback */ }

  try {
    const live = await tryLive(faults, clockNow, httpGet);
    const snapMs = Date.parse(live.snapshot);
    // H1 (clock-independent): a prior successful build proves a newer snapshot exists, so a
    // live snapshot older than it is stale — never paint it as current.
    const builtSnapMs = Date.parse(fallbackData?.provenance?.snapshot);
    if (Number.isFinite(builtSnapMs) && Number.isFinite(snapMs) && builtSnapMs > snapMs) {
      throw { reason: 'live snapshot older than last build', feeds: live.feeds };
    }
    const age = relAge(snapMs, clientNowMs, LIVE_LAG_UNCERTAIN_MIN);
    // Demote a too-old live reading only on a TRUSTED clock (H1 already caught the skew case).
    if (!age.uncertain && Number.isFinite(snapMs) && (clientNowMs - snapMs) / 60000 > LIVE_TOO_OLD_MIN) {
      throw { reason: 'live reading too old', feeds: live.feeds };
    }
    const snapHH = live.snapshot.slice(11, 16);
    const lead = !age.uncertain && age.ageMin > 15 ? 'Live (delayed)' : 'Live';
    return {
      mode: 'live',
      verdict: live.verdict,
      capacity: live.capacity,
      feeds: live.feeds,
      lastUpdated: `${lead} — snapshot ${snapHH} UTC (${age.text})`,
      reconcileNote: live.reconcileNote,
      veryStale: !age.uncertain && age.ageMin != null && age.ageMin > STALE_MIN,
    };
  } catch (liveErr) {
    return buildFallback(fallbackData, clientNowMs, liveErr);
  }
}

// Pure: turn already-fetched latest.json into a fallback or UNAVAILABLE state. Validates every
// number it is about to display so a partial/corrupt file reaches UNAVAILABLE, never NaN%.
export function buildFallback(data, clientNowMs, liveErr) {
  const unavailable = (msg) => ({
    mode: 'unavailable', verdict: null, capacity: null, feeds: liveErr?.feeds || {},
    lastUpdated: 'Live and fallback both unavailable — no current reading.',
    reason: `${liveErr?.reason || liveErr?.message || 'live failed'}; ${msg}`,
  });
  if (!data) return unavailable('fallback unavailable');
  if (data.schema_version !== SCHEMA_VERSION) return unavailable('unknown schema_version');
  const p = data.provenance || {};
  const v = data.verdict || {};
  const builtMs = Date.parse(p.build_time_utc);
  if (!Number.isFinite(builtMs)) return unavailable('fallback build time invalid');
  // TODO(stage3-audit L6): a device clock 12 h+ fast makes a fresh fallback read as too old →
  // UNAVAILABLE. Extreme and conservative (no wrong number shown). See engine/NOTES.md §5.
  if (clientNowMs - builtMs > UNAVAILABLE_AGE_MS) return unavailable('fallback too old');
  const pcts = ['renewables_pct', 'wind_pct', 'solar_pct', 'gas_plus_imports_pct', 'gas_pct', 'import_pct'];
  const numbersOk = pcts.every((k) => Number.isFinite(v[k]))
    && Number.isFinite(v.wind_mw) && Number.isFinite(v.solar_mw)
    && p.wind_capacity_mw > 0 && p.solar_capacity_mw > 0;
  if (!numbersOk) return unavailable('fallback payload incomplete');

  // A fallback snapshot too old to plausibly be "now" must not show its frozen numbers — a
  // midday 12 GW-solar reading rendered at 11pm is a wrong headline, not a stale one. Past this
  // window we go number-free (still below the 12 h build-age UNAVAILABLE cutoff above), measured
  // on the SNAPSHOT (the grid reading's own time), not the build time.
  const snapMs = Date.parse(p.snapshot);
  const snapAgeMin = Number.isFinite(snapMs) ? (clientNowMs - snapMs) / 60000 : Infinity;
  if (snapAgeMin > FALLBACK_NUMBERS_MAX_MIN) {
    return {
      mode: 'unavailable', verdict: null, capacity: null, feeds: liveErr?.feeds || {},
      lastUpdated: `Last good reading was ${fmtAge(snapAgeMin)} — too old to show as current.`,
      reason: `${liveErr?.reason || liveErr?.message || 'live failed'}; fallback snapshot too old to represent now`,
    };
  }

  const age = relAge(builtMs, clientNowMs, Infinity); // an old fallback is expected; only a future build is uncertain
  const snapHH = String(p.snapshot).slice(11, 16);
  const builtHH = new Date(builtMs).toISOString().slice(11, 16);
  // M5: only claim the live feed is unavailable when a required feed actually failed.
  const feedFailed = liveErr?.feeds?.fuelinst?.status === 'failed' || liveErr?.feeds?.neso?.status === 'failed';
  const cause = feedFailed ? 'Live feed unavailable.' : 'Live reading not yet confirmed.';
  return {
    mode: 'fallback',
    verdict: v,
    capacity: {
      wind_capacity_share_pct: roundHalfEven1((v.wind_mw / p.wind_capacity_mw) * 100),
      solar_capacity_share_pct: roundHalfEven1((v.solar_mw / p.solar_capacity_mw) * 100),
      denominator_basis: 'NESO GB-DC live',
    },
    feeds: liveErr?.feeds || {},
    lastUpdated: `Showing last good reading — snapshot ${snapHH} UTC, built ${builtHH} UTC (${age.text}). ${cause}`,
    reconcileNote: '',
    veryStale: age.uncertain || (age.ageMin != null && age.ageMin > STALE_MIN), // L3: uncertain age is also "may be stale"
  };
}

// --- DOM rendering ---
function parseFaults(search) {
  const q = new URLSearchParams(search);
  const slowMs = q.get('slow');
  // A literal '+' in a query string decodes to a space, so "?clock=+30m" arrives as " 30m".
  const clock = (q.get('clock') || '').trim();
  let clockOffsetMs = 0;
  const m = /^([+-]?\d+)m$/.exec(clock);
  if (m) clockOffsetMs = Number(m[1]) * 60 * 1000;
  return {
    break: q.get('break'),
    slow: slowMs ? { feed: q.get('slowFeed') || 'fuelinst', ms: Number(slowMs) } : null,
    partial: q.get('partial'),
    staleNeso: q.get('stale') === 'neso',
    futureNeso: q.get('future') === 'neso',
    clockOffsetMs,
  };
}

const fmtPct = (x) => (Number.isFinite(x) ? `${x.toFixed(1)}%` : '—');

function render(root, state) {
  root.dataset.mode = state.mode;
  const v = state.verdict;
  const numbers = v ? `
    <div class="verdict">
      <div class="pair"><span class="big">${fmtPct(v.renewables_pct)}</span> renewables
        <span class="sub">(wind ${fmtPct(v.wind_pct)} · solar ${fmtPct(v.solar_pct)})</span></div>
      <div class="pair"><span class="big">${fmtPct(v.gas_plus_imports_pct)}</span> gas &amp; imports
        <span class="sub">(gas ${fmtPct(v.gas_pct)} · imports ${fmtPct(v.import_pct)})</span></div>
    </div>
    <div class="trap">Wind at ${fmtPct(state.capacity.wind_capacity_share_pct)} of capacity ·
      solar ${fmtPct(state.capacity.solar_capacity_share_pct)}
      <span class="src">(${state.capacity.denominator_basis})</span></div>` : '';
  root.innerHTML = `
    <div class="badge badge-${state.mode}">${state.mode.toUpperCase()}</div>
    ${state.veryStale ? '<div class="warn">Data may be out of date</div>' : ''}
    ${numbers}
    <div class="updated">${state.lastUpdated}</div>
    ${state.reconcileNote ? `<div class="note">${state.reconcileNote}</div>` : ''}
    ${state.reason ? `<div class="note">${state.reason}</div>` : ''}
    <div class="feeds">${Object.entries(state.feeds || {}).map(([k, f]) =>
      `<span class="feed feed-${f.status}">${k}: ${f.status}${f.latencyMs != null ? ` ${f.latencyMs}ms` : ''}</span>`).join(' ')}</div>`;
}

export async function mount(root, search = window.location.search) {
  const faults = parseFaults(search);
  const clockNow = () => Date.now() + faults.clockOffsetMs;
  const cycle = async () => {
    try {
      render(root, await resolveState(faults, clockNow));
    } catch (e) {
      // Error boundary: any unexpected throw still reaches a definite, number-free state.
      render(root, {
        mode: 'unavailable', verdict: null, capacity: null, feeds: {},
        lastUpdated: 'Unexpected error — no current reading.', reason: String(e?.message || e),
      });
    }
  };
  await cycle();
  setInterval(cycle, POLL_MS);
}
