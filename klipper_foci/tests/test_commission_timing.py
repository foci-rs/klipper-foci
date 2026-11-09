"""Tests for commissioning timing evidence handling."""

import pytest

from klipper_foci import commissioning
from tests.mocks import (
    CommandError,
    MockConfigFile,
    MockGCmd,
    complete_commission_result,
    make_driver,
    timing_reply,
)


def test_timing_rejection_is_not_downgraded():
    driver = make_driver()

    driver.commissioning.handle_commission_timing(
        timing_reply(method=2, status=2, requested_period_us=160)
    )

    assert driver.commissioning.timing_by_method[2]["status"] == 2


def test_timing_summary_decodes_not_run_accepted_and_rejected():
    packed = 0 | (1 << 2) | (2 << 4) | (1 << 6) | (5 << 8) | (40 << 16)

    summary = commissioning.decode_timing_summary(packed)

    assert summary == {
        "statuses": {0: 0, 1: 1, 2: 2},
        "rejected": True,
        "overflowed": False,
        "missed_samples": 5,
        "max_lateness_us": 40,
    }


def test_timing_formatter_uses_microseconds_and_exact_field_order():
    assert commissioning.format_timing_evidence("resistance", timing_reply()) == (
        "timing resistance: status=accepted period_us=5000 valid=8 missed=0 "
        "max_lateness_us=12 max_interval_us=5012 max_poll_wall_us=20 "
        "max_spi_wall_us=8"
    )


def test_timing_detail_must_match_terminal_summary():
    driver = make_driver()
    driver.commissioning.handle_commission_timing(timing_reply(status=2))

    with pytest.raises(ValueError, match="resistance.*detail=rejected.*summary=accepted"):
        driver.commissioning.consume_timing_evidence(1)


def test_rejected_timing_is_fatal_even_with_plausible_model_values():
    driver = make_driver()
    driver.printer._objects["configfile"] = MockConfigFile()
    result = complete_commission_result()
    result["timing_summary"] = 2 << 4 | 1 << 6

    def drive_rejected_timing(_args):
        driver.commissioning.handle_commission_timing(
            timing_reply(method=2, status=2, requested_period_us=160)
        )
        driver.commissioning.result = result
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_rejected_timing

    with pytest.raises(CommandError, match="delay_timing"):
        driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert not driver.state.is_calibrated
    assert driver.commissioning.timing_by_method == {}


def test_rejected_timing_forces_a_real_disable_of_the_armed_motor():
    driver = make_driver()
    driver.printer._objects["configfile"] = MockConfigFile()
    result = complete_commission_result()
    result["timing_summary"] = 2 << 4 | 1 << 6
    enable_line = driver.printer.lookup_object("stepper_enable").lookup_enable(driver.stepper_name)

    def drive_rejected_timing(_args):
        driver.commissioning.handle_commission_timing(
            timing_reply(method=2, status=2, requested_period_us=160)
        )
        driver.commissioning.result = result
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_rejected_timing

    with pytest.raises(CommandError, match="delay_timing"):
        driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert not enable_line.is_motor_enabled()
    assert enable_line.real_disable_count == 1


def test_rejected_timing_disables_motor_with_enable_hooks_installed():
    driver = make_driver()
    driver.printer._objects["configfile"] = MockConfigFile()
    driver.homing.install_enable_hooks()
    result = complete_commission_result()
    result["timing_summary"] = 2 << 4 | 1 << 6
    enable_line = driver.printer.lookup_object("stepper_enable").lookup_enable(driver.stepper_name)

    def drive_rejected_timing(_args):
        driver.commissioning.handle_commission_timing(
            timing_reply(method=2, status=2, requested_period_us=160)
        )
        driver.commissioning.result = result
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_rejected_timing

    with pytest.raises(CommandError, match="timing evidence rejected"):
        driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert enable_line.real_disable_count == 1
    assert enable_line.enable_count == 0
    assert driver.state.inhibited
