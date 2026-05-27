"""FOCI host G-code command registry and global mode config."""

from __future__ import annotations

from dataclasses import dataclass

MODE_LEVELS: dict[str, int] = {
    "default": 0,
    "advanced": 1,
    "expert": 2,
    "developer": 3,
}

MODE_CHOICES: dict[str, str] = {mode: mode for mode in MODE_LEVELS}


class FociGlobalConfig:
    """Global `[foci]` host-module configuration."""

    def __init__(self, config) -> None:
        self.mode: str = config.getchoice("mode", MODE_CHOICES, default="default")


@dataclass(frozen=True)
class GcodeCommandSpec:
    """One host-visible mux G-code command registration."""

    name: str
    min_mode: str
    handler_name: str
    help_attr: str


GCODE_COMMANDS: tuple[GcodeCommandSpec, ...] = (
    GcodeCommandSpec("DUMP_FOCI", "default", "cmd_DUMP_FOCI", "cmd_DUMP_FOCI_help"),
    GcodeCommandSpec("DUMP_TMC", "default", "cmd_DUMP_FOCI", "cmd_DUMP_FOCI_help"),
    GcodeCommandSpec(
        "FOCI_SELFTEST", "default", "cmd_FOCI_SELFTEST", "cmd_FOCI_SELFTEST_help"
    ),
    GcodeCommandSpec(
        "FOCI_COMMISSION",
        "default",
        "cmd_FOCI_COMMISSION",
        "cmd_FOCI_COMMISSION_help",
    ),
    GcodeCommandSpec(
        "FOCI_AUTOTUNE", "default", "cmd_FOCI_AUTOTUNE", "cmd_FOCI_AUTOTUNE_help"
    ),
    GcodeCommandSpec(
        "FOCI_SET_GAINS", "default", "cmd_FOCI_SET_GAINS", "cmd_FOCI_SET_GAINS_help"
    ),
    GcodeCommandSpec(
        "FOCI_SET_INNER_GAINS",
        "default",
        "cmd_FOCI_SET_INNER_GAINS",
        "cmd_FOCI_SET_INNER_GAINS_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_CURRENT",
        "default",
        "cmd_FOCI_SET_CURRENT",
        "cmd_FOCI_SET_CURRENT_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_FEEDFORWARD",
        "default",
        "cmd_FOCI_SET_VELOCITY_FEEDFORWARD",
        "cmd_FOCI_SET_VELOCITY_FEEDFORWARD_help",
    ),
    GcodeCommandSpec(
        "FOCI_STEP_POSITION",
        "advanced",
        "cmd_FOCI_STEP_POSITION",
        "cmd_FOCI_STEP_POSITION_help",
    ),
    GcodeCommandSpec(
        "FOCI_STEPPER_STATS",
        "advanced",
        "cmd_FOCI_STEPPER_STATS",
        "cmd_FOCI_STEPPER_STATS_help",
    ),
    GcodeCommandSpec(
        "FOCI_DISPATCH_STATS",
        "advanced",
        "cmd_FOCI_DISPATCH_STATS",
        "cmd_FOCI_DISPATCH_STATS_help",
    ),
    GcodeCommandSpec("FOCI_TRACE", "advanced", "cmd_FOCI_TRACE", "cmd_FOCI_TRACE_help"),
    GcodeCommandSpec(
        "FOCI_TRACE_START",
        "advanced",
        "cmd_FOCI_TRACE_START",
        "cmd_FOCI_TRACE_START_help",
    ),
    GcodeCommandSpec(
        "FOCI_TRACE_STOP",
        "advanced",
        "cmd_FOCI_TRACE_STOP",
        "cmd_FOCI_TRACE_STOP_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "expert",
        "cmd_FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "cmd_FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_ACCEL_FEEDFORWARD",
        "expert",
        "cmd_FOCI_SET_ACCEL_FEEDFORWARD",
        "cmd_FOCI_SET_ACCEL_FEEDFORWARD_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_DECOUPLING_FEEDFORWARD",
        "expert",
        "cmd_FOCI_SET_DECOUPLING_FEEDFORWARD",
        "cmd_FOCI_SET_DECOUPLING_FEEDFORWARD_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_POSITION_LEAD",
        "expert",
        "cmd_FOCI_SET_POSITION_LEAD",
        "cmd_FOCI_SET_POSITION_LEAD_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_PHASE_ADVANCE",
        "expert",
        "cmd_FOCI_SET_PHASE_ADVANCE",
        "cmd_FOCI_SET_PHASE_ADVANCE_help",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VOLTAGE_LIMIT",
        "expert",
        "cmd_FOCI_SET_VOLTAGE_LIMIT",
        "cmd_FOCI_SET_VOLTAGE_LIMIT_help",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_STEP_TEST",
        "expert",
        "cmd_FOCI_CURRENT_STEP_TEST",
        "cmd_FOCI_CURRENT_STEP_TEST_help",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_VECTOR_STEP_TEST",
        "expert",
        "cmd_FOCI_CURRENT_VECTOR_STEP_TEST",
        "cmd_FOCI_CURRENT_VECTOR_STEP_TEST_help",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "expert",
        "cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST_help",
    ),
    GcodeCommandSpec(
        "FOCI_POSITION_TORQUE_OFFSET_TEST",
        "expert",
        "cmd_FOCI_POSITION_TORQUE_OFFSET_TEST",
        "cmd_FOCI_POSITION_TORQUE_OFFSET_TEST_help",
    ),
    GcodeCommandSpec(
        "FOCI_VOLTAGE_STEP_TEST",
        "expert",
        "cmd_FOCI_VOLTAGE_STEP_TEST",
        "cmd_FOCI_VOLTAGE_STEP_TEST_help",
    ),
)


def mode_allows(active_mode: str, min_mode: str) -> bool:
    """Return true when `active_mode` includes `min_mode`."""
    return MODE_LEVELS[active_mode] >= MODE_LEVELS[min_mode]


def register_gcode_commands(driver, gcode, mode: str) -> None:
    """Register all host-visible G-code commands allowed by `mode`."""
    for spec in GCODE_COMMANDS:
        if not mode_allows(mode, spec.min_mode):
            continue
        gcode.register_mux_command(
            spec.name,
            "STEPPER",
            driver.stepper_name,
            getattr(driver, spec.handler_name),
            desc=getattr(driver, spec.help_attr),
        )
