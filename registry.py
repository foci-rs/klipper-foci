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
    component: str
    handler_name: str
    help_text: str


GCODE_COMMANDS: tuple[GcodeCommandSpec, ...] = (
    GcodeCommandSpec(
        "DUMP_FOCI",
        "default",
        "driver",
        "cmd_DUMP_FOCI",
        "Dump TMC4671 register state for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "DUMP_TMC",
        "default",
        "driver",
        "cmd_DUMP_FOCI",
        "Dump TMC4671 register state for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "FOCI_SELFTEST",
        "default",
        "driver",
        "cmd_FOCI_SELFTEST",
        "Run TMC4671 self-test for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "FOCI_COMMISSION",
        "default",
        "driver",
        "cmd_FOCI_COMMISSION",
        "Commission a FOCI stepper (Stage 1: diagnostics + current tune + closed-loop entry)",
    ),
    GcodeCommandSpec(
        "FOCI_AUTOTUNE",
        "default",
        "driver",
        "cmd_FOCI_AUTOTUNE",
        "Tune installed FOCI stepper (Stage 2: requires commissioning + homing)",
    ),
    GcodeCommandSpec(
        "FOCI_SET_GAINS",
        "default",
        "driver",
        "cmd_FOCI_SET_GAINS",
        "Set FOCI outer gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_INNER_GAINS",
        "default",
        "driver",
        "cmd_FOCI_SET_INNER_GAINS",
        "Set FOCI inner current gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_CURRENT",
        "default",
        "driver",
        "cmd_FOCI_SET_CURRENT",
        "Set FOCI run current for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_FEEDFORWARD",
        "default",
        "driver",
        "cmd_FOCI_SET_VELOCITY_FEEDFORWARD",
        "Set FOCI velocity feedforward runtime multiplier for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_STEP_POSITION",
        "advanced",
        "driver",
        "cmd_FOCI_STEP_POSITION",
        "Query raw FOCI MCU step position without syncing Klipper",
    ),
    GcodeCommandSpec(
        "FOCI_STEPPER_STATS",
        "advanced",
        "driver",
        "cmd_FOCI_STEPPER_STATS",
        "Query FOCI MCU step queue/execution counters without motion",
    ),
    GcodeCommandSpec(
        "FOCI_DISPATCH_STATS",
        "advanced",
        "driver",
        "cmd_FOCI_DISPATCH_STATS",
        "Query FOCI MCU step-dispatch cycle counters without motion",
    ),
    GcodeCommandSpec(
        "FOCI_TRACE",
        "advanced",
        "driver",
        "cmd_FOCI_TRACE",
        "Fetch and display trace capture buffer",
    ),
    GcodeCommandSpec(
        "FOCI_TRACE_START",
        "advanced",
        "driver",
        "cmd_FOCI_TRACE_START",
        "Start FOCI per-tick trace capture",
    ),
    GcodeCommandSpec(
        "FOCI_TRACE_STOP",
        "advanced",
        "driver",
        "cmd_FOCI_TRACE_STOP",
        "Stop FOCI per-tick trace capture",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "expert",
        "driver",
        "cmd_FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "Set FOCI diagnostic velocity transient feedforward for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_ACCEL_FEEDFORWARD",
        "expert",
        "driver",
        "cmd_FOCI_SET_ACCEL_FEEDFORWARD",
        "Set FOCI acceleration/deceleration feedforward runtime gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_DECOUPLING_FEEDFORWARD",
        "expert",
        "driver",
        "cmd_FOCI_SET_DECOUPLING_FEEDFORWARD",
        "Set FOCI diagnostic q/d decoupling proxy feedforward for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_POSITION_LEAD",
        "expert",
        "driver",
        "cmd_FOCI_SET_POSITION_LEAD",
        "Set FOCI diagnostic position-target lead for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_PHASE_ADVANCE",
        "expert",
        "driver",
        "cmd_FOCI_SET_PHASE_ADVANCE",
        "Set FOCI diagnostic commutation phase advance for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VOLTAGE_LIMIT",
        "expert",
        "driver",
        "cmd_FOCI_SET_VOLTAGE_LIMIT",
        "Set FOCI PIDOUT_UQ_UD_LIMITS for bringup authority diagnostics",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_STEP_TEST",
        "expert",
        "driver",
        "cmd_FOCI_CURRENT_STEP_TEST",
        "Run a bounded FOCI current-loop step diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_VECTOR_STEP_TEST",
        "expert",
        "driver",
        "cmd_FOCI_CURRENT_VECTOR_STEP_TEST",
        "Run a bounded FOCI current-vector step diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "expert",
        "driver",
        "cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "Run a bounded FOCI torque pulse and sample it early",
    ),
    GcodeCommandSpec(
        "FOCI_POSITION_TORQUE_OFFSET_TEST",
        "expert",
        "driver",
        "cmd_FOCI_POSITION_TORQUE_OFFSET_TEST",
        "Run a bounded FOCI position-mode torque-offset sample",
    ),
    GcodeCommandSpec(
        "FOCI_VOLTAGE_STEP_TEST",
        "expert",
        "driver",
        "cmd_FOCI_VOLTAGE_STEP_TEST",
        "Run a bounded FOCI open-loop voltage-vector diagnostic",
    ),
)


def mode_allows(active_mode: str, min_mode: str) -> bool:
    """Return true when `active_mode` includes `min_mode`."""
    return MODE_LEVELS[active_mode] >= MODE_LEVELS[min_mode]


def register_gcode_commands(
    driver,
    gcode,
    mode: str,
    command_specs: tuple[GcodeCommandSpec, ...] = GCODE_COMMANDS,
) -> None:
    """Register all host-visible G-code commands allowed by `mode`."""
    for spec in command_specs:
        if not mode_allows(mode, spec.min_mode):
            continue
        component = (
            driver if spec.component == "driver" else getattr(driver, spec.component)
        )
        gcode.register_mux_command(
            spec.name,
            "STEPPER",
            driver.stepper_name,
            getattr(component, spec.handler_name),
            desc=spec.help_text,
        )
