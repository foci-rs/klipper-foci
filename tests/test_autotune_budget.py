"""Tests for host-side autotune motion budgeting."""

import pytest

from klipper_foci.autotune_budget import (
    AutotuneBudgetError,
    compute_autotune_motion_budget,
    format_safe_pose_move,
)
from tests.mocks import (
    MockCartesianKinematics,
    MockCoreXYKinematics,
    MockGCmd,
    make_driver,
)


def ready_driver(stepper_name="stepper_x", kinematics=None):
    driver = make_driver(
        stepper_name=stepper_name,
        kinematics=kinematics or MockCartesianKinematics(),
        homed_axes="xy",
    )
    toolhead = driver.printer.lookup_object("toolhead")
    toolhead.set_bounds(x_min=0.0, x_max=120.0, y_min=0.0, y_max=120.0)
    toolhead.set_position(x=60.0, y=60.0)
    return driver


def test_cartesian_x_budget_applies_margin_and_rotation_distance():
    driver = ready_driver("stepper_x", MockCartesianKinematics())
    stepper = (
        driver.printer.lookup_object("toolhead")
        .get_kinematics()
        .rails[0]
        .get_steppers()[0]
    )
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    assert budget.kinematics == "cartesian"
    assert budget.stepper_role == "x"
    assert budget.safe_x == pytest.approx(60.0)
    assert budget.safe_y == pytest.approx(60.0)
    assert budget.max_travel_mm == pytest.approx(30.0)
    assert budget.max_travel_mrev == 750


def test_corexy_budget_doubles_axis_clearance_before_margin():
    driver = ready_driver("stepper_x", MockCoreXYKinematics())
    stepper = (
        driver.printer.lookup_object("toolhead")
        .get_kinematics()
        .rails[0]
        .get_steppers()[0]
    )
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({"TRAVEL": "70"}))

    assert budget.kinematics == "corexy"
    assert budget.stepper_role == "x"
    assert budget.max_travel_mm == pytest.approx(60.0)
    assert budget.max_travel_mrev == 1500


def test_unsupported_kinematics_refuses():
    driver = make_driver(stepper_name="stepper_x", homed_axes="xy")

    with pytest.raises(AutotuneBudgetError, match="unsupported kinematics"):
        compute_autotune_motion_budget(driver, MockGCmd({}))


def test_insufficient_clearance_refuses_before_firmware():
    driver = ready_driver("stepper_x", MockCartesianKinematics())
    toolhead = driver.printer.lookup_object("toolhead")
    toolhead.set_bounds(x_min=0.0, x_max=12.0, y_min=0.0, y_max=120.0)
    toolhead.set_position(x=6.0, y=60.0)

    with pytest.raises(AutotuneBudgetError, match="insufficient"):
        compute_autotune_motion_budget(driver, MockGCmd({}))


def test_safe_pose_command_targets_center():
    driver = ready_driver("stepper_x", MockCartesianKinematics())
    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    assert format_safe_pose_move(budget) == "G0 X60.000 Y60.000"
