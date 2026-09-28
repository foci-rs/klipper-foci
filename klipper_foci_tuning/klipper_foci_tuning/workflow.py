"""Rare FOCI fine-tuning setters, split out of ControlsWorkflow."""

from __future__ import annotations


class TuningWorkflow:
    """Rare, expert-only FOCI tuning setters."""

    def __init__(self, driver) -> None:
        self.driver = driver

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
