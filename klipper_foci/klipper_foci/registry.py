"""FOCI host G-code command registry and global mode config."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points

ENTRY_POINT_GROUP = "klipper_foci.commands"


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
)


def discover_optional_specs(driver) -> tuple[GcodeCommandSpec, ...]:
    """Call every `klipper_foci.commands` entry point and concatenate its specs."""
    specs: list[GcodeCommandSpec] = []
    claimed_by: dict[str, str] = dict.fromkeys(vars(driver), "core")
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        before = dict(vars(driver))
        register = entry_point.load()
        new_specs = register(driver)
        for name, value in vars(driver).items():
            if name not in before or value is not before[name]:
                previous_owner = claimed_by.get(name)
                if previous_owner is not None and previous_owner != entry_point.name:
                    raise driver.printer.config_error(
                        f"FOCI: entry points '{previous_owner}' and "
                        f"'{entry_point.name}' both set driver.{name}"
                    )
                claimed_by[name] = entry_point.name
        specs.extend(new_specs)
    return tuple(specs)


def register_gcode_commands(
    driver,
    gcode,
    command_specs: tuple[GcodeCommandSpec, ...] = GCODE_COMMANDS,
) -> None:
    """Register all host-visible G-code commands in `command_specs`."""
    for spec in command_specs:
        if not hasattr(driver, spec.component):
            raise driver.printer.config_error(
                f"FOCI: command {spec.name} names component '{spec.component}', "
                "which no entry point actually attached to the driver"
            )
        component = getattr(driver, spec.component)
        if not hasattr(component, spec.handler_name):
            raise driver.printer.config_error(
                f"FOCI: command {spec.name} names handler '{spec.handler_name}' "
                f"on component '{spec.component}', which has no such attribute"
            )
        gcode.register_mux_command(
            spec.name,
            "STEPPER",
            driver.stepper_name,
            getattr(component, spec.handler_name),
            desc=spec.help_text,
        )
