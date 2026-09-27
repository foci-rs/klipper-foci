"""FOCI host G-code command registry and global mode config."""

from __future__ import annotations

from dataclasses import dataclass


class FociGlobalConfig:
    """Global `[foci]` host-module configuration."""

    def __init__(self, config) -> None:
        if config.get("mode", None) is not None:
            raise config.error(
                "[foci] no longer supports 'mode' -- install "
                "klipper-foci-diagnostics/klipper-foci-tuning instead of "
                "setting a mode"
            )
        self.debug: bool = config.getboolean("debug", default=False)


@dataclass(frozen=True)
class GcodeCommandSpec:
    """One host-visible mux G-code command registration."""

    name: str
    component: str
    handler_name: str
    help_text: str


GCODE_COMMANDS: tuple[GcodeCommandSpec, ...] = (
    GcodeCommandSpec(
        "DUMP_FOCI",
        "dump",
        "dump_registers",
        "Dump TMC4671 register state for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "DUMP_TMC",
        "dump",
        "dump_registers",
        "Dump TMC4671 register state for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "FOCI_SELFTEST",
        "selftest",
        "selftest",
        "Run TMC4671 self-test for a FOCI stepper",
    ),
    GcodeCommandSpec(
        "FOCI_SETUP",
        "commissioning",
        "commission",
        "Commission a FOCI stepper (diagnostics + current tune + closed-loop entry)",
    ),
    GcodeCommandSpec(
        "FOCI_AUTOTUNE",
        "autotune",
        "autotune",
        "Tune installed FOCI stepper (requires commissioning + homing)",
    ),
    GcodeCommandSpec(
        "FOCI_SET_GAINS",
        "controls",
        "set_gains",
        "Set FOCI outer gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_INNER_GAINS",
        "controls",
        "set_inner_gains",
        "Set FOCI inner current gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_FILTERS",
        "controls",
        "set_filters",
        "Set FOCI runtime biquad low-pass filters for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_CURRENT",
        "controls",
        "set_current",
        "Set FOCI run current for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_FEEDFORWARD",
        "controls",
        "set_velocity_feedforward",
        "Set FOCI velocity feedforward runtime gain for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_STEP_POSITION",
        "diagnostics",
        "step_position",
        "Query raw FOCI MCU step position without syncing Klipper",
    ),
    GcodeCommandSpec(
        "FOCI_STEPPER_STATS",
        "diagnostics",
        "stepper_stats",
        "Query FOCI MCU step queue/execution counters without motion",
    ),
    GcodeCommandSpec(
        "FOCI_STACK_WATERMARK",
        "diagnostics",
        "stack_watermark",
        "Query unused FOCI MCU stack headroom since boot without motion",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "controls",
        "set_velocity_transient_feedforward",
        "Set FOCI diagnostic velocity transient feedforward for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_ACCEL_FEEDFORWARD",
        "controls",
        "set_accel_feedforward",
        "Set FOCI acceleration/deceleration feedforward runtime gains for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_DECOUPLING_FEEDFORWARD",
        "controls",
        "set_decoupling_feedforward",
        "Set FOCI diagnostic q/d decoupling proxy feedforward for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_POSITION_LEAD",
        "controls",
        "set_position_lead",
        "Set FOCI diagnostic position-target lead for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_PHASE_ADVANCE",
        "controls",
        "set_phase_advance",
        "Set FOCI diagnostic commutation phase advance for bringup debugging",
    ),
    GcodeCommandSpec(
        "FOCI_SET_VOLTAGE_LIMIT",
        "controls",
        "set_voltage_limit",
        "Set FOCI PIDOUT_UQ_UD_LIMITS for bringup authority diagnostics",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_STEP_TEST",
        "diagnostics",
        "current_step_test",
        "Run a bounded FOCI current-loop step diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_VECTOR_STEP_TEST",
        "diagnostics",
        "current_vector_step_test",
        "Run a bounded FOCI current-vector step diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "diagnostics",
        "current_torque_sample_test",
        "Run a bounded FOCI torque pulse and sample it early",
    ),
    GcodeCommandSpec(
        "FOCI_POSITION_TORQUE_OFFSET_TEST",
        "diagnostics",
        "position_torque_offset_test",
        "Run a bounded FOCI position-mode torque-offset sample",
    ),
    GcodeCommandSpec(
        "FOCI_VOLTAGE_STEP_TEST",
        "diagnostics",
        "voltage_step_test",
        "Run a bounded FOCI open-loop voltage-vector diagnostic",
    ),
    GcodeCommandSpec(
        "FOCI_RESISTANCE_TEST",
        "diagnostics",
        "resistance_test",
        "Run the shared FOCI resistance-identification diagnostic",
    ),
)


def register_gcode_commands(
    driver,
    gcode,
    command_specs: tuple[GcodeCommandSpec, ...] = GCODE_COMMANDS,
) -> None:
    """Register all host-visible G-code commands in `command_specs`."""
    for spec in command_specs:
        component = getattr(driver, spec.component)
        gcode.register_mux_command(
            spec.name,
            "STEPPER",
            driver.stepper_name,
            getattr(component, spec.handler_name),
            desc=spec.help_text,
        )
