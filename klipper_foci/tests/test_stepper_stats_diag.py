"""Regression test: no-motion FOCI stats commands no longer live on core."""

from tests.mocks import make_driver


def test_passive_diagnostics_no_longer_has_stats_methods():
    driver = make_driver()
    for name in ("step_position", "stepper_stats", "stack_watermark"):
        assert not hasattr(driver.diagnostics.passive, name)
