"""Cross-language parity gate: the JS port (site/verdict.js) must never diverge from
the Python engine. One `uv run pytest` catches JS drift locally and in CI.

Three layers:
- GOLDEN: the committed fixture re-run through compute_verdict (strict key-set + values).
- FUZZ: 2000 seeded random mixes through BOTH engines, asserted equal — covers shapes
  no author enumerated (unseen INT* legs, lowercase codes, negatives, unknown fuels).
- CROSS-ENGINE: `node --test site/verdict.test.mjs` over the committed fixture.
"""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.grid_engine import compute_verdict, embedded_in_window, validate_snapshot

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "verdict_vectors.json"
RUNNER = REPO / "site" / "parity_runner.mjs"
JS_TESTS = [REPO / "site" / "verdict.test.mjs", REPO / "site" / "live.test.mjs",
            REPO / "site" / "render.test.mjs", REPO / "site" / "warnings.test.mjs"]

VECTORS = json.loads(FIXTURE.read_text())


# --- GOLDEN: pin Python to the committed fixture (strict key-set + values) ---

@pytest.mark.parametrize("case", VECTORS["verdict_cases"], ids=lambda c: c["name"])
def test_python_matches_golden_verdict(case):
    got = compute_verdict(case["mix"], case["embedded"])
    assert got.keys() == case["expected"].keys()  # no missing / extra fields
    assert got == case["expected"]


@pytest.mark.parametrize("case", VECTORS["snapshot_cases"], ids=lambda c: c["name"])
def test_python_matches_golden_snapshot(case):
    assert validate_snapshot(case["mix"], case["demand"]) is case["expected_valid"]


@pytest.mark.parametrize("case", VECTORS["embedded_cases"], ids=lambda c: c["name"])
def test_python_matches_golden_embedded(case):
    assert embedded_in_window(case["embedded_time"], case["snapshot_time"]) is case[
        "expected_valid"]


# --- FUZZ: 2000 seeded random mixes through both engines ---

_POOL = ["CCGT", "OCGT", "WIND", "NUCLEAR", "BIOMASS", "OTHER", "NPSHYD", "COAL", "OIL",
         "PS", "INTFR", "INTIRL", "INTNED", "INTNEM", "intfr", "INTXYZ", "WAVE",
         "GEOTHERMAL", "UNKNOWNX"]


def _random_batch(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    batch = []
    for _ in range(n):
        keys = rng.sample(_POOL, rng.randint(3, len(_POOL)))
        mix = {k: rng.randint(-2000, 12000) for k in keys}
        embedded = {
            "solar_mw": rng.randint(0, 15000),
            "wind_mw": rng.randint(0, 3000),
            "solar_capacity_mw": rng.randint(15000, 25000),
            "wind_capacity_mw": rng.randint(5000, 8000),
            "time": "2026-06-25T13:30Z",
        }
        batch.append({"mix": mix, "embedded": embedded})
    return batch


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_fuzz_parity_python_vs_js(tmp_path):
    batch = _random_batch(2000, seed=20260625)
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(batch))

    proc = subprocess.run(
        ["node", str(RUNNER), str(batch_file)],
        capture_output=True, text=True, check=True,
    )
    js_out = json.loads(proc.stdout)
    assert len(js_out) == len(batch)

    for i, (case, js) in enumerate(zip(batch, js_out)):
        py = compute_verdict(case["mix"], case["embedded"])
        assert py.keys() == js.keys(), f"case {i}: key-set diverged"
        for k in py:
            assert py[k] == js[k], (
                f"case {i} field {k}: python={py[k]} js={js[k]} mix={case['mix']}")


# --- CROSS-ENGINE: run the JS golden test from pytest so one command catches drift ---

@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
@pytest.mark.parametrize("js_test", JS_TESTS, ids=lambda p: p.name)
def test_js_suite_passes(js_test):
    proc = subprocess.run(
        ["node", "--test", str(js_test)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
