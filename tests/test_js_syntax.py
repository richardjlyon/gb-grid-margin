"""Gate: all browser ES-module entry points must parse as valid ES modules.

`node --input-type=module --check` is the effective check — plain script mode
does NOT catch smart-quote/module-syntax errors that show up at import time.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

ENTRY_POINTS = [
    REPO / "site" / "app.js",
    REPO / "site" / "live.js",
    REPO / "site" / "warnings.js",
    REPO / "site" / "share.js",
    REPO / "site" / "render.js",
    REPO / "site" / "postmortem.js",
    REPO / "site" / "postmortem-draw.js",
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
@pytest.mark.parametrize("js_file", ENTRY_POINTS, ids=lambda p: p.name)
def test_js_module_syntax(js_file):
    """Strict ES-module parse of each browser entry point via node --input-type=module --check."""
    result = subprocess.run(
        ["node", "--input-type=module", "--check"],
        input=js_file.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{js_file.name} failed ES-module syntax check:\n{result.stderr}"
    )
