"""Tests for FOCI MCU config-build command emission."""

import pytest

from tests.mocks import CommandError, MockMCU, make_config_driver, make_config_printer


def test_same_mcu_dual_channel_config_commands():
    printer, chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
            },
        }
    )
    mcu = chips["foci"]
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    mcu.run_config_callbacks()

    assert (
        "config_foci_tmc oid=%d stepper_oid=%d channel=0"
        % (driver_x.oid, driver_x.stepper_oid)
        in mcu.config_cmds
    )
    assert (
        "config_foci_tmc oid=%d stepper_oid=%d channel=1"
        % (driver_y.oid, driver_y.stepper_oid)
        in mcu.config_cmds
    )


def test_same_mcu_dual_channel_response_handlers_use_distinct_oids():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
            },
        }
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    assert driver_x.oid != driver_y.oid
    response_oids = {
        (name, oid) for _callback, name, oid in driver_x.mcu._serial.responses
    }
    assert ("foci_commission_result", driver_x.oid) in response_oids
    assert ("foci_commission_result", driver_y.oid) in response_oids
    assert ("foci_trace_info_result", driver_x.oid) in response_oids
    assert ("foci_trace_info_result", driver_y.oid) in response_oids


def test_dual_mcu_single_channel_config_commands():
    mcu_x = MockMCU("foci_x")
    mcu_y = MockMCU("foci_y")
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci_x:STEP0",
                "dir_pin": "foci_x:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci_y:STEP0",
                "dir_pin": "foci_y:DIR0",
                "oid": 12,
            },
        },
        chips={"foci_x": mcu_x, "foci_y": mcu_y},
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    mcu_x.run_config_callbacks()
    mcu_y.run_config_callbacks()

    assert mcu_x.config_cmds == [
        "config_foci_tmc oid=%d stepper_oid=%d channel=0"
        % (driver_x.oid, driver_x.stepper_oid)
    ]
    assert mcu_y.config_cmds == [
        "config_foci_tmc oid=%d stepper_oid=%d channel=0"
        % (driver_y.oid, driver_y.stepper_oid)
    ]


def test_dual_mcu_drivers_keep_runtime_state_separate():
    mcu_x = MockMCU("foci_x")
    mcu_y = MockMCU("foci_y")
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci_x:STEP0",
                "dir_pin": "foci_x:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci_y:STEP0",
                "dir_pin": "foci_y:DIR0",
                "oid": 12,
            },
        },
        chips={"foci_x": mcu_x, "foci_y": mcu_y},
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    driver_x._foci_lock = True
    driver_x._inhibited = True
    driver_x._trace_info = {"owner": "x"}

    assert driver_y._foci_lock is False
    assert driver_y._inhibited is False
    assert driver_y._trace_info is None


def test_step1_rejected_when_mcu_pin_dictionary_lacks_step1():
    mcu = MockMCU(
        "foci",
        allowed_pins={"STEP0", "DIR0", "ENA0"},
    )
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 10,
            },
        },
        chips={"foci": mcu},
    )

    with pytest.raises(CommandError, match="Unknown pin STEP1"):
        make_config_driver(printer, sections, "foci stepper_x")
