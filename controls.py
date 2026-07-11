"""Live controller control commands for FOCI host workflows."""

from __future__ import annotations

from .config import CURRENT_FILTER_MAX_HZ, FILTER_MIN_HZ, MOTION_FILTER_MAX_HZ
from .constants import MAX_DIAGNOSTIC_VOLTAGE_LIMIT, MIN_RAW_VOLTAGE_LIMIT


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
        velocity_p = self._get_outer_gain(gcmd, "VELOCITY_P")
        velocity_i = self._get_outer_gain(gcmd, "VELOCITY_I")
        position_p = self._get_outer_gain(gcmd, "POSITION_P")
        position_i = self._get_outer_gain(gcmd, "POSITION_I")

        self.driver.protocol.set_position_gains(
            position_p,
            position_i,
            velocity_p,
            velocity_i,
        )

        gcmd.respond_info(
            "FOCI %s debug gain update requested: vel_p=%d/256 vel_i=%d/256"
            " pos_p=%d/256 pos_i=%d/256"
            % (self.driver.name, velocity_p, velocity_i, position_p, position_i)
        )

    def set_inner_gains(self, gcmd) -> None:
        """Set inner current-loop gains for live bringup debugging.

        Parameters are raw TMC4671 register values. P gains are Q8.8
        numerators. Current I gains are also Q8.8 while
        CONFIG_ADVANCED_PI_REPRESENT remains at its default 0; in advanced PI
        mode their effective zero factor is raw/65536 per PWM sample. The
        command is asynchronous and does not update host applied-state caches
        because firmware application is not confirmed.
        """
        flux_p = gcmd.get_int("FLUX_P", minval=0, maxval=65535)
        flux_i = gcmd.get_int("FLUX_I", minval=0, maxval=65535)
        torque_p = gcmd.get_int("TORQUE_P", minval=0, maxval=65535)
        torque_i = gcmd.get_int("TORQUE_I", minval=0, maxval=65535)

        self.driver.protocol.set_pid_gains(flux_p, flux_i, torque_p, torque_i)

        gcmd.respond_info(
            "FOCI %s inner gain update requested: flux_p=%d/256"
            " flux_i=%d(q8.8=%.3f zero=%d/65536)"
            " torque_p=%d/256 torque_i=%d(q8.8=%.3f zero=%d/65536)"
            % (
                self.driver.name,
                flux_p,
                flux_i,
                flux_i * 2**-8,
                flux_i,
                torque_p,
                torque_i,
                torque_i * 2**-8,
                torque_i,
            )
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
        applied = []

        for param, label, attr, max_hz, setter in filters:
            value = self._get_filter_hz(gcmd, param, max_hz)
            if value is None:
                continue
            setter(value)
            setattr(self.driver.settings, attr, value)
            if self.driver.state.active_gains is not None:
                self.driver.state.active_gains[attr] = value
            applied.append("%s=%dHz" % (label, value))

        if not applied:
            raise gcmd.error(
                "FOCI %s filters: specify at least one of "
                "VELOCITY_HZ, TORQUE_HZ, POSITION_HZ, FLUX_HZ" % self.driver.name
            )

        gcmd.respond_info(
            "FOCI %s filters set: %s" % (self.driver.name, " ".join(applied))
        )

    def set_current(self, gcmd) -> None:
        """Set run current for live bringup debugging.

        RUN_CURRENT is in amps RMS, matching the printer.cfg convention. The
        value is applied immediately and kept in memory for the current Klipper
        session, but is not persisted to printer.cfg.
        """
        run_current = gcmd.get_float("RUN_CURRENT", minval=0.0, maxval=5.0)
        if run_current <= 0.0:
            raise gcmd.error("FOCI %s: RUN_CURRENT must be above 0" % self.driver.name)

        run_ma = int(run_current * 1000.0 + 0.5)
        self.driver.protocol.set_current(run_ma)
        self.driver.settings.run_current = run_current

        gcmd.respond_info(
            "FOCI %s run current set: run_current=%.3fA run_ma=%d"
            % (self.driver.name, run_current, run_ma)
        )

    def tmc_write_register(self, gcmd) -> None:
        """Write a raw TMC4671 register through dev firmware."""
        addr = gcmd.get_int("ADDR", minval=0, maxval=0xFF)
        value = gcmd.get_int("VALUE", minval=0, maxval=0xFFFFFFFF)
        self.driver.protocol.dev_tmc_write_register(addr=addr, value=value)
        gcmd.respond_info(
            "FOCI_TMC_WRITE_REGISTER %s: addr=0x%02x value=0x%08x"
            % (self.driver.stepper_name, addr, value)
        )

    def set_velocity_feedforward(self, gcmd) -> None:
        """Set velocity feedforward multiplier for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        multiplier = gcmd.get_int(
            "MULTIPLIER",
            self.driver.settings.velocity_feedforward_multiplier,
            minval=0,
            maxval=65535,
        )

        self.driver.protocol.set_velocity_feedforward(bool(enable), multiplier)
        self.driver.settings.velocity_feedforward = enable != 0
        self.driver.settings.velocity_feedforward_multiplier = multiplier

        gcmd.respond_info(
            "FOCI %s velocity feedforward set: enable=%d multiplier=%d"
            % (self.driver.name, enable, multiplier)
        )

    def set_velocity_transient_feedforward(self, gcmd) -> None:
        """Set live-only command-acceleration velocity feedforward."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        lead_time_us = gcmd.get_int(
            "LEAD_TIME_US",
            self.driver.settings.velocity_transient_lead_time_us,
            minval=0,
            maxval=65535,
        )
        gain = gcmd.get_int(
            "GAIN",
            self.driver.settings.velocity_transient_gain,
            minval=0,
            maxval=65535,
        )
        max_offset = gcmd.get_int(
            "MAX_OFFSET",
            self.driver.settings.velocity_transient_max_offset,
            minval=0,
            maxval=32767,
        )
        rate_hz = gcmd.get_int(
            "RATE_HZ",
            self.driver.settings.velocity_transient_rate_hz,
            minval=1000,
            maxval=10000,
        )

        self.driver.protocol.set_velocity_transient_feedforward(
            enable=enable != 0,
            lead_time_us=lead_time_us,
            gain=gain,
            max_offset=max_offset,
            rate_hz=rate_hz,
        )
        self.driver.settings.velocity_transient_feedforward = enable != 0
        self.driver.settings.velocity_transient_lead_time_us = lead_time_us
        self.driver.settings.velocity_transient_gain = gain
        self.driver.settings.velocity_transient_max_offset = max_offset
        self.driver.settings.velocity_transient_rate_hz = rate_hz

        gcmd.respond_info(
            "FOCI %s velocity transient feedforward set: enable=%d"
            " lead_time_us=%d gain=%d max_offset=%d rate_hz=%d"
            % (
                self.driver.name,
                enable,
                lead_time_us,
                gain,
                max_offset,
                rate_hz,
            )
        )

    def set_accel_feedforward(self, gcmd) -> None:
        """Set acceleration feedforward gains for live bringup debugging.

        ACCEL_GAIN and DECEL_GAIN are in permille. GAIN is a convenience alias
        that sets both when neither split gain is supplied.
        """
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        split_gain_supplied = (
            gcmd.get("ACCEL_GAIN", None) is not None
            or gcmd.get("DECEL_GAIN", None) is not None
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
        accel_gain = gcmd.get_int(
            "ACCEL_GAIN",
            default_accel_gain,
            minval=0,
            maxval=65535,
        )
        decel_gain = gcmd.get_int(
            "DECEL_GAIN",
            default_decel_gain,
            minval=0,
            maxval=65535,
        )

        self.driver.protocol.set_accel_feedforward(
            enable=enable != 0,
            accel_gain=accel_gain,
            decel_gain=decel_gain,
        )
        self.driver.settings.accel_feedforward = enable != 0
        self.driver.settings.accel_feedforward_accel_gain = accel_gain
        self.driver.settings.accel_feedforward_decel_gain = decel_gain

        gcmd.respond_info(
            "FOCI %s acceleration feedforward set: enable=%d"
            " accel_gain=%d decel_gain=%d"
            % (self.driver.name, enable, accel_gain, decel_gain)
        )

    def set_decoupling_feedforward(self, gcmd) -> None:
        """Set bounded q/d decoupling proxy feedforward for live debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        r_int = gcmd.get_int(
            "R_INT",
            self.driver.settings.decoupling_r_int,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        l_int = gcmd.get_int(
            "L_INT",
            self.driver.settings.decoupling_l_int,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        pole_pairs = gcmd.get_int(
            "POLE_PAIRS",
            self.driver.settings.decoupling_pole_pairs,
            minval=1,
            maxval=65535,
        )
        position_units_per_rev = gcmd.get_int(
            "POSITION_UNITS_PER_REV",
            self.driver.settings.decoupling_position_units_per_rev,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        f_pwm_hz = gcmd.get_int(
            "F_PWM_HZ",
            self.driver.settings.decoupling_f_pwm_hz,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        max_offset = gcmd.get_int(
            "MAX_OFFSET",
            self.driver.settings.decoupling_max_offset,
            minval=0,
            maxval=32767,
        )

        self.driver.protocol.set_decoupling_feedforward(
            enable=enable != 0,
            r_int=r_int,
            l_int=l_int,
            pole_pairs=pole_pairs,
            position_units_per_rev=position_units_per_rev,
            f_pwm_hz=f_pwm_hz,
            max_offset=max_offset,
        )
        self.driver.settings.decoupling_feedforward = enable != 0
        self.driver.settings.decoupling_r_int = r_int
        self.driver.settings.decoupling_l_int = l_int
        self.driver.settings.decoupling_pole_pairs = pole_pairs
        self.driver.settings.decoupling_position_units_per_rev = position_units_per_rev
        self.driver.settings.decoupling_f_pwm_hz = f_pwm_hz
        self.driver.settings.decoupling_max_offset = max_offset

        gcmd.respond_info(
            "FOCI %s decoupling feedforward set: enable=%d"
            " r_int=%d l_int=%d pole_pairs=%d position_units_per_rev=%d"
            " f_pwm_hz=%d max_offset=%d"
            % (
                self.driver.name,
                enable,
                r_int,
                l_int,
                pole_pairs,
                position_units_per_rev,
                f_pwm_hz,
                max_offset,
            )
        )

    def set_position_lead(self, gcmd) -> None:
        """Set bounded position-target lead for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        gain = gcmd.get_int(
            "GAIN",
            self.driver.settings.position_lead_gain,
            minval=0,
            maxval=65535,
        )
        max_counts = gcmd.get_int(
            "MAX_COUNTS",
            self.driver.settings.position_lead_max_counts,
            minval=0,
            maxval=200,
        )

        self.driver.protocol.set_position_lead(
            enable=enable != 0,
            gain=gain,
            max_counts=max_counts,
        )
        self.driver.settings.position_lead = enable != 0
        self.driver.settings.position_lead_gain = gain
        self.driver.settings.position_lead_max_counts = max_counts

        gcmd.respond_info(
            "FOCI %s position lead set: enable=%d gain=%d max_counts=%d"
            % (self.driver.name, enable, gain, max_counts)
        )

    def set_phase_advance(self, gcmd) -> None:
        """Set bounded commutation phase advance for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        gain_ppm = gcmd.get_int(
            "GAIN_PPM",
            self.driver.settings.phase_advance_gain_ppm,
            minval=-2_000_000,
            maxval=2_000_000,
        )
        max_counts = gcmd.get_int(
            "MAX_COUNTS",
            self.driver.settings.phase_advance_max_counts,
            minval=0,
            maxval=512,
        )
        deadband = gcmd.get_int(
            "DEADBAND",
            self.driver.settings.phase_advance_deadband,
            minval=0,
            maxval=65535,
        )

        self.driver.protocol.set_phase_advance(
            enable=enable != 0,
            gain_ppm=gain_ppm,
            max_counts=max_counts,
            deadband=deadband,
        )
        self.driver.settings.phase_advance = enable != 0
        self.driver.settings.phase_advance_gain_ppm = gain_ppm
        self.driver.settings.phase_advance_max_counts = max_counts
        self.driver.settings.phase_advance_deadband = deadband

        gcmd.respond_info(
            "FOCI %s phase advance set: enable=%d gain_ppm=%d"
            " max_counts=%d deadband=%d"
            % (self.driver.name, enable, gain_ppm, max_counts, deadband)
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
            "FOCI %s voltage limit set: pidout_uq_ud_limit=%d"
            % (self.driver.name, voltage_limit)
        )

    def _get_outer_gain(self, gcmd, key: str) -> int:
        """Read a floating-point gain parameter and convert it to raw Q8.8."""
        value = gcmd.get_float(key, minval=0.0, maxval=32767.0 / 256.0)
        return min(32767, int(value * 256.0 + 0.5))

    def _get_filter_hz(self, gcmd, key: str, max_hz: int) -> int | None:
        """Read an optional filter cutoff parameter in Hz."""
        if gcmd.get(key, None) is None:
            return None
        value = gcmd.get_int(key, minval=0, maxval=max_hz)
        if value != 0 and value < FILTER_MIN_HZ:
            raise gcmd.error(
                "%s must be 0 (disabled) or %d..%d" % (key, FILTER_MIN_HZ, max_hz)
            )
        return value
