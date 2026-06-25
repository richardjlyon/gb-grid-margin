"""Stage 4 — historical nameplate as an annual DUKES 6.2 series, applied annual-step.

Historical capacity factors need capacity *as of each year*, not the single end-2024
anchor. The interpolation rule is annual-step (decided 2026-06-25): each year's published
DUKES value is held until the next, so every denominator is a verbatim, citable figure —
no modelled in-between numbers, per the v1 rule.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.models import Nameplate, NameplateSeries, NameplateYear

SERIES_PATH = Path(__file__).resolve().parent.parent / "data" / "nameplate_series.json"
ANCHOR_PATH = Path(__file__).resolve().parent.parent / "data" / "nameplate.json"


class TestNameplateYear:
    def test_wind_total_is_onshore_plus_offshore(self):
        y = NameplateYear(year=2024, wind_onshore_gw=16.166,
                          wind_offshore_gw=15.916, solar_gw=18.28)
        assert y.wind_gw == pytest.approx(32.082, abs=0.001)


class TestAnnualStep:
    def _series(self):
        return NameplateSeries(
            source="x", source_url="https://example.com", interpolation="annual-step",
            series=[
                NameplateYear(year=2016, wind_onshore_gw=10.833,
                              wind_offshore_gw=5.293, solar_gw=11.914),
                NameplateYear(year=2024, wind_onshore_gw=16.166,
                              wind_offshore_gw=15.916, solar_gw=18.28),
            ])

    def test_returns_the_year_in_force(self):
        assert self._series().capacity_for(2016).solar_gw == 11.914

    def test_holds_last_published_for_later_year(self):
        # 2025/2026 not yet in DUKES — annual-step holds the 2024 value.
        assert self._series().capacity_for(2026).year == 2024

    def test_holds_value_between_published_points(self):
        # 2020 falls between the 2016 and 2024 points; annual-step holds 2016.
        assert self._series().capacity_for(2020).year == 2016

    def test_year_before_first_raises(self):
        with pytest.raises(ValueError, match="2009"):
            self._series().capacity_for(2009)

    def test_rejects_unsupported_interpolation(self):
        with pytest.raises(ValidationError):
            NameplateSeries(source="x", source_url="https://example.com",
                            interpolation="linear",
                            series=[NameplateYear(year=2024, wind_onshore_gw=1.0,
                                                  wind_offshore_gw=1.0, solar_gw=1.0)])

    def test_rejects_unsorted_series(self):
        with pytest.raises(ValidationError):
            NameplateSeries(source="x", source_url="https://example.com",
                            interpolation="annual-step",
                            series=[NameplateYear(year=2024, wind_onshore_gw=1.0,
                                                  wind_offshore_gw=1.0, solar_gw=1.0),
                                    NameplateYear(year=2016, wind_onshore_gw=1.0,
                                                  wind_offshore_gw=1.0, solar_gw=1.0)])


class TestShippedSeries:
    def test_validates_and_is_cited(self):
        s = NameplateSeries.model_validate_json(SERIES_PATH.read_text())
        assert s.interpolation == "annual-step"
        assert s.source
        assert s.source_url.startswith("http")
        assert s.published

    def test_covers_clean_data_edge_to_2024(self):
        s = NameplateSeries.model_validate_json(SERIES_PATH.read_text())
        years = {p.year for p in s.series}
        assert {2016, 2024} <= years

    def test_end_2024_reconciles_with_anchor(self):
        s = NameplateSeries.model_validate_json(SERIES_PATH.read_text())
        anchor = Nameplate.model_validate_json(ANCHOR_PATH.read_text())
        y2024 = s.capacity_for(2024)
        assert y2024.year == 2024
        assert y2024.wind_onshore_gw == pytest.approx(anchor.wind_onshore_gw, abs=0.001)
        assert y2024.wind_offshore_gw == pytest.approx(anchor.wind_offshore_gw, abs=0.001)
        assert y2024.solar_gw == pytest.approx(anchor.solar_gw, abs=0.001)
