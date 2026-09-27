"""Tests for routing oid-less firmware stepper events to the right driver."""

import logging

from klipper_foci.protocol import FociProtocol
from tests.mocks import MockMCU, make_driver


def _event(channel):
    return {
        "reason": 2,
        "channel": channel,
        "position": 27618,
        "clock": 3826875503,
        "timer_active": 1,
        "queue_len": 3,
        "direction": 0,
        "data0": 0,
        "data1": 0,
    }


def _bind_two_channels():
    mcu = MockMCU(name="ouroboros")
    drivers = []
    for channel, name in ((0, "stepper_x"), (1, "stepper_y")):
        driver = make_driver(stepper_name=name)
        driver.channel = channel
        driver.global_config.debug = True
        driver.protocol = FociProtocol(driver)
        driver.protocol.bind_mcu(mcu, driver.oid)
        drivers.append(driver)
    return mcu, drivers


def _stepper_event_callbacks(mcu):
    return [
        callback for callback, name, _oid in mcu._serial.responses if name == "foci_stepper_event"
    ]


def test_one_stepper_event_registration_per_mcu():
    mcu, _drivers = _bind_two_channels()

    assert len(_stepper_event_callbacks(mcu)) == 1


def test_stepper_event_is_labelled_by_its_channel_not_registration_order(caplog):
    mcu, _drivers = _bind_two_channels()
    (dispatch,) = _stepper_event_callbacks(mcu)

    with caplog.at_level(logging.INFO):
        dispatch(_event(0))
        dispatch(_event(1))

    messages = [r.message for r in caplog.records]
    assert messages[0].startswith("FOCI_STEPPER_EVENT stepper_x reason=")
    assert "channel=0" in messages[0]
    assert messages[1].startswith("FOCI_STEPPER_EVENT stepper_y reason=")
    assert "channel=1" in messages[1]


def test_stepper_event_for_unmapped_channel_names_the_mcu(caplog):
    mcu, _drivers = _bind_two_channels()
    (dispatch,) = _stepper_event_callbacks(mcu)

    with caplog.at_level(logging.INFO):
        dispatch(_event(7))

    (message,) = [r.message for r in caplog.records]
    assert message.startswith("FOCI_STEPPER_EVENT mcu ouroboros reason=")
    assert "channel=7" in message
    assert "stepper_x" not in message
    assert "stepper_y" not in message
