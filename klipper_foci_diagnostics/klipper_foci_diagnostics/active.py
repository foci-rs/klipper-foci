"""Bounded-actuation FOCI diagnostic G-code commands."""

from __future__ import annotations

from klipper_foci.constants import MIN_OPERATIONAL_VOLTAGE_LIMIT
from klipper_foci.diagnostics.active import CURRENT_STEP_AXIS_CODES, MAX_CURRENT_SAMPLE_DELAY_MS


class DiagnosticsActive:
    """FOCI diagnostics that deliberately excite hardware."""

    def __init__(self, driver) -> None:
        self.driver = driver

    def current_step_test(self, gcmd) -> None:
        """Run a bounded current-loop step diagnostic."""
        axis_name = gcmd.get("AXIS", "torque").lower()
        if axis_name not in CURRENT_STEP_AXIS_CODES:
            raise gcmd.error("AXIS must be torque or flux")
        axis = CURRENT_STEP_AXIS_CODES[axis_name]
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.driver.protocol.run_current_step_test(
            axis=axis,
            target=target,
            duration_ms=duration_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            f"FOCI {self.driver.name} current-step requested: axis={axis_name} target="
            f"{int(target)} duration_ms={int(duration_ms)} voltage_limit={int(voltage_limit)}"
        )

    def current_vector_step_test(self, gcmd) -> None:
        """Run a bounded current-vector step diagnostic."""
        torque_target = gcmd.get_int("TORQUE_TARGET", 0, minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.driver.protocol.run_current_vector_step_test(
            torque_target=torque_target,
            flux_target=flux_target,
            duration_ms=duration_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            f"FOCI {self.driver.name} current-vector-step requested: torque_target="
            f"{int(torque_target)} flux_target={int(flux_target)} duration_ms="
            f"{int(duration_ms)} voltage_limit={int(voltage_limit)}"
        )

    def current_torque_sample_test(self, gcmd) -> None:
        """Run a bounded torque pulse and sample it before the dwell floor."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int(
            "SAMPLE_DELAY_MS", 5, minval=1, maxval=MAX_CURRENT_SAMPLE_DELAY_MS
        )
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        self.driver.protocol.run_current_torque_sample_test(
            target=target,
            flux_target=flux_target,
            sample_delay_ms=sample_delay_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            f"FOCI {self.driver.name} current-torque-sample requested: target={int(target)} "
            f"flux_target={int(flux_target)} sample_delay_ms={int(sample_delay_ms)} "
            f"voltage_limit={int(voltage_limit)}"
        )

    def position_torque_offset_test(self, gcmd) -> None:
        """Run a bounded torque-offset sample while staying in position mode."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int(
            "SAMPLE_DELAY_MS", 2, minval=1, maxval=MAX_CURRENT_SAMPLE_DELAY_MS
        )
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        self.driver.protocol.run_position_torque_offset_sample_test(
            target=target,
            sample_delay_ms=sample_delay_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            f"FOCI {self.driver.name} position-torque-offset requested: target={int(target)} "
            f"sample_delay_ms={int(sample_delay_ms)} voltage_limit={int(voltage_limit)}"
        )

    def voltage_step_test(self, gcmd) -> None:
        """Run a bounded open-loop voltage-vector pulse and sample it."""
        uq_ext = gcmd.get_int("UQ", minval=-1024, maxval=1024)
        ud_ext = gcmd.get_int("UD", 0, minval=-1024, maxval=1024)
        sample_delay_ms = gcmd.get_int(
            "SAMPLE_DELAY_MS", 2, minval=1, maxval=MAX_CURRENT_SAMPLE_DELAY_MS
        )

        self.driver.protocol.run_voltage_step_test(
            uq_ext=uq_ext,
            ud_ext=ud_ext,
            sample_delay_ms=sample_delay_ms,
        )

        gcmd.respond_info(
            f"FOCI {self.driver.name} voltage-step requested: uq_ext={int(uq_ext)} ud_ext="
            f"{int(ud_ext)} sample_delay_ms={int(sample_delay_ms)}"
        )

    def resistance_test(self, gcmd) -> None:
        """Run the shared firmware resistance-identification diagnostic.

        Triggers the same firmware engine used by FOCI_SETUP's
        resistance-identification phase. Results stream back via the
        foci_resistance_profile/run/axis replies, which are displayed
        as reported with no host-side fitting or pass/fail evaluation.
        """
        detail = gcmd.get_int("DETAIL", 0, minval=0, maxval=255)

        self.driver.protocol.run_resistance_test(detail=detail)

        gcmd.respond_info(
            f"FOCI {self.driver.name} resistance-test requested: detail={int(detail)}"
        )
