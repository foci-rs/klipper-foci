"""Semantic protocol facade for klipper-foci workflows."""

from __future__ import annotations

from . import queries
from .commands import FociMcuCommands


class FociProtocol:
    """Host protocol facade for low-level FOCI MCU communication."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.commands = FociMcuCommands()

    def bind_mcu(self, mcu, oid: int) -> None:
        """Bind MCU commands and response handlers for one FOCI driver."""
        self.commands.bind(self.driver, mcu, oid)

    def set_current(self, run_ma: int) -> None:
        self.commands.set_current.send([self.driver.oid, run_ma])

    def set_voltage_limit(self, voltage_limit: int) -> None:
        self.commands.set_voltage_limit.send([self.driver.oid, voltage_limit])

    def query_adc_vm_offset(self) -> int:
        response = self.commands.query_adc_vm_offset.send([self.driver.oid])
        if response is None:
            raise self.driver.printer.command_error(
                "FOCI cached ADC_VM offset query returned no data"
            )
        try:
            status = int(response["status"])
            sample_count = int(response["sample_count"])
            offset_raw = int(response["offset_raw"])
        except (KeyError, TypeError, ValueError) as err:
            raise self.driver.printer.command_error(
                "FOCI cached ADC_VM offset query returned incomplete data"
            ) from err
        if status != 0:
            raise self.driver.printer.command_error(
                f"FOCI cached ADC_VM offset query failed with status={int(status)}"
            )
        if sample_count <= 0:
            raise self.driver.printer.command_error(
                "FOCI cached ADC_VM offset query returned no samples"
            )
        self.driver.state.adc_vm_offset_raw = offset_raw
        return offset_raw

    def set_motion_scale(
        self, *, channel: int, encoder_ppr: int, planner_steps_per_rev: int
    ) -> None:
        self.commands.set_motion_scale.send(
            [self.driver.oid, channel, encoder_ppr, planner_steps_per_rev]
        )

    def set_encoder_direction(self, channel: int, encoder_reversed: bool) -> None:
        self.commands.set_encoder_dir.send([self.driver.oid, channel, int(encoder_reversed)])

    def set_pid_gains(
        self,
        flux_p: int,
        flux_i: int,
        torque_p: int,
        torque_i: int,
    ) -> None:
        self.commands.set_pid_gains.send([self.driver.oid, flux_p, flux_i, torque_p, torque_i])

    def set_velocity_filter(self, filter_hz: int) -> None:
        self.commands.set_velocity_filter.send([self.driver.oid, filter_hz])

    def set_torque_filter(self, filter_hz: int) -> None:
        self.commands.set_torque_filter.send([self.driver.oid, filter_hz])

    def set_position_filter(self, filter_hz: int) -> None:
        self.commands.set_position_filter.send([self.driver.oid, filter_hz])

    def set_flux_filter(self, filter_hz: int) -> None:
        self.commands.set_flux_filter.send([self.driver.oid, filter_hz])

    def set_position_gains(
        self,
        position_p: int,
        position_i: int,
        velocity_p: int,
        velocity_i: int,
    ) -> None:
        self.commands.set_position_gains.send(
            [self.driver.oid, position_p, position_i, velocity_p, velocity_i]
        )

    def set_velocity_feedforward(self, enable: bool, gain_permille: int) -> None:
        self.commands.set_velocity_feedforward.send([self.driver.oid, int(enable), gain_permille])

    def set_velocity_limit(self, velocity_limit: int) -> None:
        self.commands.set_velocity_limit.send([self.driver.oid, velocity_limit])

    def set_velocity_transient_feedforward(
        self,
        *,
        enable: bool,
        lead_time_us: int,
        gain: int,
        max_offset: int,
        rate_hz: int,
    ) -> None:
        self.commands.set_velocity_transient_feedforward.send(
            [
                self.driver.oid,
                int(enable),
                lead_time_us,
                gain,
                max_offset,
                rate_hz,
            ]
        )

    def set_accel_feedforward(
        self,
        *,
        enable: bool,
        accel_gain: int,
        decel_gain: int,
    ) -> None:
        self.commands.set_accel_feedforward.send(
            [self.driver.oid, int(enable), accel_gain, decel_gain]
        )

    def set_decoupling_feedforward(
        self,
        *,
        enable: bool,
        r_int: int,
        l_int: int,
        pole_pairs: int,
        position_units_per_rev: int,
        f_pwm_hz: int,
        max_offset: int,
    ) -> None:
        self.commands.set_decoupling_feedforward.send(
            [
                self.driver.oid,
                int(enable),
                r_int,
                l_int,
                pole_pairs,
                position_units_per_rev,
                f_pwm_hz,
                max_offset,
            ]
        )

    def set_position_lead(
        self,
        *,
        enable: bool,
        gain: int,
        max_counts: int,
    ) -> None:
        self.commands.set_position_lead.send([self.driver.oid, int(enable), gain, max_counts])

    def set_phase_advance(
        self,
        *,
        enable: bool,
        gain_ppm: int,
        max_counts: int,
        deadband: int,
    ) -> None:
        self.commands.set_phase_advance.send(
            [self.driver.oid, int(enable), gain_ppm, max_counts, deadband]
        )

    def get_step_position(self) -> dict:
        return queries.get_step_position(self)

    def get_stepper_stats(self) -> tuple[dict, dict, dict, dict]:
        return queries.get_stepper_stats(self)

    def get_stepper_perf_stats(self, *, clear: bool) -> dict:
        return queries.get_stepper_perf_stats(self, clear=clear)

    def dev_tmc_write_register(self, *, addr: int, value: int) -> None:
        if self.driver.oid is None or self.commands.dev_tmc_write_register is None:
            raise self.driver.printer.command_error("FOCI_TMC_WRITE_REGISTER requires dev firmware")
        self.commands.dev_tmc_write_register.send([self.driver.oid, addr, value])

    def dev_tmc_read_register(self, *, addr: int) -> dict:
        if self.driver.oid is None or self.commands.dev_tmc_read_register is None:
            raise self.driver.printer.command_error("FOCI_TMC_READ_REGISTER requires dev firmware")
        response = self.commands.dev_tmc_read_register.send([self.driver.oid, addr])
        if response is None:
            raise self.driver.printer.command_error("FOCI_TMC_READ_REGISTER query returned no data")
        return response

    def run_current_step_test(
        self,
        *,
        axis: int,
        target: int,
        duration_ms: int,
        voltage_limit: int,
    ) -> None:
        self.commands.current_step_test.send(
            [self.driver.oid, axis, target, duration_ms, voltage_limit]
        )

    def run_current_vector_step_test(
        self,
        *,
        torque_target: int,
        flux_target: int,
        duration_ms: int,
        voltage_limit: int,
    ) -> None:
        self.commands.current_vector_step_test.send(
            [
                self.driver.oid,
                torque_target,
                flux_target,
                duration_ms,
                voltage_limit,
            ]
        )

    def run_current_torque_sample_test(
        self,
        *,
        target: int,
        flux_target: int,
        sample_delay_ms: int,
        voltage_limit: int,
    ) -> None:
        self.commands.current_torque_sample_test.send(
            [
                self.driver.oid,
                target,
                flux_target,
                sample_delay_ms,
                voltage_limit,
            ]
        )

    def run_position_torque_offset_sample_test(
        self,
        *,
        target: int,
        sample_delay_ms: int,
        voltage_limit: int,
    ) -> None:
        self.commands.position_torque_offset_sample_test.send(
            [self.driver.oid, target, sample_delay_ms, voltage_limit]
        )

    def run_voltage_step_test(
        self,
        *,
        uq_ext: int,
        ud_ext: int,
        sample_delay_ms: int,
    ) -> None:
        self.commands.voltage_step_test.send([self.driver.oid, uq_ext, ud_ext, sample_delay_ms])

    def run_resistance_test(self, *, detail: int = 0) -> None:
        self.commands.resistance_test.send([self.driver.oid, detail])

    def run_velocity_limit_latch_test(self, *, channel: int) -> None:
        """Run the trace-only velocity-output-limit persistence diagnostic."""
        command = self.commands.velocity_limit_latch_test
        if command is None:
            raise self.driver.printer.command_error(
                "FOCI_VELOCITY_LIMIT_LATCH_TEST requires trace firmware"
            )
        command.send([self.driver.oid, channel])

    def configure_startup(
        self,
        *,
        current_ma: int,
        voltage_limit: int,
        channel: int,
        encoder_ppr: int,
        planner_steps_per_rev: int,
        encoder_reversed: bool,
        pid_gains: tuple[int, int, int, int] | None,
        filter_hz: dict[str, int | None],
        position_gains: tuple[int, int, int, int] | None,
        velocity_feedforward: tuple[bool, int],
        velocity_limit: int | None,
    ) -> None:
        """Apply connect-time firmware configuration in the existing order."""
        self.set_current(current_ma)
        self.set_voltage_limit(voltage_limit)
        self.query_adc_vm_offset()
        self.set_motion_scale(
            channel=channel,
            encoder_ppr=encoder_ppr,
            planner_steps_per_rev=planner_steps_per_rev,
        )
        self.set_encoder_direction(channel, encoder_reversed)
        if pid_gains is not None:
            self.set_pid_gains(*pid_gains)
        if filter_hz.get("velocity") is not None:
            self.set_velocity_filter(filter_hz["velocity"])
        if filter_hz.get("torque") is not None:
            self.set_torque_filter(filter_hz["torque"])
        if filter_hz.get("position") is not None:
            self.set_position_filter(filter_hz["position"])
        if filter_hz.get("flux") is not None:
            self.set_flux_filter(filter_hz["flux"])
        if position_gains is not None:
            self.set_position_gains(*position_gains)
        enable_feedforward, gain_permille = velocity_feedforward
        if enable_feedforward:
            self.set_velocity_feedforward(True, gain_permille)
        if velocity_limit is not None:
            self.set_velocity_limit(velocity_limit)

    def set_auto_calibrate_on_enable(self, allowed: bool) -> None:
        self.commands.set_auto_calibrate_on_enable.send([self.driver.oid, int(allowed)])

    def preload_active_gains(self, gains: dict[str, int | None], voltage_limit: int) -> None:
        self.set_voltage_limit(voltage_limit)
        self.set_pid_gains(
            gains["flux_p"],
            gains["flux_i"],
            gains["torque_p"],
            gains["torque_i"],
        )
        if gains.get("velocity_p") is not None:
            self.set_position_gains(
                gains["position_p"],
                gains["position_i"],
                gains["velocity_p"],
                gains["velocity_i"],
            )
        if gains.get("velocity_limit"):
            self.set_velocity_limit(gains["velocity_limit"])
        for filter_name, setter in (
            ("velocity", self.set_velocity_filter),
            ("torque", self.set_torque_filter),
            ("position", self.set_position_filter),
            ("flux", self.set_flux_filter),
        ):
            hz = gains.get(f"{filter_name}_filter_hz")
            if hz is not None:
                setter(hz)

    def run_calibration(self) -> None:
        self.commands.calibrate.send([self.driver.oid])

    def run_commission(self, profile_code: int) -> None:
        self.commands.commission.send([self.driver.oid, profile_code])

    def run_tune(
        self,
        *,
        action: int = 0,
        profile_code: int,
        mode_code: int,
        inner_lambda: int,
        theta_e: int,
        current_ringing: int,
        current_bw: int,
        inner_warning_flags: int,
        requested_velocity_mrev_s: int,
        machine_velocity_ceiling_mrev_s: int,
        requested_velocity_source: int,
        max_stroke_travel_mrev: int,
        settle_travel_reserve_mrev: int,
        negative_position_headroom_mrev: int,
        positive_position_headroom_mrev: int,
        max_duration_ms: int,
    ) -> None:
        self.commands.tune.send(
            [
                self.driver.oid,
                action,
                profile_code,
                mode_code,
                inner_lambda,
                theta_e,
                current_ringing,
                current_bw,
                inner_warning_flags,
                requested_velocity_mrev_s,
                machine_velocity_ceiling_mrev_s,
                requested_velocity_source,
                max_stroke_travel_mrev,
                settle_travel_reserve_mrev,
                negative_position_headroom_mrev,
                positive_position_headroom_mrev,
                max_duration_ms,
            ]
        )

    def run_selftest(self) -> None:
        self.commands.selftest.send([self.driver.oid])

    def dump_registers(self) -> None:
        self.commands.dump_registers.send([self.driver.oid])
