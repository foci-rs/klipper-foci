"""Diagnostic FOCI host workflows."""

from __future__ import annotations

from .passive import PassiveDiagnostics
from ..constants import MIN_OPERATIONAL_VOLTAGE_LIMIT


class DiagnosticsWorkflow:
    """Own advanced and expert FOCI diagnostic commands and responses."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.passive = PassiveDiagnostics(driver)
        self.current_torque_sample_details: dict[tuple[int, int, int, int], dict] = {}
        self.current_torque_sample_labels: dict[tuple[int, int, int, int], str] = {}

    def handle_current_step_result(self, params: dict) -> None:
        """Handle foci_current_step_result from firmware."""
        msg = (
            "FOCI %s current step: status=%d target=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.driver.name,
                params["status"],
                params["target"],
                params["torque_during"],
                params["torque_before"],
                params["torque_after"],
                params["flux_during"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_vector_step_result(self, params: dict) -> None:
        """Handle foci_current_vector_step_result from firmware."""
        msg = (
            "FOCI %s current vector step: status=%d"
            " torque_target=%d flux_target=%d"
            " actual_torque=%d actual_flux=%d"
            " before=%d after=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.driver.name,
                params["status"],
                params["torque_target"],
                params["flux_target"],
                params["torque_during"],
                params["flux_during"],
                params["torque_before"],
                params["torque_after"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_torque_sample_result(self, params: dict) -> None:
        """Handle foci_current_torque_sample_result from firmware."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        detail = self.current_torque_sample_details.pop(detail_key, {})
        label = self.current_torque_sample_labels.pop(
            detail_key, "current torque sample"
        )
        msg = (
            "FOCI %s %s: status=%d"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " pidin_target_torque=%d pidin_target_flux=%d"
            " pidout_target_torque=%d pidout_target_flux=%d"
            " pid_torque_target_monitor=%d"
            " torque_error=%d flux_error=%d"
            " torque_error_sum=%d flux_error_sum=%d"
            " uq_prelimit=%d ud_prelimit=%d"
            " ff_velocity=%d ff_torque=%d"
            " status_flags=0x%08x"
            % (
                self.driver.name,
                label,
                params["status"],
                params["target"],
                params.get("flux_target", 0),
                params["sample_delay_ms"],
                params["voltage_limit"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params.get("pidin_target_torque", 0),
                params.get("pidin_target_flux", 0),
                params.get("pidout_target_torque", 0),
                params.get("pidout_target_flux", 0),
                params.get("pid_torque_target_monitor", 0),
                detail.get("torque_error", 0),
                detail.get("flux_error", 0),
                detail.get("torque_error_sum", 0),
                detail.get("flux_error_sum", 0),
                detail.get("uq_prelimit", 0),
                detail.get("ud_prelimit", 0),
                detail.get("ff_velocity", 0),
                detail.get("ff_torque", 0),
                params.get("status_flags", 0),
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_torque_sample_detail_result(self, params: dict) -> None:
        """Cache split current torque sample details until the base reply arrives."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        self.current_torque_sample_details[detail_key] = params

    def handle_voltage_step_result(self, params: dict) -> None:
        """Handle foci_voltage_step_result from firmware."""
        msg = (
            "FOCI %s voltage step: status=%d"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " uux_sample=%d uwy_sample=%d"
            " pwm_ux_sample=%d pwm_wy_sample=%d"
            " pwm_sv_chop=0x%08x pwm_bbm=0x%08x pwm_maxcnt=%d"
            " phi_e_sample=%d phi_m_sample=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " status_flags=0x%08x"
            % (
                self.driver.name,
                params["status"],
                params["uq_ext"],
                params["ud_ext"],
                params["sample_delay_ms"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["uux_sample"],
                params["uwy_sample"],
                params["pwm_ux_sample"],
                params["pwm_wy_sample"],
                params["pwm_sv_chop"],
                params["pwm_bbm"],
                params["pwm_maxcnt"],
                params["phi_e_sample"],
                params["phi_m_sample"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params["status_flags"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_stepper_event(self, params: dict) -> None:
        return self.passive.handle_stepper_event(params)

    def handle_stepper_perf_event(self, params: dict) -> None:
        return self.passive.handle_stepper_perf_event(params)

    def step_position(self, gcmd) -> None:
        return self.passive.step_position(gcmd)

    def stepper_stats(self, gcmd) -> None:
        return self.passive.stepper_stats(gcmd)

    def dispatch_stats(self, gcmd) -> None:
        return self.passive.dispatch_stats(gcmd)

    def current_step_test(self, gcmd) -> None:
        """Run a bounded current-loop step diagnostic."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.driver.protocol.run_current_step_test(
            target=target,
            duration_ms=duration_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            "FOCI %s current-step requested: target=%d"
            " duration_ms=%d voltage_limit=%d"
            % (self.driver.name, target, duration_ms, voltage_limit)
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
            "FOCI %s current-vector-step requested:"
            " torque_target=%d flux_target=%d duration_ms=%d voltage_limit=%d"
            % (
                self.driver.name,
                torque_target,
                flux_target,
                duration_ms,
                voltage_limit,
            )
        )

    def current_torque_sample_test(self, gcmd) -> None:
        """Run a bounded torque pulse and sample it before the dwell floor."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 5, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        self.current_torque_sample_details.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )
        self.current_torque_sample_labels.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )

        self.driver.protocol.run_current_torque_sample_test(
            target=target,
            flux_target=flux_target,
            sample_delay_ms=sample_delay_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            "FOCI %s current-torque-sample requested:"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d"
            % (
                self.driver.name,
                target,
                flux_target,
                sample_delay_ms,
                voltage_limit,
            )
        )

    def position_torque_offset_test(self, gcmd) -> None:
        """Run a bounded torque-offset sample while staying in position mode."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        detail_key = (target, 0, sample_delay_ms, voltage_limit)
        self.current_torque_sample_details.pop(detail_key, None)
        self.current_torque_sample_labels[detail_key] = "position torque offset sample"

        self.driver.protocol.run_position_torque_offset_sample_test(
            target=target,
            sample_delay_ms=sample_delay_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            "FOCI %s position-torque-offset requested:"
            " target=%d sample_delay_ms=%d voltage_limit=%d"
            % (self.driver.name, target, sample_delay_ms, voltage_limit)
        )

    def voltage_step_test(self, gcmd) -> None:
        """Run a bounded open-loop voltage-vector pulse and sample it."""
        uq_ext = gcmd.get_int("UQ", minval=-1024, maxval=1024)
        ud_ext = gcmd.get_int("UD", 0, minval=-1024, maxval=1024)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)

        self.driver.protocol.run_voltage_step_test(
            uq_ext=uq_ext,
            ud_ext=ud_ext,
            sample_delay_ms=sample_delay_ms,
        )

        gcmd.respond_info(
            "FOCI %s voltage-step requested:"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d"
            % (self.driver.name, uq_ext, ud_ext, sample_delay_ms)
        )
