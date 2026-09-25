"""Tests for firmware stepper-event diagnostics."""

import logging

from tests.mocks import MockGCode, make_driver


def test_stepper_event_handler_reports_nothing_without_debug(caplog):
    """FOCI_STEPPER_EVENT is per-step noise: report_detail's contract is that
    with [foci] debug off, it is dropped everywhere -- not console, not log."""
    driver = make_driver(stepper_name="stepper_x")
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    with caplog.at_level(logging.INFO, logger="klipper_foci.diagnostics.passive"):
        driver.diagnostics.handle_stepper_event(
            {
                "reason": 4,
                "channel": 0,
                "position": 6465,
                "clock": 123456,
                "timer_active": 1,
                "queue_len": 17,
                "direction": 1,
                "data0": 20,
                "data1": 45150,
            }
        )

    assert gcode._responses == []
    assert caplog.records == []


def test_stepper_event_handler_formats_known_reason_for_log_only(caplog):
    """With [foci] debug on, FOCI_STEPPER_EVENT reaches klippy.log but still
    never the console -- it stays developer detail, not an operator summary."""
    driver = make_driver(stepper_name="stepper_x")
    driver.global_config.debug = True
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    with caplog.at_level(logging.INFO, logger="klipper_foci.diagnostics.passive"):
        driver.diagnostics.handle_stepper_event(
            {
                "reason": 4,
                "channel": 0,
                "position": 6465,
                "clock": 123456,
                "timer_active": 1,
                "queue_len": 17,
                "direction": 1,
                "data0": 20,
                "data1": 45150,
            }
        )

    assert gcode._responses == []
    assert caplog.records[0].message == (
        "FOCI_STEPPER_EVENT stepper_x reason=trsync_stop(4) channel=0 "
        "pos=6465 clock=123456 timer_active=1 queue_len=17 dir=1 "
        "data0=20 data1=45150"
    )


def test_stepper_event_handler_formats_unknown_reason_without_crashing(caplog):
    driver = make_driver(stepper_name="stepper_y")
    driver.global_config.debug = True
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    with caplog.at_level(logging.INFO, logger="klipper_foci.diagnostics.passive"):
        driver.diagnostics.handle_stepper_event(
            {
                "reason": 99,
                "channel": 0,
                "position": -13,
                "clock": 7,
                "timer_active": 0,
                "queue_len": 0,
                "direction": 0,
                "data0": 0,
                "data1": 0,
            }
        )

    assert "reason=unknown(99)" in caplog.records[-1].message
    assert "stepper_y" in caplog.records[-1].message
