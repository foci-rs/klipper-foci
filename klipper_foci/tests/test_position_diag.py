"""Regression test: the step-position diagnostic no longer lives on core."""

from tests.mocks import make_driver


def test_passive_diagnostics_no_longer_has_step_position():
    driver = make_driver()
    assert not hasattr(driver.diagnostics.passive, "step_position")
