"""Active FOCI diagnostic commands and response handlers."""

from __future__ import annotations

import logging

from ..commissioning import (
    CURRENT_LOOP_FAILURE_REASON_NAMES,
    format_commission_error_detail_name,
)
from ..constants import MIN_OPERATIONAL_VOLTAGE_LIMIT
from ..report import report_detail

log = logging.getLogger(__name__)

CURRENT_STEP_AXIS_CODES = {
    "torque": 0,
    "flux": 1,
}
MAX_CURRENT_SAMPLE_DELAY_MS = 200


class ActiveDiagnostics:
    """Own FOCI diagnostics that deliberately excite hardware."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.current_torque_sample_details: dict[tuple[int, int, int, int], dict] = {}
        self.current_torque_sample_labels: dict[tuple[int, int, int, int], str] = {}
        # Transient per-driver cache of the commission-stream resistance
        # replies (foci_resistance_run + the two foci_resistance_axis
        # replies), keyed by oid. Populated by handle_resistance_run and
        # handle_resistance_axis below; folded into the commission result
        # dict on commission success by CommissioningWorkflow.commission()
        # via pop_resistance_cache(), which only returns a non-empty dict
        # when all three replies (run, axis0, axis1) are present — a
        # partial set folds in nothing, so persist_commission_results'
        # presence-gated resistance block either persists a complete set
        # of identified_r_* keys or none at all. The cache entry for an
        # oid is unconditionally cleared at every commission exit
        # (success via pop_resistance_cache, failure/timeout via
        # clear_resistance_cache), so a failed or partial run can never
        # leak stale values into a later commission's fold.
        # A standalone FOCI_RESISTANCE_TEST run populates this cache too
        # and leaves no persisted trace by itself (nothing folds it in
        # without a commission completing afterward). But a standalone
        # run's full entry could otherwise pre-populate a later
        # commission's cache: if that commission then delivered only a
        # partial set of replies, the received axis would overwrite its
        # slot while the stale standalone axis lingered in the other,
        # making the all-or-nothing pop_resistance_cache see a complete
        # but mixed-origin entry. CommissioningWorkflow.commission()
        # guards against this by clearing the per-oid cache at the start
        # of every commission run, before its own replies can arrive.
        self.resistance_cache: dict[int, dict] = {}
        self.inductance_cache: dict[int, dict] = {}
        self._last_inductance_evidence: dict[int, dict] = {}
        self.current_loop_cache: dict[int, dict] = {}
        self.last_current_loop_run: dict[int, dict] = {}
        self.last_current_loop_hold: dict[int, dict] = {}
        self.last_closed_loop_activation: dict[int, dict] = {}
        self._last_current_loop_samples: dict[int, dict[str, list[dict]]] = {}
        self.last_encoder_alignment: dict[int, dict] = {}
        self.adc_residuals: dict[int, list[dict]] = {}
        self.current_step_pending_axis: str | None = None

    def handle_current_step_result(self, params: dict) -> None:
        """Handle foci_current_step_result from firmware."""
        axis = self.current_step_pending_axis or "torque"
        self.current_step_pending_axis = None
        msg = (
            f"FOCI {self.driver.name} current step: axis={axis} status={int(params['status'])} "
            f"target={int(params['target'])} actual={int(params['torque_during'])} before="
            f"{int(params['torque_before'])} after={int(params['torque_after'])} flux="
            f"{int(params['flux_during'])} iq={int(params['iq_during'])} id="
            f"{int(params['id_during'])} uq_limited={int(params['uq_limited'])} ud_limited="
            f"{int(params['ud_limited'])} enc_before={int(params['encoder_before'])} enc_after="
            f"{int(params['encoder_after'])} enc_delta={int(params['encoder_delta'])} adc_vm_raw="
            f"{int(params['adc_vm_raw'])}"
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_vector_step_result(self, params: dict) -> None:
        """Handle foci_current_vector_step_result from firmware."""
        msg = (
            f"FOCI {self.driver.name} current vector step: status={int(params['status'])} "
            f"torque_target={int(params['torque_target'])} flux_target={int(params['flux_target'])}"
            f" actual_torque={int(params['torque_during'])} actual_flux="
            f"{int(params['flux_during'])} before={int(params['torque_before'])} after="
            f"{int(params['torque_after'])} iq={int(params['iq_during'])} id="
            f"{int(params['id_during'])} uq_limited={int(params['uq_limited'])} ud_limited="
            f"{int(params['ud_limited'])} enc_before={int(params['encoder_before'])} enc_after="
            f"{int(params['encoder_after'])} enc_delta={int(params['encoder_delta'])} adc_vm_raw="
            f"{int(params['adc_vm_raw'])}"
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
        label = self.current_torque_sample_labels.pop(detail_key, "current torque sample")
        msg = (
            f"FOCI {self.driver.name} {label}: status={int(params['status'])} target="
            f"{int(params['target'])} flux_target={int(params.get('flux_target', 0))} "
            f"sample_delay_ms={int(params['sample_delay_ms'])} voltage_limit="
            f"{int(params['voltage_limit'])} actual={int(params['torque_sample'])} before="
            f"{int(params['torque_before'])} after={int(params['torque_after'])} flux="
            f"{int(params['flux_sample'])} iq={int(params['iq_sample'])} id="
            f"{int(params['id_sample'])} uq_limited={int(params['uq_limited'])} ud_limited="
            f"{int(params['ud_limited'])} enc_before={int(params['encoder_before'])} enc_sample="
            f"{int(params['encoder_sample'])} enc_after={int(params['encoder_after'])} "
            f"enc_delta_sample={int(params['encoder_delta_sample'])} enc_delta_after="
            f"{int(params['encoder_delta_after'])} adc_vm_raw={int(params['adc_vm_raw'])} "
            f"pidin_target_torque={int(params.get('pidin_target_torque', 0))} pidin_target_flux="
            f"{int(params.get('pidin_target_flux', 0))} pidout_target_torque="
            f"{int(params.get('pidout_target_torque', 0))} pidout_target_flux="
            f"{int(params.get('pidout_target_flux', 0))} pid_torque_target_monitor="
            f"{int(params.get('pid_torque_target_monitor', 0))} torque_error="
            f"{int(detail.get('torque_error', 0))} flux_error={int(detail.get('flux_error', 0))} "
            f"torque_error_sum={int(detail.get('torque_error_sum', 0))} flux_error_sum="
            f"{int(detail.get('flux_error_sum', 0))} uq_prelimit="
            f"{int(detail.get('uq_prelimit', 0))} ud_prelimit={int(detail.get('ud_prelimit', 0))} "
            f"ff_velocity={int(detail.get('ff_velocity', 0))} ff_torque="
            f"{int(detail.get('ff_torque', 0))} status_flags=0x{params.get('status_flags', 0):08x}"
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
            f"FOCI {self.driver.name} voltage step: status={int(params['status'])} uq_ext="
            f"{int(params['uq_ext'])} ud_ext={int(params['ud_ext'])} sample_delay_ms="
            f"{int(params['sample_delay_ms'])} actual={int(params['torque_sample'])} before="
            f"{int(params['torque_before'])} after={int(params['torque_after'])} flux="
            f"{int(params['flux_sample'])} iq={int(params['iq_sample'])} id="
            f"{int(params['id_sample'])} uq_limited={int(params['uq_limited'])} ud_limited="
            f"{int(params['ud_limited'])} uux_sample={int(params['uux_sample'])} uwy_sample="
            f"{int(params['uwy_sample'])} pwm_ux_sample={int(params['pwm_ux_sample'])} "
            f"pwm_wy_sample={int(params['pwm_wy_sample'])} pwm_sv_chop=0x"
            f"{params['pwm_sv_chop']:08x} pwm_bbm=0x{params['pwm_bbm']:08x} pwm_maxcnt="
            f"{int(params['pwm_maxcnt'])} phi_e_sample={int(params['phi_e_sample'])} phi_m_sample="
            f"{int(params['phi_m_sample'])} enc_before={int(params['encoder_before'])} enc_sample="
            f"{int(params['encoder_sample'])} enc_after={int(params['encoder_after'])} "
            f"enc_delta_sample={int(params['encoder_delta_sample'])} enc_delta_after="
            f"{int(params['encoder_delta_after'])} adc_vm_raw={int(params['adc_vm_raw'])} "
            f"status_flags=0x{params['status_flags']:08x}"
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

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
        self.current_step_pending_axis = axis_name

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
        detail_key = (target, 0, sample_delay_ms, voltage_limit)
        self.current_torque_sample_details.pop(detail_key, None)
        self.current_torque_sample_labels[detail_key] = "position torque offset sample"

        self.driver.protocol.run_position_torque_offset_sample_test(
            target=target,
            sample_delay_ms=sample_delay_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            f"FOCI {self.driver.name} position-torque-offset requested: target={int(target)} "
            f"sample_delay_ms={int(sample_delay_ms)} voltage_limit={int(voltage_limit)}"
        )

    def handle_resistance_profile(self, params: dict) -> None:
        """Handle foci_resistance_profile from firmware.

        Displays board/profile constants used by the resistance sweep
        exactly as reported. The host performs no interpretation.
        """
        msg = (
            f"FOCI {self.driver.name} resistance profile: pwm_maxcnt={int(params['pwm_maxcnt'])} "
            f"bbm_h={int(params['bbm_h'])} bbm_l={int(params['bbm_l'])} dsadc_mdec_a="
            f"{int(params['dsadc_mdec_a'])} dsadc_mdec_b={int(params['dsadc_mdec_b'])} "
            f"linear_current_threshold_count={int(params['linear_current_threshold_count'])} "
            f"encoder_move_warn_counts={int(params['encoder_move_warn_counts'])} "
            f"status_flags_warn_mask=0x{params['status_flags_warn_mask']:08x} "
            f"scale_metadata_validated={int(params['scale_metadata_validated'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_resistance_run(self, params: dict) -> None:
        """Handle foci_resistance_run from firmware.

        Displays the firmware-selected count-space resistance slope and
        run-level warning/readback evidence as reported. The host does not
        recompute or re-select this value. Also caches the run fields
        (keyed by oid) so a subsequent commission completion can fold
        them into the persisted result; see pop_resistance_cache().
        """
        self.resistance_cache.setdefault(params["oid"], {})["run"] = {
            "selected_r_count_slope_milli": params["selected_r_count_slope_milli"],
            "gain_path_count_slope_milli": params.get("gain_path_count_slope_milli", 0),
            "status_flags_or": params["status_flags_or"],
            "warning_flags": params["warning_flags"],
            "peak_abs_current_count": params["peak_abs_current_count"],
            "max_abs_steady_mean_current_count": params["max_abs_steady_mean_current_count"],
            "current_ceiling_count": params["current_ceiling_count"],
            "power_stage_tripped": params["power_stage_tripped"],
        }
        msg = (
            f"FOCI {self.driver.name} resistance run: status={int(params['status'])} status_name="
            f"{format_commission_error_detail_name(params['status']) if params['status'] else 'ok'}"
            f" selected_r_count_slope_milli={int(params['selected_r_count_slope_milli'])} "
            f"warning_flags={int(params['warning_flags'])} status_flags_or=0x"
            f"{params['status_flags_or']:08x} peak_abs_current_count="
            f"{int(params['peak_abs_current_count'])} max_abs_steady_mean_current_count="
            f"{int(params['max_abs_steady_mean_current_count'])} current_ceiling_count="
            f"{int(params['current_ceiling_count'])} power_stage_tripped="
            f"{int(params['power_stage_tripped'])} pwm_maxcnt_readback="
            f"{int(params['pwm_maxcnt_readback'])} bbm_readback=0x{params['bbm_readback']:04x} "
            f"dsadc_mdec_readback=0x{params['dsadc_mdec_readback']:08x} pwm_sv_chop_readback=0x"
            f"{params['pwm_sv_chop_readback']:08x}"
        )
        report_detail(log, self.driver.global_config.debug, msg)
        if params["power_stage_tripped"]:
            toolhead = self.driver.printer.lookup_object("toolhead")
            stepper_enable = self.driver.printer.lookup_object("stepper_enable")
            enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
            enable_line.motor_disable(toolhead.get_last_move_time())
            self.driver.state.is_calibrated = False
            self.driver.homing.invalidate_homing()
            gcode = self.driver.printer.lookup_object("gcode")
            gcode.respond_info(
                f"FOCI {self.driver.name} resistance containment: firmware disabled the motor; "
                f"calibration was cleared and rehoming is required"
            )

    def handle_resistance_axis(self, params: dict) -> None:
        """Handle foci_resistance_axis from firmware.

        Displays the firmware-fitted per-axis resistance evidence exactly
        as reported: count-slope, intercept, fit residual, point-selection
        masks, signed-anchor slope/asymmetry, and thermal drift. The host
        does not fit, select points, or evaluate quality gates here. Also
        caches the axis fields (keyed by oid, routed by electrical_axis —
        not arrival order) so a subsequent commission completion can fold
        them into the persisted result; see pop_resistance_cache().
        """
        axis_key = f"axis{int(params['electrical_axis'])}"
        self.resistance_cache.setdefault(params["oid"], {})[axis_key] = {
            "r_count_slope_milli": params["r_count_slope_milli"],
            "intercept_count": params.get("intercept_count", 0),
            "rmse_permille": params.get("rmse_permille", 0),
            "selected_mask": params.get("selected_mask", 0),
            "signed_count_slope_milli": params.get("signed_count_slope_milli", 0),
            "signed_asymmetry_permille": params.get("signed_asymmetry_permille", 0),
            "drift_permille": params.get("drift_permille", 0),
        }
        msg = (
            f"FOCI {self.driver.name} resistance axis: electrical_axis="
            f"{int(params['electrical_axis'])} phi_e_ext={int(params['phi_e_ext'])} count_slope="
            f"{int(params['r_count_slope_milli'])} intercept_count="
            f"{int(params.get('intercept_count', 0))} rmse_permille="
            f"{int(params.get('rmse_permille', 0))} selected_mask=0x"
            f"{params.get('selected_mask', 0):04x} excluded_point_mask=0x"
            f"{params.get('excluded_point_mask', 0):04x} selected_count="
            f"{int(params.get('selected_count', 0))} signed_count_slope="
            f"{int(params.get('signed_count_slope_milli', 0))} signed_asymmetry_permille="
            f"{int(params.get('signed_asymmetry_permille', 0))} drift_permille="
            f"{int(params.get('drift_permille', 0))} warning_flags={int(params['warning_flags'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_current_loop_run(self, params: dict) -> None:
        """Handle foci_current_loop_run from firmware."""
        run = dict(params)
        oid = params["oid"]
        cached = self.current_loop_cache.setdefault(oid, {})
        cached["run"] = run
        self.last_current_loop_run[oid] = run
        samples = {
            "flux": [dict(sample) for sample in cached.get("flux", [])],
            "torque": [dict(sample) for sample in cached.get("torque", [])],
        }
        if samples["flux"] or samples["torque"]:
            self._last_current_loop_samples[oid] = samples
        msg = (
            f"FOCI {self.driver.name} current-loop run: status={int(params['status'])} source="
            f"{int(params['gains_source'])} tier={int(params['gains_tier'])} split_source="
            f"{int(params['axis_split_source'])} measured_split="
            f"{int(params['measured_axis_split_permille'])} applied_split="
            f"{int(params['applied_axis_split_permille'])} clamped="
            f"{int(params['axis_split_clamped'])} axes={int(params['current_validation_axes'])} "
            f"retry_exhausted={int(params['retry_budget_exhausted'])} failure_reason="
            f"{int(params['failure_reason'])}/"
            f"{CURRENT_LOOP_FAILURE_REASON_NAMES.get(params['failure_reason'], 'unknown')} "
            f"candidate_source={int(params['candidate_gains_source'])} candidate_tier="
            f"{int(params['candidate_gains_tier'])} candidate_attempt="
            f"{int(params['candidate_attempt'])} candidate_flux={int(params['candidate_flux_p'])}/"
            f"{int(params['candidate_flux_i'])} candidate_torque="
            f"{int(params['candidate_torque_p'])}/{int(params['candidate_torque_i'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_current_loop_filters(self, params: dict) -> None:
        """Handle foci_current_loop_filters from firmware."""
        filters = dict(params)
        oid = params["oid"]
        cached = self.current_loop_cache.setdefault(oid, {})
        cached["filters"] = filters
        msg = (
            f"FOCI {self.driver.name} current-loop filters: velocity="
            f"{int(params['velocity_filter_hz'])} torque={int(params['torque_filter_hz'])} "
            f"position={int(params['position_filter_hz'])} flux={int(params['flux_filter_hz'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_current_loop_hold(self, params: dict) -> None:
        """Handle foci_current_loop_hold from firmware."""
        self.last_current_loop_hold[params["oid"]] = dict(params)
        msg = (
            f"FOCI {self.driver.name} current-loop hold: hold_status={int(params['hold_status'])} "
            f"warnings={int(params['warning_flags'])} samples={int(params['sample_count'])} "
            f"elapsed_us={int(params['elapsed_us'])} period_us="
            f"{int(params['requested_sample_period_us'])} pos_span="
            f"{int(params['position_span_count'])} pos_drift={int(params['position_drift_count'])} "
            f"torque_rms={int(params['torque_rms_count'])} torque_span="
            f"{int(params['torque_peak_to_peak_count'])} torque_crossings="
            f"{int(params['torque_crossing_count'])} flux_rms={int(params['flux_rms_count'])} "
            f"flux_span={int(params['flux_peak_to_peak_count'])} flux_crossings="
            f"{int(params['flux_crossing_count'])} status_or=0x{params['status_flags_or']:08x} "
            f"actionable_status_count={int(params['actionable_status_count'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_closed_loop_activation(self, params: dict) -> None:
        """Handle foci_closed_loop_activation from firmware."""
        self.last_closed_loop_activation[params["oid"]] = dict(params)
        msg = (
            f"FOCI {self.driver.name} closed-loop entry: entry_status={int(params['entry_status'])}"
            f" position_1={int(params['position_1'])} position_2={int(params['position_2'])} "
            f"drift_count={int(params['drift_count'])} threshold_count="
            f"{int(params['threshold_count'])} runaway={int(params['runaway'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_inductance_run(self, params: dict) -> None:
        """Handle foci_inductance_run from firmware."""
        oid = params["oid"]
        cached = self._ensure_inductance_cache(oid)
        cached["run"] = dict(params)
        self._last_inductance_evidence[oid] = self._copy_inductance_cache(cached)
        report_detail(
            log,
            self.driver.global_config.debug,
            f"FOCI {self.driver.name} inductance run: source={int(params['source'])} status="
            f"{int(params['status'])} warning_flags={int(params['warning_flags'])} ud_count="
            f"{int(params['ud_count'])} realized_frequency_millihz="
            f"{int(params['realized_frequency_millihz'])} elapsed_us="
            f"{int(params['elapsed_us'])} openloop_phi_delta_counts="
            f"{int(params['openloop_phi_delta_counts'])} sample_count="
            f"{int(params['sample_count'])} encoder_delta_counts="
            f"{int(params['encoder_delta_counts'])} status_flags_or=0x"
            f"{params['status_flags_or']:08x}",
        )

    def handle_inductance_frame(self, params: dict) -> None:
        """Handle foci_inductance_frame from firmware."""
        oid = params["oid"]
        cached = self._ensure_inductance_cache(oid)
        cached["frame"] = dict(params)
        self._last_inductance_evidence[oid] = self._copy_inductance_cache(cached)
        report_detail(
            log,
            self.driver.global_config.debug,
            f"FOCI {self.driver.name} inductance frame: id_mean_milli_count="
            f"{int(params['id_mean_milli_count'])} iq_mean_milli_count="
            f"{int(params['iq_mean_milli_count'])} id_rms_milli_count="
            f"{int(params['id_rms_milli_count'])} iq_rms_milli_count="
            f"{int(params['iq_rms_milli_count'])} drift_permille="
            f"{int(params['drift_permille'])} zero_id_mean_milli_count="
            f"{int(params['zero_id_mean_milli_count'])} zero_iq_mean_milli_count="
            f"{int(params['zero_iq_mean_milli_count'])}",
        )

    def handle_inductance_estimate(self, params: dict) -> None:
        """Handle foci_inductance_estimate from firmware."""
        oid = params["oid"]
        cached = self._ensure_inductance_cache(oid)
        cached["estimate"] = dict(params)
        self._last_inductance_evidence[oid] = self._copy_inductance_cache(cached)
        report_detail(
            log,
            self.driver.global_config.debug,
            f"FOCI {self.driver.name} inductance estimate: x_average_count_ratio_milli="
            f"{int(params['x_average_count_ratio_milli'])} x_d_count_ratio_milli="
            f"{int(params['x_d_count_ratio_milli'])} x_q_count_ratio_milli="
            f"{int(params['x_q_count_ratio_milli'])} saliency_status="
            f"{int(params['saliency_status'])} saliency_permille="
            f"{int(params['saliency_permille'])} x_mag_nominal_count_ratio_milli="
            f"{int(params['x_mag_nominal_count_ratio_milli'])} x_mag_shift_minus_permille="
            f"{int(params['x_mag_shift_minus_permille'])} x_mag_shift_plus_permille="
            f"{int(params['x_mag_shift_plus_permille'])} x_mag_vs_quad_permille="
            f"{int(params['x_mag_vs_quad_permille'])}",
        )

    def handle_encoder_alignment(self, params: dict) -> None:
        """Handle foci_encoder_alignment from firmware."""
        evidence = dict(params)
        self.last_encoder_alignment[params["oid"]] = evidence
        msg = (
            f"FOCI {self.driver.name} encoder alignment: encoder_count="
            f"{int(params['encoder_count'])} electrical_residual_counts="
            f"{int(params['electrical_residual_counts'])} stability_counts="
            f"{int(params['stability_counts'])} movement_counts={int(params['movement_counts'])} "
            f"min_movement_counts={int(params['min_movement_counts'])} counts_per_electrical_rev="
            f"{int(params['counts_per_electrical_rev'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_adc_residual(self, params: dict) -> None:
        """Handle foci_adc_residual from firmware."""
        cached = self.adc_residuals.setdefault(params["oid"], [])
        cached.append(dict(params))
        msg = (
            f"FOCI {self.driver.name} adc residual: stage={int(params['stage'])} sample_count="
            f"{int(params['sample_count'])} pwm_sv_chop={int(params['pwm_sv_chop'])} pwm_bbm=0x"
            f"{params['pwm_bbm']:08x} adc_i0_scale_offset=0x{params['adc_i0_scale_offset']:08x} "
            f"adc_i1_scale_offset=0x{params['adc_i1_scale_offset']:08x} adc_iux_mean_count="
            f"{int(params['adc_iux_mean_count'])} adc_iwy_mean_count="
            f"{int(params['adc_iwy_mean_count'])} pid_flux_mean_count="
            f"{int(params['pid_flux_mean_count'])} pid_torque_mean_count="
            f"{int(params['pid_torque_mean_count'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_current_validation_axis(self, params: dict) -> None:
        """Handle foci_current_validation_axis from firmware."""
        axis_key = {0: "flux", 1: "torque"}.get(params["axis"])
        cached = self.current_loop_cache.setdefault(params["oid"], {})
        if axis_key is None:
            cached["invalid_axis"] = True
        else:
            axis_samples = cached.setdefault(axis_key, [])
            sample = dict(params)
            sample["gate_role"] = self._current_validation_gate_role(
                axis_key, params["sample_delay_ms"]
            )
            axis_samples.append(sample)
        msg = (
            f"FOCI {self.driver.name} current validation: axis={int(params['axis'])} sample_index="
            f"{int(params['sample_index'])} status={int(params['status'])} attempt="
            f"{int(params['attempt'])} target={int(params['target'])} delay_ms="
            f"{int(params['sample_delay_ms'])} role="
            f"{self._current_validation_gate_role(axis_key, params['sample_delay_ms'])} response="
            f"{int(params['positive_response_permille'])}/"
            f"{int(params['negative_response_permille'])} cross="
            f"{int(params['cross_axis_permille'])} cross_peak="
            f"{int(params.get('cross_axis_peak_permille', params['cross_axis_permille']))} voltage="
            f"{int(params['voltage_output_permille'])} encoder_delta="
            f"{int(params['encoder_delta_counts'])} signed_encoder_delta="
            f"{int(params.get('positive_encoder_delta_counts', 0))}/"
            f"{int(params.get('negative_encoder_delta_counts', 0))} status_flags_or=0x"
            f"{params['status_flags_or']:08x}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_current_validation_settled_sample(self, params: dict) -> None:
        """Handle foci_current_validation_settled_sample from firmware."""
        cached = self.current_loop_cache.setdefault(params["oid"], {})
        settled_samples = cached.setdefault("settled_samples", [])
        settled_samples.append(dict(params))
        msg = (
            f"FOCI {self.driver.name} current validation settled: axis={int(params['axis'])} "
            f"sample_index={int(params['sample_index'])} direction={int(params['direction'])} "
            f"raw_index={int(params['raw_index'])} attempt={int(params['attempt'])} target="
            f"{int(params['target'])} delay_ms={int(params['sample_delay_ms'])} same_count="
            f"{int(params['same_axis_count'])} cross_count={int(params['cross_axis_count'])} cross="
            f"{int(params['cross_axis_permille'])} voltage={int(params['voltage_output_permille'])}"
            f" encoder_delta={int(params['encoder_delta_counts'])} status_flags=0x"
            f"{params['status_flags']:08x}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def handle_current_validation_envelope(self, params: dict) -> None:
        """Handle foci_current_validation_envelope from firmware."""
        cached = self.current_loop_cache.setdefault(params["oid"], {})
        cached["validation_envelope"] = dict(params)
        msg = (
            f"FOCI {self.driver.name} current validation envelope: step_amplitude="
            f"{int(params['step_amplitude'])} flux_step_amplitude="
            f"{int(params['flux_step_amplitude'])} torque_step_amplitude="
            f"{int(params['torque_step_amplitude'])} pidout_limit={int(params['pidout_limit'])} "
            f"current_limited={int(params['current_limited'])} voltage_limited="
            f"{int(params['voltage_limited'])} max_p={int(params['max_p'])}"
        )
        report_detail(log, self.driver.global_config.debug, msg)

    def _current_validation_gate_role(self, axis_key: str | None, sample_delay_ms: int) -> str:
        if axis_key == "flux" and sample_delay_ms == 100:
            return "gate"
        if axis_key == "torque" and sample_delay_ms == 0:
            return "gate"
        return "telemetry"

    def pop_resistance_cache(self, oid: int) -> dict:
        """Fold cached commission-stream resistance replies into result keys.

        Returns a dict of `resistance_*` keys (the keys
        CommissioningWorkflow.persist_commission_results' presence-gated
        resistance block already expects), built from the cached
        foci_resistance_run / foci_resistance_axis replies for `oid` by
        handle_resistance_run / handle_resistance_axis. Clears the cache
        entry for `oid` unconditionally (see clear_resistance_cache).

        All-or-nothing: returns the full folded dict only when the cache
        holds the run reply AND both axis0 and axis1 replies. If any of
        the three is missing — for example a commission that completed
        before every resistance reply arrived — returns `{}` so the
        presence-gate in persist_commission_results' resistance block
        skips the block entirely instead of persisting a partial set of
        identified_r_* keys (or raising a KeyError on the missing one).

        The host performs no fitting, point selection, unit conversion,
        or quality-gate evaluation here: every value is copied through
        from the firmware-reported reply fields as-is.
        """
        cached = self.clear_resistance_cache(oid)
        if not cached:
            return {}

        run = cached.get("run")
        axis0 = cached.get("axis0")
        axis1 = cached.get("axis1")
        if run is None or axis0 is None or axis1 is None:
            return {}

        folded: dict = {
            "resistance_selected_count_slope_milli": run["selected_r_count_slope_milli"],
        }

        return folded

    def clear_resistance_cache(self, oid: int) -> dict:
        """Discard and return the cached resistance replies for `oid`.

        Called by pop_resistance_cache on the commission success path, and
        directly by CommissioningWorkflow on every early-exit failure path
        (timeout, mid-phase error) so a failed or aborted commission never
        leaves a stale resistance-reply cache for a later run to fold in.
        Returns an empty dict if nothing was cached.
        """
        return self.resistance_cache.pop(oid, None) or {}

    def clear_inductance_cache(self, oid: int) -> dict:
        """Discard and return the cached inductance replies for `oid`."""
        return self.inductance_cache.pop(oid, None) or {}

    def pop_inductance_cache(self, oid: int) -> dict:
        """Fold cached commission-stream inductance replies into result keys."""
        cached = self.clear_inductance_cache(oid)
        if not cached:
            return {}

        run = cached.get("run")
        frame = cached.get("frame")
        estimate = cached.get("estimate")
        if run is None or frame is None or estimate is None:
            return {}

        return {
            "inductance_source": run["source"],
            "inductance_reactance_count_ratio_milli": estimate["x_average_count_ratio_milli"],
            "inductance_saliency_status": estimate["saliency_status"],
        }

    def pop_current_loop_cache(self, oid: int) -> dict:
        """Fold cached commission-stream current-loop replies into result keys."""
        cached = self.clear_current_loop_cache(oid)
        if not cached:
            return {}

        filters = cached.get("filters")
        folded_filters = {}
        if filters is not None:
            folded_filters = {
                "velocity_filter_hz": filters["velocity_filter_hz"],
                "current_torque_filter_hz": filters["torque_filter_hz"],
                "position_filter_hz": filters["position_filter_hz"],
                "current_flux_filter_hz": filters["flux_filter_hz"],
            }

        run = cached.get("run")
        flux_samples = cached.get("flux", [])
        torque_samples = cached.get("torque", [])
        if run is None:
            return folded_filters
        if cached.get("invalid_axis"):
            return folded_filters
        expected_flux_samples = run["flux_validation_sample_count"]
        expected_torque_samples = run["torque_validation_sample_count"]
        if expected_flux_samples == 0 or expected_torque_samples == 0:
            return folded_filters
        if len(flux_samples) != expected_flux_samples:
            return folded_filters
        if len(torque_samples) != expected_torque_samples:
            return folded_filters

        return {
            **folded_filters,
            "current_gains_source": run["gains_source"],
            "current_gains_tier": run["gains_tier"],
            "current_retry_budget_exhausted": run["retry_budget_exhausted"],
            "current_failure_reason": run["failure_reason"],
            "current_candidate_attempt": run["candidate_attempt"],
        }

    def clear_current_loop_cache(self, oid: int) -> dict:
        """Discard and return the cached current-loop replies for `oid`."""
        return self.current_loop_cache.pop(oid, None) or {}

    def last_current_loop_evidence(self, oid: int) -> dict:
        """Return the most recent transient current-loop run reply for `oid`."""
        return self.last_current_loop_run.get(oid, {})

    def last_current_loop_hold_evidence(self, oid: int) -> dict:
        """Return the most recent transient current-loop hold reply for `oid`."""
        return self.last_current_loop_hold.get(oid, {})

    def last_closed_loop_activation_evidence(self, oid: int) -> dict:
        """Return the most recent transient closed-loop entry reply for `oid`."""
        return self.last_closed_loop_activation.get(oid, {})

    def last_inductance_evidence(self, oid: int) -> dict:
        """Return the most recent transient inductance evidence for `oid`."""
        return self._last_inductance_evidence.get(oid, {})

    def last_current_loop_samples(self, oid: int) -> dict[str, list[dict]]:
        """Return current-validation sample replies from the most recent run."""
        return self._last_current_loop_samples.get(oid, {})

    def last_encoder_alignment_evidence(self, oid: int) -> dict:
        """Return the most recent transient encoder-alignment reply for `oid`."""
        return self.last_encoder_alignment.get(oid, {})

    def clear_last_encoder_alignment_evidence(self, oid: int) -> dict:
        """Discard and return the last encoder-alignment reply for `oid`."""
        return self.last_encoder_alignment.pop(oid, None) or {}

    def _copy_inductance_cache(self, cached: dict) -> dict:
        copied = {}
        for key in ("run", "frame", "estimate"):
            value = cached.get(key)
            copied[key] = dict(value) if value is not None else None
        return copied

    def _ensure_inductance_cache(self, oid: int) -> dict:
        return self.inductance_cache.setdefault(
            oid,
            {"run": None, "frame": None, "estimate": None},
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
