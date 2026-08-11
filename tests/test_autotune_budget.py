"""Tests for host-side autotune motion budgeting."""

import pytest
from klipper_foci.autotune_budget import (
    AutotuneBudgetError,
    _motor_headroom_mm,
    compute_autotune_motion_budget,
    format_safe_pose_move,
)

from tests.mocks import (
    MockCartesianKinematics,
    MockCoreXYKinematics,
    MockGCmd,
    make_driver,
)


class GetRailsCartesianKinematics:
    """Cartesian kinematics that exposes rails through get_rails only."""

    def __init__(self):
        self._delegate = MockCartesianKinematics()

    def get_rails(self):
        return self._delegate.rails


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
    stepper = driver.printer.lookup_object("toolhead").get_kinematics().rails[0].get_steppers()[0]
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    assert budget.kinematics == "cartesian"
    assert budget.stepper_role == "x"
    assert budget.safe_x == pytest.approx(60.0)
    assert budget.safe_y == pytest.approx(60.0)
    assert budget.max_travel_mm == pytest.approx(50.0)
    assert budget.max_stroke_travel_mrev == 1500
    assert budget.settle_travel_reserve_mrev == 250
    assert budget.negative_position_headroom_mrev == 1250
    assert budget.positive_position_headroom_mrev == 1250
    assert budget.machine_velocity_ceiling_mrev_s == 7500
    assert budget.requested_velocity_mrev_s == 5000
    assert budget.requested_velocity_source == 1


def test_corexy_budget_doubles_axis_clearance_before_margin():
    driver = ready_driver("stepper_x", MockCoreXYKinematics())
    stepper = driver.printer.lookup_object("toolhead").get_kinematics().rails[0].get_steppers()[0]
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({"TRAVEL": "70"}))

    assert budget.kinematics == "corexy"
    assert budget.stepper_role == "x"
    assert budget.max_travel_mm == pytest.approx(60.0)
    assert budget.max_stroke_travel_mrev == 1750
    assert budget.settle_travel_reserve_mrev == 250
    assert budget.negative_position_headroom_mrev == 2500
    assert budget.positive_position_headroom_mrev == 2500


def test_budget_resolves_rotation_distance_from_get_rails_kinematics():
    kin = GetRailsCartesianKinematics()
    driver = ready_driver("stepper_x", kin)
    kin.get_rails()[0].get_steppers()[0]._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    assert budget.max_stroke_travel_mrev == 1500


def test_default_travel_uses_the_machine_budget_bounded_by_headroom():
    """No TRAVEL parameter takes the machine's own budget, not a fixed figure.

    CoreXY at the centre of a 120 mm bed offers 2 * min(60, 60) = 120 mm of
    kinematic travel, but only 120 - 20 = 100 mm of absolute position headroom
    after the CoreXY-domain margin. The moving stroke follows the headroom, so
    the full stroke is 110 and moving travel is 100.
    """
    driver = ready_driver("stepper_x", MockCoreXYKinematics())
    stepper = driver.printer.lookup_object("toolhead").get_kinematics().rails[0].get_steppers()[0]
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    assert budget.max_travel_mm == pytest.approx(100.0)
    assert budget.max_stroke_travel_mrev == 2750


def test_default_moving_stroke_fits_inside_the_position_window():
    """The planned moving stroke never exceeds the runtime position guard.

    Firmware plans travel velocity from `max_stroke_travel_mrev` less
    `settle_travel_reserve_mrev`, while the headroom fields bound the
    non-faulting position window. The first must not exceed the second, or the
    default relies on a safety guard to contain motion it planned.
    """
    for kinematics in (MockCartesianKinematics(), MockCoreXYKinematics()):
        driver = ready_driver("stepper_x", kinematics)
        toolhead = driver.printer.lookup_object("toolhead")
        toolhead.get_kinematics().rails[0].get_steppers()[0]._step_dist = 0.01

        budget = compute_autotune_motion_budget(driver, MockGCmd({}))

        moving_allowance = budget.max_stroke_travel_mrev - budget.settle_travel_reserve_mrev
        assert moving_allowance <= budget.negative_position_headroom_mrev
        assert moving_allowance <= budget.positive_position_headroom_mrev


def test_default_travel_is_bounded_by_the_safety_cap():
    """A machine with more travel than the cap still stops at the cap."""
    driver = ready_driver("stepper_x", MockCoreXYKinematics())
    toolhead = driver.printer.lookup_object("toolhead")
    toolhead.set_bounds(x_min=0.0, x_max=400.0, y_min=0.0, y_max=400.0)
    toolhead.set_position(x=200.0, y=200.0)
    stepper = toolhead.get_kinematics().rails[0].get_steppers()[0]
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    assert budget.max_travel_mm == pytest.approx(110.0)
    assert budget.max_stroke_travel_mrev == 3000


def test_default_travel_enforces_the_invariant_after_integer_conversion():
    """A millimetre-domain bound can still overshoot the window by one mrev.

    Each field is floored independently, so when the rotation distance does not
    divide the settle margin cleanly the moving allowance can exceed the
    position window by one unit. Here rd = 32 mm makes the margin 312.5 mrev,
    and the clamp must land on the integer fields rather than the millimetres.
    """
    driver = ready_driver("stepper_x", MockCoreXYKinematics())
    toolhead = driver.printer.lookup_object("toolhead")
    toolhead.set_bounds(x_min=0.0, x_max=120.02, y_min=0.0, y_max=120.02)
    toolhead.get_kinematics().rails[0].get_steppers()[0]._step_dist = 0.008

    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    moving_allowance = budget.max_stroke_travel_mrev - budget.settle_travel_reserve_mrev
    assert moving_allowance == budget.negative_position_headroom_mrev
    assert moving_allowance <= budget.positive_position_headroom_mrev


def test_explicit_travel_beyond_the_position_window_is_rejected():
    """An explicit TRAVEL past the window is refused, not silently clamped."""
    driver = ready_driver("stepper_x", MockCoreXYKinematics())
    stepper = driver.printer.lookup_object("toolhead").get_kinematics().rails[0].get_steppers()[0]
    stepper._step_dist = 0.01

    with pytest.raises(AutotuneBudgetError, match="absolute-position window"):
        compute_autotune_motion_budget(driver, MockGCmd({"TRAVEL": "120"}))


def test_explicit_tune_velocity_is_converted_to_motor_space():
    driver = ready_driver("stepper_x", MockCartesianKinematics())
    stepper = driver.printer.lookup_object("toolhead").get_kinematics().rails[0].get_steppers()[0]
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(
        driver,
        MockGCmd({"TUNE_VELOCITY": "200"}),
    )

    assert budget.requested_velocity_mrev_s == 5000
    assert budget.requested_velocity_source == 0
    assert budget.machine_velocity_ceiling_mrev_s == 7500


def test_default_velocity_uses_firmware_published_envelope_constants():
    driver = ready_driver("stepper_x", MockCartesianKinematics())
    driver.mcu.constants.update(
        {
            "ENVELOPE_PROPORTIONAL_NUM": 4,
            "ENVELOPE_PROPORTIONAL_DEN": 3,
            "ENVELOPE_ABSOLUTE_MARGIN_MREV_S": 1000,
        }
    )
    stepper = driver.printer.lookup_object("toolhead").get_kinematics().rails[0].get_steppers()[0]
    stepper._step_dist = 0.01

    budget = compute_autotune_motion_budget(driver, MockGCmd({}))

    assert budget.machine_velocity_ceiling_mrev_s == 7500
    assert budget.requested_velocity_mrev_s == 5625
    assert budget.requested_velocity_source == 1


@pytest.mark.parametrize(
    "constants, message",
    [
        ({}, "missing firmware envelope constant"),
        (
            {
                "ENVELOPE_PROPORTIONAL_NUM": 3,
                "ENVELOPE_PROPORTIONAL_DEN": 0,
                "ENVELOPE_ABSOLUTE_MARGIN_MREV_S": 2000,
            },
            "invalid firmware envelope constants",
        ),
    ],
)
def test_missing_or_invalid_firmware_envelope_constants_refuse(constants, message):
    driver = ready_driver("stepper_x", MockCartesianKinematics())
    driver.mcu.constants.clear()
    driver.mcu.constants.update(constants)

    with pytest.raises(AutotuneBudgetError, match=message):
        compute_autotune_motion_budget(driver, MockGCmd({}))


def test_corexy_motor_headroom_preserves_asymmetric_safe_window():
    negative, positive = _motor_headroom_mm(
        "corexy",
        "x",
        x=30.0,
        y=70.0,
        min_x=0.0,
        min_y=0.0,
        max_x=120.0,
        max_y=120.0,
    )

    assert negative == pytest.approx(60.0)
    assert positive == pytest.approx(100.0)


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
