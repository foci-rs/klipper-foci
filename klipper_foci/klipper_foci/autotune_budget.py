"""Host-side safe-motion budget calculation for FOCI installed-tuning autotune."""

from __future__ import annotations

from dataclasses import dataclass

MAX_AUTOTUNE_TRAVEL_MM = 120.0
AUTOTUNE_SAFETY_MARGIN_MM = 10.0
# Maximum duration of one active motion or excitation primitive.
DEFAULT_MAX_DURATION_MS = 3000
REQUESTED_VELOCITY_EXPLICIT = 0
REQUESTED_VELOCITY_DEFAULTED = 1

_ENVELOPE_CONSTANT_NAMES = (
    "ENVELOPE_PROPORTIONAL_NUM",
    "ENVELOPE_PROPORTIONAL_DEN",
    "ENVELOPE_ABSOLUTE_MARGIN_MREV_S",
)


class AutotuneBudgetError(Exception):
    """Raised when host-side motion budget cannot be computed safely."""


@dataclass(frozen=True)
class AutotuneMotionBudget:
    """Firmware-ready motion budget plus host safe-pose evidence.

    ``max_duration_ms`` caps one active motion or excitation primitive. It is
    not a whole-autotune timeout.
    """

    kinematics: str
    stepper_role: str
    safe_x: float
    safe_y: float
    max_travel_mm: float
    requested_velocity_mrev_s: int
    machine_velocity_ceiling_mrev_s: int
    requested_velocity_source: int
    max_stroke_travel_mrev: int
    settle_travel_reserve_mrev: int
    negative_position_headroom_mrev: int
    positive_position_headroom_mrev: int
    max_duration_ms: int
    homing_speed_mrev_s: int
    max_accel_mrev_s2: int


def _status_axis_tuple(status: dict, key: str) -> tuple[float, float]:
    value = status.get(key)
    if value is None or len(value) < 2:
        raise AutotuneBudgetError(f"missing X/Y {key}")
    return float(value[0]), float(value[1])


def _kinematics_kind(kinematics) -> str:
    name = type(kinematics).__name__.lower()
    if "corexy" in name:
        return "corexy"
    if "cartesian" in name or "cart" in name:
        return "cartesian"
    raise AutotuneBudgetError(f"unsupported kinematics '{type(kinematics).__name__}'")


def _stepper_role(stepper_name: str) -> str:
    short = stepper_name.split()[-1]
    if short.endswith("stepper_x"):
        return "x"
    if short.endswith("stepper_y"):
        return "y"
    raise AutotuneBudgetError(f"named stepper '{stepper_name}' is outside supported XY motion set")


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
    raise AutotuneBudgetError(f"could not resolve rotation_distance for '{driver.stepper_name}'")


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


def _motor_headroom_mm(
    kind: str,
    role: str,
    *,
    x: float,
    y: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> tuple[float, float]:
    """Return negative and positive motor travel before a printer-space bound."""
    if kind == "cartesian" and role == "x":
        return x - min_x, max_x - x
    if kind == "cartesian" and role == "y":
        return y - min_y, max_y - y
    if kind == "corexy" and role == "x":
        return 2.0 * min(x - min_x, y - min_y), 2.0 * min(max_x - x, max_y - y)
    if kind == "corexy" and role == "y":
        return 2.0 * min(x - min_x, max_y - y), 2.0 * min(max_x - x, y - min_y)
    raise AutotuneBudgetError("unsupported kinematics/stepper combination")


def _mrev(value_mm: float, rotation_distance_mm: float) -> int:
    """Convert a nonnegative printer-space distance to conservative motor mrev."""
    return int((value_mm * 1000.0) / rotation_distance_mm)


def _firmware_envelope_constants(driver) -> tuple[int, int, int]:
    get_constants = getattr(driver.mcu, "get_constants", None)
    constants = get_constants() if get_constants is not None else {}
    missing = [name for name in _ENVELOPE_CONSTANT_NAMES if name not in constants]
    if missing:
        raise AutotuneBudgetError(f"missing firmware envelope constant(s): {', '.join(missing)}")
    try:
        numerator, denominator, margin = (int(constants[name]) for name in _ENVELOPE_CONSTANT_NAMES)
    except (TypeError, ValueError) as err:
        raise AutotuneBudgetError("invalid firmware envelope constants") from err
    if numerator <= denominator or denominator <= 0 or margin <= 0:
        raise AutotuneBudgetError("invalid firmware envelope constants")
    return numerator, denominator, margin


def compute_autotune_motion_budget(driver, gcmd) -> AutotuneMotionBudget:
    """Compute firmware motor-space motion caps for one named FOCI stepper."""
    toolhead = driver.printer.lookup_object("toolhead")
    kinematics = toolhead.get_kinematics()
    kind = _kinematics_kind(kinematics)
    role = _stepper_role(driver.stepper_name)
    status = toolhead.get_status(toolhead.get_last_move_time())
    min_x, min_y = _status_axis_tuple(status, "axis_minimum")
    max_x, max_y = _status_axis_tuple(status, "axis_maximum")
    safe_x = (min_x + max_x) / 2.0
    safe_y = (min_y + max_y) / 2.0
    x_clearance = min(safe_x - min_x, max_x - safe_x)
    y_clearance = min(safe_y - min_y, max_y - safe_y)

    available_mm = _kinematic_budget_mm(kind, role, x_clearance, y_clearance)
    negative_mm, positive_mm = _motor_headroom_mm(
        kind,
        role,
        x=safe_x,
        y=safe_y,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
    )
    absolute_margin_mm = _kinematic_budget_mm(
        kind,
        role,
        AUTOTUNE_SAFETY_MARGIN_MM,
        AUTOTUNE_SAFETY_MARGIN_MM,
    )
    headroom_mm = min(negative_mm, positive_mm) - absolute_margin_mm
    travel_is_defaulted = gcmd.get("TRAVEL", None) is None
    if travel_is_defaulted:
        requested_travel_mm = min(
            available_mm,
            MAX_AUTOTUNE_TRAVEL_MM,
            headroom_mm + AUTOTUNE_SAFETY_MARGIN_MM,
        )
    else:
        requested_travel_mm = gcmd.get_float(
            "TRAVEL",
            None,
            minval=1.0,
            maxval=MAX_AUTOTUNE_TRAVEL_MM,
        )
    full_stroke_mm = min(requested_travel_mm, available_mm)
    moving_travel_mm = full_stroke_mm - AUTOTUNE_SAFETY_MARGIN_MM
    if moving_travel_mm <= 0.0:
        raise AutotuneBudgetError("insufficient X/Y travel for FOCI_AUTOTUNE")

    rotation_distance = _rotation_distance_mm(driver)
    if rotation_distance <= 0.0:
        raise AutotuneBudgetError(f"invalid rotation_distance for '{driver.stepper_name}'")
    settle_travel_reserve_mrev = _mrev(AUTOTUNE_SAFETY_MARGIN_MM, rotation_distance)
    negative_position_headroom_mrev = _mrev(negative_mm - absolute_margin_mm, rotation_distance)
    positive_position_headroom_mrev = _mrev(positive_mm - absolute_margin_mm, rotation_distance)
    if negative_position_headroom_mrev <= 0 or positive_position_headroom_mrev <= 0:
        raise AutotuneBudgetError("insufficient absolute-position headroom")

    safe_stroke_mrev = (
        min(negative_position_headroom_mrev, positive_position_headroom_mrev)
        + settle_travel_reserve_mrev
    )
    max_stroke_travel_mrev = _mrev(full_stroke_mm, rotation_distance)
    if max_stroke_travel_mrev > safe_stroke_mrev:
        if not travel_is_defaulted:
            safe_travel_mm = safe_stroke_mrev * rotation_distance / 1000.0
            raise AutotuneBudgetError(
                f"TRAVEL={requested_travel_mm:.1f} exceeds the absolute-position "
                f"window; the safe maximum here is {safe_travel_mm:.1f} mm"
            )
        max_stroke_travel_mrev = safe_stroke_mrev
    if (
        max_stroke_travel_mrev <= 0
        or settle_travel_reserve_mrev <= 0
        or settle_travel_reserve_mrev >= max_stroke_travel_mrev
    ):
        raise AutotuneBudgetError("insufficient motor travel for FOCI_AUTOTUNE")

    moving_travel_mm = (
        (max_stroke_travel_mrev - settle_travel_reserve_mrev) * rotation_distance / 1000.0
    )

    try:
        machine_velocity_mm_s = float(status["max_velocity"])
    except (KeyError, TypeError, ValueError) as err:
        raise AutotuneBudgetError("missing or invalid configured max_velocity") from err
    if machine_velocity_mm_s <= 0.0:
        raise AutotuneBudgetError("missing or invalid configured max_velocity")
    machine_velocity_ceiling_mrev_s = _mrev(machine_velocity_mm_s, rotation_distance)

    try:
        machine_accel_mm_s2 = float(status["max_accel"])
    except (KeyError, TypeError, ValueError) as err:
        raise AutotuneBudgetError("missing or invalid configured max_accel") from err
    if machine_accel_mm_s2 <= 0.0:
        raise AutotuneBudgetError("missing or invalid configured max_accel")
    max_accel_mrev_s2 = _mrev(machine_accel_mm_s2, rotation_distance)

    if driver.config.homing_speed_mm_s <= 0.0:
        raise AutotuneBudgetError("invalid configured homing_speed")
    homing_speed_mrev_s = _mrev(driver.config.homing_speed_mm_s, rotation_distance)
    numerator, denominator, margin_mrev_s = _firmware_envelope_constants(driver)
    if machine_velocity_ceiling_mrev_s <= margin_mrev_s:
        raise AutotuneBudgetError("configured max_velocity is below envelope margin")

    explicit_velocity = gcmd.get("TUNE_VELOCITY", None)
    if explicit_velocity is None:
        requested_velocity_mrev_s = min(
            denominator * machine_velocity_ceiling_mrev_s // numerator,
            machine_velocity_ceiling_mrev_s - margin_mrev_s,
        )
        requested_velocity_source = REQUESTED_VELOCITY_DEFAULTED
    else:
        requested_velocity_mm_s = gcmd.get_float(
            "TUNE_VELOCITY",
            minval=0.001,
            maxval=machine_velocity_mm_s,
        )
        requested_velocity_mrev_s = _mrev(requested_velocity_mm_s, rotation_distance)
        requested_velocity_source = REQUESTED_VELOCITY_EXPLICIT
    if requested_velocity_mrev_s <= 0:
        raise AutotuneBudgetError("requested velocity is not representable")

    return AutotuneMotionBudget(
        kinematics=kind,
        stepper_role=role,
        safe_x=safe_x,
        safe_y=safe_y,
        max_travel_mm=moving_travel_mm,
        requested_velocity_mrev_s=requested_velocity_mrev_s,
        machine_velocity_ceiling_mrev_s=machine_velocity_ceiling_mrev_s,
        requested_velocity_source=requested_velocity_source,
        max_stroke_travel_mrev=max_stroke_travel_mrev,
        settle_travel_reserve_mrev=settle_travel_reserve_mrev,
        negative_position_headroom_mrev=negative_position_headroom_mrev,
        positive_position_headroom_mrev=positive_position_headroom_mrev,
        max_duration_ms=DEFAULT_MAX_DURATION_MS,
        homing_speed_mrev_s=homing_speed_mrev_s,
        max_accel_mrev_s2=max_accel_mrev_s2,
    )


def format_safe_pose_move(budget: AutotuneMotionBudget) -> str:
    """Return the Klipper move command for the selected safe pose."""
    return f"G0 X{budget.safe_x:.3f} Y{budget.safe_y:.3f}"
