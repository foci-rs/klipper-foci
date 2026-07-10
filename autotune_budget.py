"""Host-side safe-motion budget calculation for FOCI Stage 2 autotune."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_AUTOTUNE_TRAVEL_MM = 40.0
MAX_AUTOTUNE_TRAVEL_MM = 120.0
AUTOTUNE_SAFETY_MARGIN_MM = 10.0
DEFAULT_MAX_VELOCITY_MREV_S = 6000
DEFAULT_MAX_DURATION_MS = 3000
DIRECTION_BOTH = 0x03


class AutotuneBudgetError(Exception):
    """Raised when host-side motion budget cannot be computed safely."""


@dataclass(frozen=True)
class AutotuneMotionBudget:
    """Firmware-ready motion budget plus host safe-pose evidence."""

    kinematics: str
    stepper_role: str
    safe_x: float
    safe_y: float
    max_travel_mm: float
    max_travel_mrev: int
    max_velocity_mrev_s: int
    max_duration_ms: int
    direction_mask: int


def _status_axis_tuple(status: dict, key: str) -> tuple[float, float]:
    value = status.get(key)
    if value is None or len(value) < 2:
        raise AutotuneBudgetError("missing X/Y %s" % key)
    return float(value[0]), float(value[1])


def _kinematics_kind(kinematics) -> str:
    name = type(kinematics).__name__.lower()
    if "corexy" in name:
        return "corexy"
    if "cartesian" in name or "cart" in name:
        return "cartesian"
    raise AutotuneBudgetError("unsupported kinematics '%s'" % type(kinematics).__name__)


def _stepper_role(stepper_name: str) -> str:
    short = stepper_name.split()[-1]
    if short.endswith("stepper_x"):
        return "x"
    if short.endswith("stepper_y"):
        return "y"
    raise AutotuneBudgetError(
        "named stepper '%s' is outside supported XY motion set" % stepper_name
    )


def _rotation_distance_mm(driver) -> float:
    toolhead = driver.printer.lookup_object("toolhead")
    kinematics = toolhead.get_kinematics()
    rails = getattr(kinematics, "rails", None)
    if rails is None and hasattr(kinematics, "get_rails"):
        rails = kinematics.get_rails()
    if rails is not None:
        for rail in rails:
            for stepper in rail.get_steppers():
                if stepper.get_name() == driver.stepper_name:
                    return (
                        float(stepper.get_step_dist())
                        * float(driver.config.microsteps)
                        * float(driver.config.full_steps)
                    )
    get_steppers = getattr(kinematics, "get_steppers", None)
    if get_steppers is not None:
        for stepper in get_steppers():
            if stepper.get_name() == driver.stepper_name:
                return (
                    float(stepper.get_step_dist())
                    * float(driver.config.microsteps)
                    * float(driver.config.full_steps)
                )
    raise AutotuneBudgetError(
        "could not resolve rotation_distance for '%s'" % driver.stepper_name
    )


def _kinematic_budget_mm(
    kind: str,
    role: str,
    x_clearance: float,
    y_clearance: float,
) -> float:
    if kind == "cartesian" and role == "x":
        return x_clearance
    if kind == "cartesian" and role == "y":
        return y_clearance
    if kind == "corexy":
        return 2.0 * min(x_clearance, y_clearance)
    raise AutotuneBudgetError("unsupported kinematics/stepper combination")


def compute_autotune_motion_budget(driver, gcmd) -> AutotuneMotionBudget:
    """Compute firmware motor-space motion caps for one named FOCI stepper."""
    toolhead = driver.printer.lookup_object("toolhead")
    kinematics = toolhead.get_kinematics()
    kind = _kinematics_kind(kinematics)
    role = _stepper_role(driver.stepper_name)
    status = toolhead.get_status(toolhead.get_last_move_time())
    homed = set(status.get("homed_axes", ""))
    if not {"x", "y"}.issubset(homed):
        missing = "".join(sorted({"x", "y"} - homed))
        raise AutotuneBudgetError("printer not homed for X/Y (missing: %s)" % missing)

    _status_axis_tuple(status, "position")
    min_x, min_y = _status_axis_tuple(status, "axis_minimum")
    max_x, max_y = _status_axis_tuple(status, "axis_maximum")
    safe_x = (min_x + max_x) / 2.0
    safe_y = (min_y + max_y) / 2.0
    x_clearance = min(safe_x - min_x, max_x - safe_x)
    y_clearance = min(safe_y - min_y, max_y - safe_y)

    requested_mm = gcmd.get_float(
        "TRAVEL",
        DEFAULT_AUTOTUNE_TRAVEL_MM,
        minval=1.0,
        maxval=MAX_AUTOTUNE_TRAVEL_MM,
    )
    available_mm = _kinematic_budget_mm(kind, role, x_clearance, y_clearance)
    safe_mm = min(requested_mm, available_mm) - AUTOTUNE_SAFETY_MARGIN_MM
    if safe_mm <= 0.0:
        raise AutotuneBudgetError("insufficient X/Y travel for FOCI_AUTOTUNE")

    rotation_distance = _rotation_distance_mm(driver)
    if rotation_distance <= 0.0:
        raise AutotuneBudgetError(
            "invalid rotation_distance for '%s'" % driver.stepper_name
        )
    max_travel_mrev = int(round((safe_mm / rotation_distance) * 1000.0))
    if max_travel_mrev <= 0:
        raise AutotuneBudgetError("insufficient motor travel for FOCI_AUTOTUNE")

    return AutotuneMotionBudget(
        kinematics=kind,
        stepper_role=role,
        safe_x=safe_x,
        safe_y=safe_y,
        max_travel_mm=safe_mm,
        max_travel_mrev=max_travel_mrev,
        max_velocity_mrev_s=DEFAULT_MAX_VELOCITY_MREV_S,
        max_duration_ms=DEFAULT_MAX_DURATION_MS,
        direction_mask=DIRECTION_BOTH,
    )


def format_safe_pose_move(budget: AutotuneMotionBudget) -> str:
    """Return the Klipper move command for the selected safe pose."""
    return "G0 X%.3f Y%.3f" % (budget.safe_x, budget.safe_y)
