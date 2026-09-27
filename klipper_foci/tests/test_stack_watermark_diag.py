"""Regression test: the stack-watermark stats command no longer lives on core."""

from tests.mocks import make_driver


def test_passive_diagnostics_no_longer_has_stack_watermark():
    driver = make_driver()
    assert not hasattr(driver.diagnostics.passive, "stack_watermark")
