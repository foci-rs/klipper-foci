"""Rare FOCI fine-tuning setters, split out of ControlsWorkflow."""

from __future__ import annotations

from klipper_foci.constants import MAX_DIAGNOSTIC_VOLTAGE_LIMIT, MIN_RAW_VOLTAGE_LIMIT


class TuningWorkflow:
    """Rare, expert-only FOCI tuning setters."""

    def __init__(self, driver) -> None:
        self.driver = driver

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
            f"FOCI {self.driver.name} velocity transient feedforward set: enable={int(enable)} "
            f"lead_time_us={int(lead_time_us)} gain={int(gain)} max_offset={int(max_offset)} "
            f"rate_hz={int(rate_hz)}"
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
            f"FOCI {self.driver.name} acceleration feedforward set: enable={int(enable)} "
            f"accel_gain={int(accel_gain)} decel_gain={int(decel_gain)}"
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
            f"FOCI {self.driver.name} decoupling feedforward set: enable={int(enable)} r_int="
            f"{int(r_int)} l_int={int(l_int)} pole_pairs={int(pole_pairs)} "
            f"position_units_per_rev={int(position_units_per_rev)} f_pwm_hz={int(f_pwm_hz)} "
            f"max_offset={int(max_offset)}"
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
            f"FOCI {self.driver.name} position lead set: enable={int(enable)} gain={int(gain)} "
            f"max_counts={int(max_counts)}"
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
            f"FOCI {self.driver.name} phase advance set: enable={int(enable)} gain_ppm="
            f"{int(gain_ppm)} max_counts={int(max_counts)} deadband={int(deadband)}"
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
