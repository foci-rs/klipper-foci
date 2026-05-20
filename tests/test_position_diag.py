"""Tests for no-motion FOCI step-position diagnostics."""

from tests.mocks import (
    MockCartesianKinematics,
    MockCommand,
    MockGCmd,
    MockStepper,
    make_driver,
)


def test_step_position_diagnostic_reports_raw_host_and_klipper_delta():
    stepper = MockStepper(
        "stepper_x",
        oid=10,
        mcu_position=15000,
        dir_inverted=True,
        step_dist=0.01,
    )
    kin = MockCartesianKinematics([[stepper]])
    driver = make_driver(stepper_name="stepper_x", kinematics=kin)
    driver.oid = 10
    driver.stepper_get_position_cmd = MockCommand({"pos": -19176})
    gcmd = MockGCmd()

    driver.cmd_FOCI_STEP_POSITION(gcmd)

    assert driver.stepper_get_position_cmd.last_args == [10]
    assert "FOCI_STEP_POSITION stepper_x:" in gcmd.last_info
    assert "raw=-19176" in gcmd.last_info
    assert "host=19176" in gcmd.last_info
    assert "klipper=15000" in gcmd.last_info
    assert "delta=4176" in gcmd.last_info
    assert "invert_dir=1" in gcmd.last_info
    assert "step_dist=0.010000" in gcmd.last_info
    assert "delta_mm=41.760" in gcmd.last_info


def test_step_position_diagnostic_leaves_non_inverted_raw_position_unchanged():
    stepper = MockStepper(
        "stepper_y",
        oid=12,
        mcu_position=8000,
        dir_inverted=False,
        step_dist=0.01,
    )
    kin = MockCartesianKinematics([[stepper]])
    driver = make_driver(stepper_name="stepper_y", kinematics=kin)
    driver.oid = 12
    driver.stepper_get_position_cmd = MockCommand({"pos": 8125})
    gcmd = MockGCmd()

    driver.cmd_FOCI_STEP_POSITION(gcmd)

    assert driver.stepper_get_position_cmd.last_args == [12]
    assert "raw=8125" in gcmd.last_info
    assert "host=8125" in gcmd.last_info
    assert "klipper=8000" in gcmd.last_info
    assert "delta=125" in gcmd.last_info
    assert "invert_dir=0" in gcmd.last_info
    assert "delta_mm=1.250" in gcmd.last_info
