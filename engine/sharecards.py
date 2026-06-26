"""Grid Gauge share cards (Stage 8): sourced 1200x630 OG PNGs + unfurl stubs,
built from the same site JSON the dashboard reads so a card can never disagree
with the site. Visual system: Ink (default) / Instrument (gauge & stripe) /
Alarm (active warning only)."""
from __future__ import annotations

import hashlib
import html as _html
import json
import math
import re
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
SITE_URL = "https://gridgauge.co.uk"
CARD_W, CARD_H = 1200, 630
