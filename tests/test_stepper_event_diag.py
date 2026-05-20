"""Tests for firmware stepper-event diagnostics."""

from tests.mocks import MockGCode, make_driver


def test_stepper_event_handler_formats_known_reason_for_gcode_output():
    driver = make_driver(stepper_name="stepper_x")
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    driver._handle_stepper_event(
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

    assert gcode._responses == [
        "FOCI_STEPPER_EVENT stepper_x reason=trsync_stop(4) channel=0 "
        "pos=6465 clock=123456 timer_active=1 queue_len=17 dir=1 "
        "data0=20 data1=45150"
    ]


def test_stepper_event_handler_formats_unknown_reason_without_crashing():
    driver = make_driver(stepper_name="stepper_y")
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    driver._handle_stepper_event(
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

    assert "reason=unknown(99)" in gcode._responses[-1]
    assert "stepper_y" in gcode._responses[-1]
