# tests/test_conditions_markup.py
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "site/index.html").read_text()


def test_rail_replaces_old_warnstrip():
    assert 'class="warnstrip"' not in HTML and 'id="warnstrip"' not in HTML
    assert 'id="conditions"' in HTML
    for cid in ("cond-wind", "cond-firm", "cond-import", "cond-scarcity"):
        assert f'id="{cid}"' in HTML, cid
    # scarcity lamp is the official guest and links to the methodology ladder
    assert "methodology.html#warnings" in HTML
