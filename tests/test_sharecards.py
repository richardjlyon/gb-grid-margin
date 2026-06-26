from pathlib import Path
from engine import sharecards


def test_module_constants():
    assert sharecards.SITE_URL == "https://gridgauge.co.uk"
    assert sharecards.CARD_W == 1200 and sharecards.CARD_H == 630
    assert (sharecards.TEMPLATES / "fonts").is_dir()
