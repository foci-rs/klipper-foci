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
