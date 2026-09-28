"""Live controller control commands for FOCI host workflows."""

from __future__ import annotations

from .config import (
    CURRENT_FILTER_MAX_HZ,
    FILTER_MIN_HZ,
    MOTION_FILTER_MAX_HZ,
    gain_to_permille,
)
from .constants import (
    MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
    MAX_RUN_CURRENT_AMPS,
    MIN_RAW_VOLTAGE_LIMIT,
    PID_GAIN_MAX_RAW,
)
from .registers import format_i_gain, format_p_gain


class ControlsWorkflow:
    """Apply live controller mutators requested through G-code."""

    def __init__(self, driver) -> None:
        self.driver = driver

    def set_gains(self, gcmd) -> None:
        """Set outer-loop gains for live bringup debugging.

        Parameters are floating-point gain values. For example, `VELOCITY_P=2.0`
        writes raw Q8.8 value 512 and `POSITION_P=1.0` writes raw value 256.
        The command is asynchronous and does not update host applied-state
        caches because firmware application is not confirmed.
        """
        velocity_p = self._get_p_gain(gcmd, "VELOCITY_P")
        velocity_i = self._get_i_gain(gcmd, "VELOCITY_I")
        position_p = self._get_p_gain(gcmd, "POSITION_P")
        position_i = self._get_i_gain(gcmd, "POSITION_I")

        self.driver.protocol.set_position_gains(
            position_p,
            position_i,
            velocity_p,
            velocity_i,
        )

        gcmd.respond_info(
            f"FOCI {self.driver.name} debug gain update requested: vel_p={int(velocity_p)}("
            f"{format_p_gain(velocity_p)}) vel_i={int(velocity_i)}({format_i_gain(velocity_i)}"
            f") pos_p={int(position_p)}({format_p_gain(position_p)}) pos_i={int(position_i)}("
            f"{format_i_gain(position_i)})"
        )

    def set_inner_gains(self, gcmd) -> None:
        """Set inner current-loop gains for live bringup debugging.

        Parameters are raw TMC4671 register values. P gains are Q8.8 and I
        gains are Q4.12. In advanced PI mode, the current-I effective zero
        factor is raw/1048576 per PWM sample. The
        command is asynchronous and does not update host applied-state caches
        because firmware application is not confirmed.
        """
        flux_p = gcmd.get_int("FLUX_P", minval=0, maxval=PID_GAIN_MAX_RAW)
        flux_i = gcmd.get_int("FLUX_I", minval=0, maxval=PID_GAIN_MAX_RAW)
        torque_p = gcmd.get_int("TORQUE_P", minval=0, maxval=PID_GAIN_MAX_RAW)
        torque_i = gcmd.get_int("TORQUE_I", minval=0, maxval=PID_GAIN_MAX_RAW)

        self.driver.protocol.set_pid_gains(flux_p, flux_i, torque_p, torque_i)

        gcmd.respond_info(
            f"FOCI {self.driver.name} inner gain update requested: flux_p={int(flux_p)}("
            f"{format_p_gain(flux_p)}) flux_i={int(flux_i)}({format_i_gain(flux_i)} zero="
            f"{int(flux_i)}/1048576) torque_p={int(torque_p)}({format_p_gain(torque_p)}) "
            f"torque_i={int(torque_i)}({format_i_gain(torque_i)} zero={int(torque_i)}/1048576)"
        )

    def set_filters(self, gcmd) -> None:
        """Set runtime biquad low-pass filters for live bringup debugging.

        Values are cutoff frequencies in Hz. `0` disables the corresponding
        filter. Values are applied immediately and kept in memory for the
        current Klipper session, but are not persisted to printer.cfg.
        """
        filters = (
            (
                "VELOCITY_HZ",
                "velocity",
                "velocity_filter_hz",
                MOTION_FILTER_MAX_HZ,
                self.driver.protocol.set_velocity_filter,
            ),
            (
                "TORQUE_HZ",
                "torque",
                "torque_filter_hz",
                CURRENT_FILTER_MAX_HZ,
                self.driver.protocol.set_torque_filter,
            ),
            (
                "POSITION_HZ",
                "position",
                "position_filter_hz",
                MOTION_FILTER_MAX_HZ,
                self.driver.protocol.set_position_filter,
            ),
            (
                "FLUX_HZ",
                "flux",
                "flux_filter_hz",
                CURRENT_FILTER_MAX_HZ,
                self.driver.protocol.set_flux_filter,
            ),
        )
        requested = [
            (label, attr, setter, value)
            for param, label, attr, max_hz, setter in filters
            if (value := self._get_filter_hz(gcmd, param, max_hz)) is not None
        ]
        applied = []

        for label, attr, setter, value in requested:
            setter(value)
            setattr(self.driver.settings, attr, value)
            if self.driver.state.active_gains is not None:
                self.driver.state.active_gains[attr] = value
            applied.append(f"{label}={int(value)}Hz")

        if not applied:
            raise gcmd.error(
                f"FOCI {self.driver.name} filters: specify at least one of VELOCITY_HZ, "
                f"TORQUE_HZ, POSITION_HZ, FLUX_HZ"
            )

        gcmd.respond_info(f"FOCI {self.driver.name} filters set: {' '.join(applied)}")

    def set_current(self, gcmd) -> None:
        """Set run current for live bringup debugging.

        RUN_CURRENT is in amps RMS, matching the printer.cfg convention. The
        value is applied immediately and kept in memory for the current Klipper
        session, but is not persisted to printer.cfg.
        """
        run_current = gcmd.get_float("RUN_CURRENT", minval=0.0, maxval=MAX_RUN_CURRENT_AMPS)
        if run_current <= 0.0:
            raise gcmd.error(f"FOCI {self.driver.name}: RUN_CURRENT must be above 0")

        run_ma = int(run_current * 1000.0 + 0.5)
        self.driver.protocol.set_current(run_ma)
        self.driver.settings.run_current = run_current

        gcmd.respond_info(
            f"FOCI {self.driver.name} run current set: run_current={run_current:.3f}A run_ma="
            f"{int(run_ma)}"
        )

    def set_velocity_feedforward(self, gcmd) -> None:
        """Set velocity feedforward gain for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        gain = gcmd.get_float(
            "GAIN",
            self.driver.settings.velocity_feedforward_gain,
            minval=0.0,
            maxval=8.0,
        )

        self.driver.protocol.set_velocity_feedforward(bool(enable), gain_to_permille(gain))
        self.driver.settings.velocity_feedforward = enable != 0
        self.driver.settings.velocity_feedforward_gain = gain

        gcmd.respond_info(
            f"FOCI {self.driver.name} velocity feedforward set: enable={int(enable)} gain={gain}"
        )

    def set_voltage_limit(self, gcmd) -> None:
        """Set PIDOUT_UQ_UD_LIMITS for live authority diagnostics.

        VOLTAGE_LIMIT is a raw TMC4671 PIDOUT count. This command is live-only:
        it changes the current Klipper session and does not persist config.
        """
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            minval=MIN_RAW_VOLTAGE_LIMIT,
            maxval=MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
        )

        self.driver.protocol.set_voltage_limit(voltage_limit)
        self.driver.settings.voltage_limit = voltage_limit

        gcmd.respond_info(
            f"FOCI {self.driver.name} voltage limit set: pidout_uq_ud_limit={int(voltage_limit)}"
        )

    def set_accel_feedforward(self, gcmd) -> None:
        """Set acceleration feedforward gains for live bringup debugging.

        ACCEL_GAIN and DECEL_GAIN are in permille. GAIN is a convenience alias
        that sets both when neither split gain is supplied.
        """
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        split_gain_supplied = (
            gcmd.get("ACCEL_GAIN", None) is not None or gcmd.get("DECEL_GAIN", None) is not None
        )
        alias_gain = (
            gcmd.get_int("GAIN", minval=0, maxval=65535)
            if gcmd.get("GAIN", None) is not None
            else None
        )
        if alias_gain is not None and not split_gain_supplied:
            default_accel_gain = alias_gain
            default_decel_gain = alias_gain
        else:
            default_accel_gain = self.driver.settings.accel_feedforward_accel_gain
            default_decel_gain = self.driver.settings.accel_feedforward_decel_gain
        accel_gain = gcmd.get_int("ACCEL_GAIN", default_accel_gain, minval=0, maxval=65535)
        decel_gain = gcmd.get_int("DECEL_GAIN", default_decel_gain, minval=0, maxval=65535)

        self.driver.protocol.set_accel_feedforward(
            enable=enable != 0,
            accel_gain=accel_gain,
            decel_gain=decel_gain,
        )
        self.driver.settings.accel_feedforward = enable != 0
        self.driver.settings.accel_feedforward_accel_gain = accel_gain
        self.driver.settings.accel_feedforward_decel_gain = decel_gain

        gcmd.respond_info(
            f"FOCI {self.driver.name} acceleration feedforward set: enable={int(enable)} "
            f"accel_gain={int(accel_gain)} decel_gain={int(decel_gain)}"
        )

    def _get_p_gain(self, gcmd, key: str) -> int:
        """Read a floating-point proportional gain and encode raw Q8.8."""
        value = gcmd.get_float(key, minval=0.0, maxval=PID_GAIN_MAX_RAW / 256.0)
        return min(PID_GAIN_MAX_RAW, int(value * 256.0 + 0.5))

    def _get_i_gain(self, gcmd, key: str) -> int:
        """Read a floating-point integral gain and encode raw Q4.12."""
        value = gcmd.get_float(key, minval=0.0, maxval=PID_GAIN_MAX_RAW / 4096.0)
        return min(PID_GAIN_MAX_RAW, int(value * 4096.0 + 0.5))

    def _get_filter_hz(self, gcmd, key: str, max_hz: int) -> int | None:
        """Read an optional filter cutoff parameter in Hz."""
        if gcmd.get(key, None) is None:
            return None
        value = gcmd.get_int(key, minval=0, maxval=max_hz)
        if value != 0 and value < FILTER_MIN_HZ:
            raise gcmd.error(f"{key} must be 0 (disabled) or {int(FILTER_MIN_HZ)}..{int(max_hz)}")
        return value
