"""Python mirror of site/warnings.js for the build-time warning card. Same
scarcity ladder (EMN/CMN), same precedence order, same window parse, same
per-type fetch and fail-safe in-force logic. The browser light (warnings.js)
stays the live, primary signal; this exists so the share card can render the
current state at build time."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Two rungs only. NESO does NOT rank EMN against CMN (different signals to different parts of the
# market); the EMN-leads order is an EDITORIAL precedence — the EMN is the operator's judgement-based
# margin call. NISM (the EMN's pre-2016 predecessor) was retired and never appears in the feed.
_LADDER = [
    ("EMN", "Electricity Margin Notice", "ELECTRICITY MARGIN NOTICE", 2),
    ("CMN", "Capacity Market Notice", "CAPACITY MARKET NOTICE", 1),
]
_WINDOW = re.compile(
    r"from\s+(\d{1,2}:\d{2})\s*hrs\s+to\s+(\d{1,2}:\d{2})\s*hrs\s+on\s+\w+\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE)
WARNINGS_URL = "https://data.elexon.co.uk/bmrs/api/v1/system/warnings"
_LONDON = ZoneInfo("Europe/London")


def classify_warning(warning_type: str | None):
    t = (warning_type or "").upper()
    for code, label, match, rank in _LADDER:
        if match in t:
            return code
    return None


def _kind(warning_type: str | None):
    t = (warning_type or "").upper()
    for entry in _LADDER:
        if entry[2] in t:
            return entry
    return None


def parse_window(text: str | None):
    m = _WINDOW.search(text or "")
    return {"from": m.group(1), "to": m.group(2), "date": m.group(3)} if m else None


def _london_now_num(now: datetime) -> int:
    lt = now.astimezone(_LONDON)
    return int(f"{lt.year:04d}{lt.month:02d}{lt.day:02d}{lt.hour:02d}{lt.minute:02d}")


def _emn_end_num(text: str | None):
    win = parse_window(text)
    if not win:
        return None
    dd, mm, yyyy = win["date"].split("/")
    hh, mi = win["to"].split(":")
    return int(f"{yyyy}{mm}{dd}{int(hh):02d}{mi}")


def _emn_in_force(text: str | None, now: datetime) -> bool:
    """In force = a covered window whose end is still ahead. Cancellation, or an unparseable
    window, fails safe to NOT in force (under-claim when ambiguous)."""
    t = (text or "").upper()
    if "NOTIFICATION CANCELLATION" in t or "HAS BEEN CANCELLED" in t:
        return False
    end = _emn_end_num(text)
    if end is None:
        return False
    return _london_now_num(now) < end


def _cmn_in_force(text: str | None) -> bool:
    """In force = text begins 'Electricity Capacity Market Notice Currently Active'; a 'Cancelled'
    record (or anything without the active marker) is NOT in force."""
    t = (text or "").upper()
    if "CAPACITY MARKET NOTICE CANCELLED" in t:
        return False
    return "CAPACITY MARKET NOTICE CURRENTLY ACTIVE" in t


def parse_active_warnings(rows, now: datetime | None = None):
    """Given warning rows (the per-type latest records, pooled), return whether a scarcity notice
    is IN FORCE and, if so, the most severe one (CMN over EMN; ties by most recent publishTime)."""
    if now is None:
        now = datetime.now(timezone.utc)
    live = []
    for entry in _LADDER:
        for r in (rows or []):
            if entry[2] not in (r.get("warningType") or "").upper():
                continue
            in_force = (_emn_in_force(r.get("warningText"), now) if entry[0] == "EMN"
                        else _cmn_in_force(r.get("warningText")))
            if in_force:
                live.append((entry, r))
    if not live:
        return {"in_force": False}
    live.sort(key=lambda er: (er[0][3], str(er[1].get("publishTime", ""))), reverse=True)
    entry, row = live[0]
    return {"in_force": True, "type": entry[0], "type_label": entry[1],
            "issued_at": row.get("publishTime"), "window": parse_window(row.get("warningText"))}


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json
        return json.loads(resp.read())


def fetch_active_warnings():
    """Latest message of EACH scarcity type, pooled (CORS-open, same family as FUELINST). Queries
    per warningType because the no-params endpoint returns only the single latest message of ANY
    type, so an in-force EMN/CMN is missed whenever a newer non-scarcity notice lands after it.
    Returns [] on any error.

    Swallowing errors to [] is a deliberate safe default: a build-time SYSWARN outage yields an
    "All clear" card, which is a false negative (silent, not alarming) — the safer direction than a
    stale false alarm.  The 15 s timeout is intentionally more generous than warnings.js's 6 s
    (build tolerance vs browser responsiveness)."""
    rows = []
    try:
        for code, _label, match, _rank in _LADDER:
            url = f"{WARNINGS_URL}?warningType={urllib.parse.quote(match)}"
            body = _get_json(url)
            data = body.get("data")
            if isinstance(data, list):
                rows.extend(data)
        return rows
    except Exception:
        return []
