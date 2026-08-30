"""Tests for the no-motion FOCI MCU stack-headroom query."""

import pytest

from tests.mocks import CommandError, MockCommand, MockGCmd, make_driver


def make_watermark_driver(response):
    driver = make_driver(stepper_name="stepper_x")
    driver.oid = 10
    driver.protocol.commands.stack_watermark = MockCommand(response)
    return driver


def test_stack_watermark_reports_headroom_and_painted_span():
    driver = make_watermark_driver(
        {
            "oid": 10,
            "stack_unused_bytes": 40960,
            "painted_bytes": 97280,
            "status": 0,
        }
    )
    gcmd = MockGCmd()

    driver.diagnostics.stack_watermark(gcmd)

    assert driver.protocol.commands.stack_watermark.last_args == [10]
    assert "stack_unused_bytes=40960" in gcmd.last_info
    assert "painted_bytes=97280" in gcmd.last_info
    assert "lower bound" not in gcmd.last_info


def test_stack_watermark_flags_an_untouched_span_as_a_lower_bound():
    driver = make_watermark_driver(
        {
            "oid": 10,
            "stack_unused_bytes": 97280,
            "painted_bytes": 97280,
            "status": 0,
        }
    )
    gcmd = MockGCmd()

    driver.diagnostics.stack_watermark(gcmd)

    assert "lower bound" in gcmd.last_info


def test_stack_watermark_rejects_a_board_that_never_painted():
    driver = make_watermark_driver(
        {"oid": 10, "stack_unused_bytes": 0, "painted_bytes": 0, "status": 1}
    )

    with pytest.raises(CommandError, match="status=1"):
        driver.diagnostics.stack_watermark(MockGCmd())


def test_stack_watermark_rejects_an_incomplete_reply():
    driver = make_watermark_driver({"oid": 10, "status": 0})

    with pytest.raises(CommandError, match="incomplete data"):
        driver.diagnostics.stack_watermark(MockGCmd())


def test_stack_watermark_rejects_a_missing_reply():
    driver = make_watermark_driver(None)

    with pytest.raises(CommandError, match="returned no data"):
        driver.diagnostics.stack_watermark(MockGCmd())


def test_stack_watermark_requires_mcu_identify():
    driver = make_watermark_driver({"oid": 10})
    driver.oid = None

    with pytest.raises(CommandError, match="before MCU identify"):
        driver.diagnostics.stack_watermark(MockGCmd())
