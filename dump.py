"""FOCI register dump workflow."""

from __future__ import annotations

from .registers import (
    DUMP_GROUPS,
    FIELD_FORMATTERS,
    REGISTERS,
    SIGNED_FIELDS,
    Fields,
    FieldHelper,
    fmt_adc_vm_raw,
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
    "identified_theta_e_us",
    "identified_ringing_count",
    "identified_bandwidth_hz",
    "identified_inner_warning_flags",
)

CURRENT_LOOP_IDENTIFICATION_FIELDS: tuple[str, ...] = (
    "identified_current_gains_source",
    "identified_current_candidate_gains_source",
    "identified_axis_split_source",
    "identified_current_candidate_axis_split_source",
    "identified_current_gains_tier",
    "identified_current_candidate_gains_tier",
    "identified_current_measured_axis_split_permille",
    "identified_current_candidate_measured_axis_split_permille",
    "identified_current_applied_axis_split_permille",
    "identified_current_candidate_applied_axis_split_permille",
    "identified_current_axis_split_clamped",
    "identified_current_candidate_axis_split_clamped",
    "identified_current_candidate_flux_p",
    "identified_current_candidate_flux_i",
    "identified_current_candidate_torque_p",
    "identified_current_candidate_torque_i",
    "identified_current_candidate_attempt",
    "identified_current_validation_axes",
    "identified_current_flux_validation_sample_count",
    "identified_current_torque_validation_sample_count",
    "identified_current_retry_budget_exhausted",
    "identified_current_failure_reason",
    "identified_current_flux_response_min_permille",
    "identified_current_torque_response_min_permille",
    "identified_current_flux_encoder_delta_counts",
    "identified_current_torque_encoder_delta_counts",
)

CURRENT_GAINS_SOURCE_LABELS: dict[int, str] = {
    0: "failed",
    1: "measured",
    2: "default",
}

AXIS_SPLIT_SOURCE_LABELS: dict[int, str] = {
    0: "none",
    1: "impedance",
}

CURRENT_GAINS_TIER_LABELS: dict[int, str] = {
    0: "none",
    1: "measured_symmetric",
    2: "measured_split",
    3: "default",
    4: "physical_symmetric",
}

CURRENT_LOOP_FAILURE_LABELS: dict[int, str] = {
    0: "none",
    1: "resistance_invalid",
    2: "impedance_invalid",
    3: "gain_synthesis",
    4: "flux_validation",
    5: "torque_validation",
    6: "saturation",
    7: "motion",
    8: "status_flags",
    9: "retry_exhausted",
    10: "spi",
    11: "hold_position_span",
    12: "hold_status_flags",
    13: "hold_sample_error",
    14: "response_magnitude",
    15: "cross_axis_coupling",
    16: "wrong_sign",
}

CURRENT_LOOP_HOLD_STATUS_LABELS: dict[int, str] = {
    0: "not_run",
    1: "pass",
    2: "fail_position_span",
    3: "fail_status_flags",
    4: "fail_sample_error",
}

CURRENT_VALIDATION_AXIS_FLUX = 0x01
CURRENT_VALIDATION_AXIS_TORQUE = 0x02

# Firmware-owned resistance-identification evidence (count-space, no
# host-side fitting). Displayed as persisted; not recomputed here.
RESISTANCE_IDENTIFICATION_FIELDS: tuple[str, ...] = (
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

INDUCTANCE_IDENTIFICATION_FIELDS: tuple[str, ...] = (
    "identified_l_source",
    "identified_l_warning_flags",
    "identified_l_frequency_millihz",
    "identified_l_reactance_count_ratio_milli",
    "identified_l_d_reactance_count_ratio_milli",
    "identified_l_q_reactance_count_ratio_milli",
    "identified_l_saliency_status",
    "identified_l_saliency_permille",
    "identified_l_iq_mean_milli_count",
    "identified_l_drift_permille",
    "identified_l_r_shift_minus_permille",
    "identified_l_r_shift_plus_permille",
    "identified_l_x_mag_vs_quad_permille",
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
                    lines.append(self._pretty_format_register(reg_name, val))
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
            "  Note: identified_r*/identified_l* are control-model count-space"
            " fields derived during commissioning; AC reactance evidence is"
            " reported separately below."
        )

        lines.append("-- Persisted inductance evidence --")
        lines.extend(self._format_persisted_inductance_evidence())
        lines.append(
            "  Note: persisted identified_l_* inductance fields are"
            " firmware-reported count-space reactance evidence; the host"
            " performs no fitting or quality-gate evaluation."
        )

        lines.append("-- Current-loop commissioning evidence --")
        lines.extend(self._format_current_loop_summary())
        lines.extend(
            self._format_pair("config.%s" % field_name, getattr(config, field_name))
            for field_name in CURRENT_LOOP_IDENTIFICATION_FIELDS
        )
        lines.append(
            "  Note: identified_current_* and identified_axis_split_source"
            " fields are firmware-reported current-loop evidence (accepted"
            " gains source, split source, validation sample counts,"
            " response minima, and encoder-delta maxima); the host performs"
            " no gain selection or quality-gate evaluation."
        )

        last_current_loop = self.driver.diagnostics.active.last_current_loop_evidence(
            self.driver.oid
        )
        if last_current_loop:
            lines.append("-- Last current-loop run (not persisted) --")
            lines.extend(self._format_last_current_loop_summary(last_current_loop))
            lines.extend(
                self._format_last_current_validation_samples(
                    self.driver.diagnostics.active.last_current_loop_samples(
                        self.driver.oid
                    )
                )
            )

        last_current_loop_hold = (
            self.driver.diagnostics.active.last_current_loop_hold_evidence(
                self.driver.oid
            )
        )
        if last_current_loop_hold:
            lines.append("-- Last sustained-hold gate (not persisted) --")
            lines.extend(self._format_last_current_loop_hold(last_current_loop_hold))

        last_encoder_alignment = (
            self.driver.diagnostics.active.last_encoder_alignment_evidence(
                self.driver.oid
            )
        )
        if last_encoder_alignment:
            lines.append("-- Last encoder alignment (not persisted) --")
            lines.extend(self._format_last_encoder_alignment(last_encoder_alignment))

        last_inductance = self.driver.diagnostics.active.last_inductance_evidence(
            self.driver.oid
        )
        if last_inductance:
            lines.append("-- Last inductance evidence (not persisted) --")
            lines.extend(self._format_last_inductance_evidence(last_inductance))

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

    def _pretty_format_register(self, reg_name: str, reg_value: int) -> str:
        if reg_name != "ADC_VM_RAW":
            return self.fields.pretty_format(reg_name, reg_value)

        constants = {}
        get_constants = getattr(self.driver.mcu, "get_constants", None)
        if get_constants is not None:
            constants = get_constants()
        raw = self.fields.get_field("adc_vm_raw", reg_name, reg_value)
        return "%-30s %08x adc_vm_raw=%s" % (
            reg_name + ":",
            reg_value,
            fmt_adc_vm_raw(raw, constants, self.driver.state.adc_vm_offset_raw),
        )

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
        active_gains: dict[str, int | None] | None,
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

    def _format_persisted_inductance_evidence(self) -> list[str]:
        config = self.driver.config
        return [
            self._format_pair("config.%s" % field_name, getattr(config, field_name))
            for field_name in INDUCTANCE_IDENTIFICATION_FIELDS
        ]

    def _format_last_inductance_evidence(self, evidence: dict) -> list[str]:
        lines = []
        run = evidence.get("run")
        if run is not None:
            lines.extend(
                self._format_last_inductance_group(
                    "last.inductance_run",
                    run,
                    (
                        "source",
                        "status",
                        "warning_flags",
                        "ud_count",
                        "realized_frequency_millihz",
                        "elapsed_us",
                        "openloop_phi_delta_counts",
                        "sample_count",
                        "encoder_delta_counts",
                        "status_flags_or",
                    ),
                )
            )
        frame = evidence.get("frame")
        if frame is not None:
            lines.extend(
                self._format_last_inductance_group(
                    "last.inductance_frame",
                    frame,
                    (
                        "id_mean_milli_count",
                        "iq_mean_milli_count",
                        "id_rms_milli_count",
                        "iq_rms_milli_count",
                        "drift_permille",
                        "zero_id_mean_milli_count",
                        "zero_iq_mean_milli_count",
                    ),
                )
            )
        estimate = evidence.get("estimate")
        if estimate is not None:
            lines.extend(
                self._format_last_inductance_group(
                    "last.inductance_estimate",
                    estimate,
                    (
                        "x_average_count_ratio_milli",
                        "x_d_count_ratio_milli",
                        "x_q_count_ratio_milli",
                        "saliency_status",
                        "saliency_permille",
                        "x_mag_nominal_count_ratio_milli",
                        "x_mag_shift_minus_permille",
                        "x_mag_shift_plus_permille",
                        "x_mag_vs_quad_permille",
                    ),
                )
            )
        return lines

    def _format_last_inductance_group(
        self,
        prefix: str,
        values: dict,
        field_names: tuple[str, ...],
    ) -> list[str]:
        return [
            self._format_pair("%s.%s" % (prefix, field_name), values.get(field_name))
            for field_name in field_names
        ]

    def _format_current_loop_summary(self) -> list[str]:
        config = self.driver.config
        validation_axes = config.identified_current_validation_axes
        return [
            "  current_gains_source: %s"
            % self._label_code(
                config.identified_current_gains_source,
                CURRENT_GAINS_SOURCE_LABELS,
            ),
            "  axis_split_source: %s"
            % self._label_code(
                config.identified_axis_split_source,
                AXIS_SPLIT_SOURCE_LABELS,
            ),
            "  current_gains_tier: %s"
            % self._label_code(
                config.identified_current_gains_tier,
                CURRENT_GAINS_TIER_LABELS,
            ),
            "  current_validation: flux=%s torque=%s"
            % (
                self._axis_validation_label(
                    validation_axes, CURRENT_VALIDATION_AXIS_FLUX
                ),
                self._axis_validation_label(
                    validation_axes, CURRENT_VALIDATION_AXIS_TORQUE
                ),
            ),
            "  retry_budget_exhausted: %s"
            % self._bool_code(config.identified_current_retry_budget_exhausted),
            "  failure_reason: %s"
            % self._label_code(
                config.identified_current_failure_reason,
                CURRENT_LOOP_FAILURE_LABELS,
            ),
        ]

    def _format_last_current_loop_summary(self, run: dict) -> list[str]:
        validation_axes = run.get("current_validation_axes")
        flux_sample_count = run.get("flux_validation_sample_count")
        torque_sample_count = run.get("torque_validation_sample_count")
        return [
            self._format_pair(
                "last.current_gains_source",
                self._label_code(run.get("gains_source"), CURRENT_GAINS_SOURCE_LABELS),
            ),
            self._format_pair(
                "last.candidate_gains_source",
                self._label_code(
                    run.get("candidate_gains_source"), CURRENT_GAINS_SOURCE_LABELS
                ),
            ),
            self._format_pair(
                "last.axis_split_source",
                self._label_code(
                    run.get("axis_split_source"), AXIS_SPLIT_SOURCE_LABELS
                ),
            ),
            self._format_pair(
                "last.candidate_axis_split_source",
                self._label_code(
                    run.get("candidate_axis_split_source"), AXIS_SPLIT_SOURCE_LABELS
                ),
            ),
            self._format_pair(
                "last.current_gains_tier",
                self._label_code(run.get("gains_tier"), CURRENT_GAINS_TIER_LABELS),
            ),
            self._format_pair(
                "last.candidate_gains_tier",
                self._label_code(
                    run.get("candidate_gains_tier"), CURRENT_GAINS_TIER_LABELS
                ),
            ),
            self._format_pair("last.candidate_flux_p", run.get("candidate_flux_p")),
            self._format_pair("last.candidate_flux_i", run.get("candidate_flux_i")),
            self._format_pair("last.candidate_torque_p", run.get("candidate_torque_p")),
            self._format_pair("last.candidate_torque_i", run.get("candidate_torque_i")),
            self._format_pair("last.candidate_attempt", run.get("candidate_attempt")),
            self._format_pair(
                "last.current_validation",
                "flux=%s torque=%s"
                % (
                    self._axis_validation_label_for_count(
                        validation_axes, CURRENT_VALIDATION_AXIS_FLUX, flux_sample_count
                    ),
                    self._axis_validation_label_for_count(
                        validation_axes,
                        CURRENT_VALIDATION_AXIS_TORQUE,
                        torque_sample_count,
                    ),
                ),
            ),
            self._format_pair(
                "last.retry_budget_exhausted",
                self._bool_code(run.get("retry_budget_exhausted")),
            ),
            self._format_pair(
                "last.failure_reason",
                self._label_code(
                    run.get("failure_reason"), CURRENT_LOOP_FAILURE_LABELS
                ),
            ),
        ]

    def _format_last_current_loop_hold(self, evidence: dict) -> list[str]:
        return [
            self._format_hold_pair(
                "last.hold_status",
                self._label_code(
                    evidence.get("hold_status"), CURRENT_LOOP_HOLD_STATUS_LABELS
                ),
            ),
            self._format_hold_pair(
                "last.hold_samples",
                "%s @ %s us, elapsed_us=%s"
                % (
                    evidence.get("sample_count"),
                    evidence.get("requested_sample_period_us"),
                    evidence.get("elapsed_us"),
                ),
            ),
            self._format_hold_pair(
                "last.hold_position",
                "span=%s drift=%s"
                % (
                    evidence.get("position_span_count"),
                    evidence.get("position_drift_count"),
                ),
            ),
            self._format_hold_pair(
                "last.hold_torque",
                "mean=%s rms=%s span=%s crossings=%s"
                % (
                    evidence.get("torque_mean_count"),
                    evidence.get("torque_rms_count"),
                    evidence.get("torque_peak_to_peak_count"),
                    evidence.get("torque_crossing_count"),
                ),
            ),
            self._format_hold_pair(
                "last.hold_flux",
                "mean=%s rms=%s span=%s crossings=%s"
                % (
                    evidence.get("flux_mean_count"),
                    evidence.get("flux_rms_count"),
                    evidence.get("flux_peak_to_peak_count"),
                    evidence.get("flux_crossing_count"),
                ),
            ),
            self._format_hold_pair(
                "last.hold_status_flags",
                "or=%s actionable_count=%s warnings=%s"
                % (
                    evidence.get("status_flags_or"),
                    evidence.get("actionable_status_count"),
                    evidence.get("warning_flags"),
                ),
            ),
        ]

    def _format_last_current_validation_samples(self, samples: dict) -> list[str]:
        lines = []
        for axis_key in ("flux", "torque"):
            for sample in samples.get(axis_key, []):
                label = "last.current_validation_sample[%s:%s]" % (
                    axis_key,
                    sample.get("sample_index"),
                )
                value = (
                    "role=%s delay_ms=%s status=%s response=%s/%s"
                    " cross=%s cross_peak=%s voltage=%s encoder_delta=%s"
                    " signed_encoder_delta=%s/%s"
                    % (
                        sample.get("gate_role", "unknown"),
                        sample.get("sample_delay_ms"),
                        sample.get("status"),
                        sample.get("positive_response_permille"),
                        sample.get("negative_response_permille"),
                        sample.get("cross_axis_permille"),
                        sample.get(
                            "cross_axis_peak_permille",
                            sample.get("cross_axis_permille"),
                        ),
                        sample.get("voltage_output_permille"),
                        sample.get("encoder_delta_counts"),
                        sample.get("positive_encoder_delta_counts", 0),
                        sample.get("negative_encoder_delta_counts", 0),
                    )
                )
                lines.append(self._format_pair(label, value))
        return lines

    def _format_last_encoder_alignment(self, evidence: dict) -> list[str]:
        residual = "%s/%s counts" % (
            evidence.get("electrical_residual_counts"),
            evidence.get("counts_per_electrical_rev"),
        )
        return [
            self._format_pair(
                "last.encoder_alignment_count", evidence.get("encoder_count")
            ),
            self._format_pair("last.encoder_alignment_residual", residual),
            self._format_pair(
                "last.encoder_alignment_stability",
                "%s counts" % evidence.get("stability_counts"),
            ),
            self._format_pair(
                "last.encoder_alignment_movement",
                "%s counts" % evidence.get("movement_counts"),
            ),
            self._format_pair(
                "last.encoder_alignment_min_movement",
                "%s counts" % evidence.get("min_movement_counts"),
            ),
        ]

    def _label_code(self, value: int | None, labels: dict[int, str]) -> str:
        if value is None:
            return "unknown"
        return labels.get(value, "unknown(%d)" % value)

    def _axis_validation_label(self, axes: int | None, mask: int) -> str:
        if axes is None:
            return "unknown"
        return "pass" if axes & mask else "fail"

    def _axis_validation_label_for_count(
        self, axes: int | None, mask: int, sample_count: int | None
    ) -> str:
        if axes is None or sample_count is None:
            return "unknown"
        if sample_count <= 0:
            return "not_run"
        return self._axis_validation_label(axes, mask)

    def _bool_code(self, value: int | None) -> str:
        if value is None:
            return "unknown"
        return "yes" if value else "no"

    def _format_pair(self, name: str, value: object | None) -> str:
        return "  %-34s = %s" % (name, self._display_value(value))

    def _format_hold_pair(self, name: str, value: object | None) -> str:
        return "  %-32s = %s" % (name, self._display_value(value))

    def _display_value(self, value: object | None) -> str:
        if value is None:
            return "(unset)"
        return str(value)
