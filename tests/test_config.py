"""Tests for FOCI MCU config-build command emission."""

import pytest

from tests.mocks import CommandError, MockMCU, make_config_driver, make_config_printer


def test_same_mcu_dual_channel_uses_stepper_oids_without_foci_config():
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
    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    assert mcu.config_cmds == []
    assert driver_x.oid == 10
    assert driver_y.oid == 12


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

    response_oids = {
        (name, oid) for _callback, name, oid in driver_x.mcu._serial.responses
    }
    assert ("foci_commission_result", 10) in response_oids
    assert ("foci_commission_result", 12) in response_oids
    assert ("foci_trace_info_result", 10) in response_oids
    assert ("foci_trace_info_result", 12) in response_oids


def test_dual_mcu_single_channel_uses_stepper_oids_without_foci_config():
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
    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    assert mcu_x.config_cmds == []
    assert mcu_y.config_cmds == []
    assert driver_x.oid == 10
    assert driver_y.oid == 12


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


def test_saved_commission_and_tune_fields_are_accepted_on_restart():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    sections["foci stepper_x"].update(
        {
            "identified_r_mohm": 1792,
            "identified_l_uh": 2046,
            "identified_lambda_us": 0,
            "identified_theta_e_us": 160,
            "identified_ringing_count": 7,
            "identified_bandwidth_hz": 0,
            "identified_tau_e_us": 1154,
            "identified_tau_e_crosscheck_us": 3821,
            "identified_tau_residual_permille": 1000,
            "identified_inner_warning_flags": 36,
            "identified_j_eff": 12345,
            "identified_b_eff": 678,
            "autotune_profile": "conservative",
            "autotune_mode": "nominal",
            "autotune_status": "commissioned",
        }
    )

    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert driver.identified_r_mohm == 1792
    assert driver.identified_l_uh == 2046
    assert driver.identified_tau_e_us == 1154
    assert driver.identified_j_eff == 12345
    assert driver.identified_b_eff == 678
    assert driver.autotune_profile == "conservative"
    assert driver.autotune_mode == "nominal"
    assert driver.autotune_status == "commissioned"
