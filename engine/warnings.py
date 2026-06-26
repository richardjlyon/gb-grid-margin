"""Python mirror of site/warnings.js for the build-time warning card. Same
scarcity ladder (EMN/CMN/NISM), same severity order, same window parse.
The browser light (warnings.js) stays the live, primary signal; this exists so
the share card can render the current state at build time."""
from __future__ import annotations

import re
import urllib.request

_LADDER = [
    ("NISM", "Notice of Insufficient System Margin", "INSUFFICIENT SYSTEM MARGIN", 3),
    ("EMN", "Electricity Margin Notice", "ELECTRICITY MARGIN NOTICE", 2),
    ("CMN", "Capacity Market Notice", "CAPACITY MARKET NOTICE", 1),
]
_WINDOW = re.compile(
    r"from\s+(\d{1,2}:\d{2})\s*hrs\s+to\s+(\d{1,2}:\d{2})\s*hrs\s+on\s+\w+\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE)
WARNINGS_URL = "https://data.elexon.co.uk/bmrs/api/v1/system/warnings"


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


def parse_active_warnings(rows):
    scarcity = [(r, _kind(r.get("warningType"))) for r in (rows or [])]
    scarcity = [(r, k) for r, k in scarcity if k]
    if not scarcity:
        return {"in_force": False}
    scarcity.sort(key=lambda rk: (rk[1][3], str(rk[0].get("publishTime", ""))), reverse=True)
    row, kind = scarcity[0]
    return {"in_force": True, "type": kind[0], "type_label": kind[1],
            "issued_at": row.get("publishTime"), "window": parse_window(row.get("warningText"))}


def fetch_active_warnings():
    """Active-only feed (CORS-open, same family as FUELINST). Returns [] on any error."""
    try:
        req = urllib.request.Request(WARNINGS_URL, headers={"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            body = json.loads(resp.read())
        data = body.get("data")
        return data if isinstance(data, list) else []
    except Exception:
        return []
