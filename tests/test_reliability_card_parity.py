"""Colour parity: engine.sharecards.reliable_share_to_color must match site/render.js."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from engine.sharecards import reliable_share_to_color

REPO = Path(__file__).resolve().parents[1]
SAMPLES = [0.0, 0.30, 0.40, 0.45, 0.475, 0.50, 0.525, 0.65, 0.70, 1.0, 1.30]


def _js_colors(samples):
    script = (
        "import {reliableShareToColor} from './site/render.js';"
        f"const s={json.dumps(samples)};"
        "console.log(JSON.stringify(s.map(reliableShareToColor)));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         cwd=REPO, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_python_ramp_matches_js_ramp():
    js = _js_colors(SAMPLES)
    py = [list(reliable_share_to_color(s)) for s in SAMPLES]
    assert py == js, f"ramp drift\nJS {js}\nPY {py}"


def test_null_is_gap_grey():
    assert reliable_share_to_color(None) == (232, 232, 230)
