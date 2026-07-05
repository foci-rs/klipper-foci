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
        "dump",
        "dump_registers",
        "Dump TMC4671 register state for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "DUMP_TMC",
        "default",
        "dump",
        "dump_registers",
        "Dump TMC4671 register state for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "FOCI_SELFTEST",
        "default",
        "selftest",
        "selftest",
        "Run TMC4671 self-test for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "FOCI_COMMISSION",
        "default",
        "commissioning",
        "commission",
        "Commission a FOCI stepper (Stage 1: diagnostics + current tune + closed-loop entry)",
    ),
    GcodeCommandSpec(
        "FOCI_AUTOTUNE",
        "default",
        "autotune",
        "autotune",
        "Tune installed FOCI stepper (Stage 2: requires commissioning + homing)",
    ),
    GcodeCommandSpec(
        "FOCI_SET_GAINS",
        "default",
        "controls",
        "set_gains",
        "Set FOCI outer gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_INNER_GAINS",
        "default",
        "controls",
        "set_inner_gains",
        "Set FOCI inner current gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_CURRENT",
        "default",
        "controls",
        "set_current",
        "Set FOCI run current for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_FEEDFORWARD",
        "default",
        "controls",
        "set_velocity_feedforward",
        "Set FOCI velocity feedforward runtime multiplier for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_STEP_POSITION",
        "advanced",
        "diagnostics",
        "step_position",
        "Query raw FOCI MCU step position without syncing Klipper",
    ),
    GcodeCommandSpec(
        "FOCI_STEPPER_STATS",
        "advanced",
        "diagnostics",
        "stepper_stats",
        "Query FOCI MCU step queue/execution counters without motion",
    ),
    GcodeCommandSpec(
        "FOCI_DISPATCH_STATS",
        "advanced",
        "diagnostics",
        "dispatch_stats",
        "Query FOCI MCU step-dispatch cycle counters without motion",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "expert",
        "controls",
        "set_velocity_transient_feedforward",
        "Set FOCI diagnostic velocity transient feedforward for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_ACCEL_FEEDFORWARD",
        "expert",
        "controls",
        "set_accel_feedforward",
        "Set FOCI acceleration/deceleration feedforward runtime gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_DECOUPLING_FEEDFORWARD",
        "expert",
        "controls",
        "set_decoupling_feedforward",
        "Set FOCI diagnostic q/d decoupling proxy feedforward for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_POSITION_LEAD",
        "expert",
        "controls",
        "set_position_lead",
        "Set FOCI diagnostic position-target lead for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_PHASE_ADVANCE",
        "expert",
        "controls",
        "set_phase_advance",
        "Set FOCI diagnostic commutation phase advance for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VOLTAGE_LIMIT",
        "expert",
        "controls",
        "set_voltage_limit",
        "Set FOCI PIDOUT_UQ_UD_LIMITS for bringup authority diagnostics",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_STEP_TEST",
        "expert",
        "diagnostics",
        "current_step_test",
        "Run a bounded FOCI current-loop step diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_VECTOR_STEP_TEST",
        "expert",
        "diagnostics",
        "current_vector_step_test",
        "Run a bounded FOCI current-vector step diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "expert",
        "diagnostics",
        "current_torque_sample_test",
        "Run a bounded FOCI torque pulse and sample it early",
    ),
    GcodeCommandSpec(
        "FOCI_POSITION_TORQUE_OFFSET_TEST",
        "expert",
        "diagnostics",
        "position_torque_offset_test",
        "Run a bounded FOCI position-mode torque-offset sample",
    ),
    GcodeCommandSpec(
        "FOCI_VOLTAGE_STEP_TEST",
        "expert",
        "diagnostics",
        "voltage_step_test",
        "Run a bounded FOCI open-loop voltage-vector diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_RESISTANCE_TEST",
        "expert",
        "diagnostics",
        "resistance_test",
        "Run the shared FOCI resistance-identification diagnostic",
    ),
)

DEV_GCODE_COMMANDS: tuple[GcodeCommandSpec, ...] = (
    GcodeCommandSpec(
        "FOCI_TMC_READ_REGISTER",
        "developer",
        "diagnostics",
        "tmc_read_register",
        "Read a raw TMC4671 register through dev firmware",
    ),
    GcodeCommandSpec(
        "FOCI_TMC_WRITE_REGISTER",
        "developer",
        "controls",
        "tmc_write_register",
        "Write a raw TMC4671 register through dev firmware",
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
        component = getattr(driver, spec.component)
        gcode.register_mux_command(
            spec.name,
            "STEPPER",
            driver.stepper_name,
            getattr(component, spec.handler_name),
            desc=spec.help_text,
        )
