"""FOCI register dump workflow."""

from __future__ import annotations

from .registers import (
    DUMP_GROUPS,
    FIELD_FORMATTERS,
    REGISTERS,
    SIGNED_FIELDS,
    Fields,
    FieldHelper,
)

LIVE_GAIN_FIELDS: tuple[tuple[str, str], ...] = (
    ("flux_p", "PID_FLUX_P_FLUX_I"),
    ("flux_i", "PID_FLUX_P_FLUX_I"),
    ("torque_p", "PID_TORQUE_P_TORQUE_I"),
    ("torque_i", "PID_TORQUE_P_TORQUE_I"),
    ("velocity_p", "PID_VELOCITY_P_VELOCITY_I"),
    ("velocity_i", "PID_VELOCITY_P_VELOCITY_I"),
    ("position_p", "PID_POSITION_P_POSITION_I"),
    ("position_i", "PID_POSITION_P_POSITION_I"),
    ("velocity_limit", "PID_VELOCITY_LIMIT"),
)

ACTIVE_GAIN_FIELDS: tuple[str, ...] = (
    "flux_p",
    "flux_i",
    "torque_p",
    "torque_i",
    "velocity_p",
    "velocity_i",
    "position_p",
    "position_i",
    "velocity_limit",
    "velocity_filter_hz",
    "torque_filter_hz",
    "position_filter_hz",
    "flux_filter_hz",
)

CONFIG_GAIN_FIELDS: tuple[str, ...] = (
    "pid_flux_p",
    "pid_flux_i",
    "pid_torque_p",
    "pid_torque_i",
    "pid_velocity_p",
    "pid_velocity_i",
    "pid_position_p",
    "pid_position_i",
    "pid_velocity_limit",
    "commissioned_velocity_p",
    "commissioned_velocity_i",
    "commissioned_position_p",
    "commissioned_position_i",
    "commissioned_velocity_limit",
)

IDENTIFIED_MODEL_FIELDS: tuple[str, ...] = (
    "identified_r_count_milli",
    "identified_l_count_micro",
    "identified_r_int",
    "identified_l_int",
    "identified_lambda_us",
    "identified_tau_e_us",
    "identified_tau_e_crosscheck_us",
    "identified_tau_residual_permille",
    "identified_theta_e_us",
    "identified_ringing_count",
    "identified_bandwidth_hz",
    "identified_inner_warning_flags",
)

# Firmware-owned resistance-identification evidence (count-space, no
# host-side fitting). Displayed as persisted; not recomputed here.
RESISTANCE_IDENTIFICATION_FIELDS: tuple[str, ...] = (
    "identified_r_profile_version",
    "identified_r_count_slope_milli",
    "identified_r_gain_path_count_slope_milli",
    "identified_r_axis0_count_slope_milli",
    "identified_r_axis1_count_slope_milli",
    "identified_r_axis0_intercept_count",
    "identified_r_axis1_intercept_count",
    "identified_r_axis0_rmse_permille",
    "identified_r_axis1_rmse_permille",
    "identified_r_selected_mask_axis0",
    "identified_r_selected_mask_axis1",
    "identified_r_axis0_signed_count_slope_milli",
    "identified_r_axis1_signed_count_slope_milli",
    "identified_r_axis0_signed_asymmetry_permille",
    "identified_r_axis1_signed_asymmetry_permille",
    "identified_r_axis0_drift_permille",
    "identified_r_axis1_drift_permille",
    "identified_r_status_flags_or",
    "identified_r_warning_flags",
)

COMPARE_GAIN_FIELDS: tuple[str, ...] = tuple(
    field_name for field_name, _reg_name in LIVE_GAIN_FIELDS
)


class RegisterDumpWorkflow:
    """Own DUMP_FOCI/DUMP_TMC command handling and dump response state."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self._dump_buffer: dict[int, int] = {}
        self._dump_complete = False
        self.fields = FieldHelper(Fields, SIGNED_FIELDS, FIELD_FORMATTERS)

    def handle_dump_value(self, params: dict) -> None:
        """Handle a single register value from the firmware dump."""
        self._dump_buffer[params["addr"]] = params["value"]

    def handle_dump_done(self, params: dict) -> None:
        """Handle dump completion signal from firmware."""
        self._dump_complete = True

    def write_register(self, gcmd) -> None:
        """Throwaway debug: write one raw TMC4671 register (dev firmware)."""
        addr = int(gcmd.get("ADDR"), 0) & 0xFF
        value = int(gcmd.get("VALUE"), 0) & 0xFFFFFFFF
        self.driver.protocol.write_register(addr, value)
        gcmd.respond_info(f"FOCI write reg {addr:#04x} = {value:#010x}")

    def read_register(self, gcmd) -> None:
        """Throwaway debug: read one raw TMC4671 register (dev firmware)."""
        addr = int(gcmd.get("ADDR"), 0) & 0xFF
        value = self.driver.protocol.read_register(addr)
        gcmd.respond_info(f"FOCI read reg {addr:#04x} = {value:#010x}")

    def dump_registers(self, gcmd) -> None:
        """Handler for DUMP_FOCI and DUMP_TMC GCode commands.

        Sends a single foci_dump_registers command to the firmware and
        waits for all register values to be streamed back via the
        FOCI:DUMP: output protocol, then prints them formatted to the
        GCode console. ``TUNING=1`` appends host-derived read-only tuning
        analysis using the same dump response.
        """
        include_tuning = bool(gcmd.get_int("TUNING", 0, minval=0, maxval=1))
        reactor = self.driver.printer.get_reactor()
        self._dump_buffer.clear()
        self._dump_complete = False
        self.driver.protocol.dump_registers()

        # Wait for dump completion. The serial reader thread calls
        # handle_dump_done which sets _dump_complete.
        deadline = reactor.monotonic() + 5.0
        while not self._dump_complete and reactor.monotonic() < deadline:
            reactor.pause(reactor.monotonic() + 0.05)

        if not self._dump_complete:
            gcmd.respond_info("FOCI register dump timed out")
            return

        lines: list[str] = []
        for group_name, regs in DUMP_GROUPS:
            if "%s" in group_name:
                header = group_name % self.driver.stepper_name
            else:
                header = group_name
            lines.append("========== %s ==========" % header)
            for reg_name in regs:
                addr = REGISTERS[reg_name]
                if addr in self._dump_buffer:
                    val = self._dump_buffer[addr]
                    lines.append(self.fields.pretty_format(reg_name, val))
                else:
                    lines.append("  %-30s = (not in dump)" % reg_name)

        if include_tuning:
            lines.extend(self._format_tuning_analysis())

        gcmd.respond_info("\n".join(lines))

    def _format_tuning_analysis(self) -> list[str]:
        config = self.driver.config
        state = self.driver.state
        active_gains = state.active_gains
        live_gains = self._live_gain_values()

        lines = [
            "",
            "========== Tuning Analysis ==========",
            "-- Runtime status --",
            self._format_pair("autotune_status", config.autotune_status),
            self._format_pair("runtime_status", state.runtime_status),
            self._format_pair(
                "active_gains_present",
                "yes" if active_gains is not None else "no",
            ),
            self._format_pair("autotune_profile", config.autotune_profile),
            self._format_pair("autotune_mode", config.autotune_mode),
        ]

        persisted_status = config.autotune_status or "uncommissioned"
        if persisted_status != state.runtime_status:
            lines.append(
                "  WARNING: autotune_status/runtime_status divergence persisted=%s"
                " validated=%s" % (persisted_status, state.runtime_status)
            )

        lines.append("-- Live TMC gains --")
        lines.extend(
            self._format_pair("live.%s" % field_name, value)
            for field_name, value in live_gains.items()
        )

        lines.append("-- Host active gains --")
        if active_gains is None:
            lines.append("  active_gains unavailable")
        else:
            lines.extend(
                self._format_pair(
                    "active.%s" % field_name, active_gains.get(field_name)
                )
                for field_name in ACTIVE_GAIN_FIELDS
            )

        lines.append("-- Persisted config gains --")
        lines.extend(
            self._format_pair("config.%s" % field_name, getattr(config, field_name))
            for field_name in CONFIG_GAIN_FIELDS
        )

        lines.append("-- Identified count-space model --")
        lines.extend(
            self._format_pair("config.%s" % field_name, getattr(config, field_name))
            for field_name in IDENTIFIED_MODEL_FIELDS
        )
        lines.append(
            "  Note: identified_r*/identified_l* are FOCI count-space"
            " commissioning values; validated physical R/L comparison is"
            " tracked separately."
        )

        lines.append("-- Resistance identification evidence --")
        lines.extend(
            self._format_pair("config.%s" % field_name, getattr(config, field_name))
            for field_name in RESISTANCE_IDENTIFICATION_FIELDS
        )
        lines.append(
            "  Note: identified_r_* resistance fields are firmware-reported"
            " count-space evidence (selected/gain-path/per-axis slopes,"
            " fit quality, signed-anchor, and drift); the host performs no"
            " fitting or quality-gate evaluation."
        )

        lines.append("-- Comparison --")
        lines.extend(self._format_gain_comparison(live_gains, active_gains))
        return lines

    def _live_gain_values(self) -> dict[str, int | None]:
        values: dict[str, int | None] = {}
        for field_name, reg_name in LIVE_GAIN_FIELDS:
            addr = REGISTERS[reg_name]
            if addr not in self._dump_buffer:
                values[field_name] = None
                continue
            values[field_name] = self.fields.get_field(
                field_name,
                reg_name,
                self._dump_buffer[addr],
            )
        return values

    def _format_gain_comparison(
        self,
        live_gains: dict[str, int | None],
        active_gains: dict[str, int] | None,
    ) -> list[str]:
        if active_gains is None:
            return ["  active_gains unavailable; live/host comparison skipped"]

        warnings: list[str] = []
        for field_name in COMPARE_GAIN_FIELDS:
            live_value = live_gains.get(field_name)
            host_value = active_gains.get(field_name)
            if live_value is None:
                warnings.append(
                    "  WARNING: %s live value unavailable host=%s"
                    % (field_name, self._display_value(host_value))
                )
            elif host_value is None:
                warnings.append(
                    "  WARNING: %s host value unavailable live=%s"
                    % (field_name, self._display_value(live_value))
                )
            elif live_value != host_value:
                warnings.append(
                    "  WARNING: %s mismatch live=%s host=%s"
                    % (
                        field_name,
                        self._display_value(live_value),
                        self._display_value(host_value),
                    )
                )

        if warnings:
            return warnings
        return ["  live register gains match host active_gains"]

    def _format_pair(self, name: str, value: object | None) -> str:
        return "  %-34s = %s" % (name, self._display_value(value))

    def _display_value(self, value: object | None) -> str:
        if value is None:
            return "(unset)"
        return str(value)
