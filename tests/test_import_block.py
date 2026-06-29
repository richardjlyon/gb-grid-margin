"""Parity tests for import_block — the pure helper that builds the live import-spend block
in latest.json. The golden inputs match the JS importRatePerHour tests so the engine and
browser port are pinned to the same arithmetic.
"""
from engine.build_site import import_block


def test_import_block_golden():
    """6890 MW × £800/MWh = £5,512,000/h — matches JS importRatePerHour(6890, 800)."""
    blk = import_block(6890.0, 19.1, 800.0, "latest settled half-hour · 27 Jun, 14:00")
    assert blk is not None
    assert blk["rate_per_h"] == 5_512_000.0


def test_import_block_export_floor():
    """Export (net ≤ 0) → £0/h — matches JS importRatePerHour(-500, 800)."""
    blk = import_block(-500.0, -1.4, 800.0, "latest settled half-hour · 27 Jun, 14:00")
    assert blk is not None
    assert blk["rate_per_h"] == 0.0


def test_import_block_none_price_returns_none():
    """Graceful degrade: no price available → import block is None (published as null)."""
    assert import_block(6890.0, 19.1, None, None) is None


def test_import_block_passthrough_fields():
    """All five fields are present when price is available."""
    stamp = "latest settled half-hour · 27 Jun, 14:00"
    blk = import_block(6890.0, 19.1, 800.0, stamp)
    assert blk is not None
    assert blk["net_import_mw"] == 6890.0
    assert blk["import_pct"] == 19.1
    assert blk["price_per_mwh"] == 800.0
    assert blk["price_stamp"] == stamp


def test_import_block_negative_price_floor():
    """Negative system price with positive import → £0/h — matches JS importRatePerHour(6890, -50)."""
    blk = import_block(6890.0, 19.1, -50.0, "latest settled half-hour · 27 Jun, 14:00")
    assert blk is not None
    assert blk["rate_per_h"] == 0.0
