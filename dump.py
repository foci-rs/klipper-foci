"""FOCI register dump workflow."""

from __future__ import annotations

from .commissioning import CURRENT_LOOP_FAILURE_REASON_NAMES
from .config import POSITION_UNITS_PER_REV
from .readiness import format_readiness_report, resolve_autotune_readiness
from .registers import (
    DUMP_GROUPS,
    FIELD_FORMATTERS,
    REGISTERS,
    SIGNED_FIELDS,
    FieldHelper,
    Fields,
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
    "identified_lambda_us",
    "identified_tau_e_us",
    "identified_theta_e_us",
    "identified_theta_source",
    "identified_bandwidth_hz",
    "identified_inner_warning_flags",
)

CURRENT_LOOP_IDENTIFICATION_FIELDS: tuple[str, ...] = (
    "identified_current_gains_source",
    "identified_current_gains_tier",
    "identified_current_retry_budget_exhausted",
    "identified_current_failure_reason",
)

CURRENT_GAINS_SOURCE_NAMES: dict[int, str] = {
    0: "failed",
    1: "measured",
    2: "default",
}

AXIS_SPLIT_SOURCE_NAMES: dict[int, str] = {
    0: "none",
    1: "impedance",
}

CURRENT_GAINS_TIER_NAMES: dict[int, str] = {
    0: "none",
    1: "measured_symmetric",
    2: "measured_split",
    3: "default",
    4: "physical_symmetric",
}

CURRENT_LOOP_HOLD_STATUS_NAMES: dict[int, str] = {
    0: "not_run",
    1: "pass",
    2: "fail_position_span",
    3: "fail_status_flags",
    4: "fail_sample_error",
}

CLOSED_LOOP_ACTIVATION_STATUS_NAMES: dict[int, str] = {
    0: "not_run",
    1: "pass",
    2: "fail_runaway",
    3: "fail_drift",
    4: "warn_drift",
}

CURRENT_VALIDATION_AXIS_FLUX = 0x01
CURRENT_VALIDATION_AXIS_TORQUE = 0x02

# Firmware-owned resistance-identification evidence (count-space, no
# host-side fitting). Displayed as persisted; not recomputed here.
RESISTANCE_IDENTIFICATION_FIELDS: tuple[str, ...] = ("identified_r_count_slope_milli",)

INDUCTANCE_IDENTIFICATION_FIELDS: tuple[str, ...] = (
    "identified_l_source",
    "identified_l_reactance_count_ratio_milli",
    "identified_l_saliency_status",
)

VELOCITY_TUNE_PROVENANCE_FIELDS: tuple[str, ...] = (
    "autotune_probed_velocity_mrev_s",
    "autotune_d_eq_q",
    "autotune_confidence_q",
    "autotune_band_lower_percent",
    "autotune_band_upper_percent",
    "autotune_band_position_q",
)

POSITION_TUNE_FIELDS: tuple[tuple[str, str], ...] = (
    ("autotune_position_bound_units", "bound"),
    ("autotune_position_homing_peak_units", "homing peak"),
    ("autotune_position_motion_cruise_units", "motion cruise"),
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

    def _request_dump_values(self) -> bool:
        reactor = self.driver.printer.get_reactor()
        self._dump_buffer.clear()
        self._dump_complete = False
        self.driver.protocol.dump_registers()

        # Wait for dump completion. The serial reader thread calls
        # handle_dump_done which sets _dump_complete.
        deadline = reactor.monotonic() + 5.0
        while not self._dump_complete and reactor.monotonic() < deadline:
            reactor.pause(reactor.monotonic() + 0.05)

        return self._dump_complete

    def dump_registers(self, gcmd) -> None:
        """Handler for DUMP_FOCI and DUMP_TMC GCode commands.

        Sends a single foci_dump_registers command to the firmware and
        waits for all register values to be streamed back via the
        FOCI:DUMP: output protocol, then prints them formatted to the
        GCode console. ``TUNING=1`` appends host-derived read-only tuning
        analysis using the same dump response.
        """
        include_tuning = bool(gcmd.get_int("TUNING", 0, minval=0, maxval=1))
        if not self._request_dump_values():
            gcmd.respond_info("FOCI register dump timed out")
            return

        lines: list[str] = []
        for group_name, regs in DUMP_GROUPS:
            if "%s" in group_name:
                header = group_name % self.driver.stepper_name
            else:
                header = group_name
            lines.append(f"========== {header} ==========")
            for reg_name in regs:
                addr = REGISTERS[reg_name]
                if addr in self._dump_buffer:
                    val = self._dump_buffer[addr]
                    lines.append(self._pretty_format_register(reg_name, val))
                else:
                    lines.append(f"  {reg_name:30} = (not in dump)")

        stall = self.driver.protocol.query_stall()
        lines.append(
            f"homing clamp_active={stall['clamp_active']} last_stall latched={stall['latched']} "
            f"peak_error_units={stall['peak_error_units']} trigger_tick={stall['trigger_tick']}"
        )

        if include_tuning:
            lines.extend(self._format_tuning_analysis())

        gcmd.respond_info("\n".join(lines))

    def _format_tuning_analysis(self) -> list[str]:
        config = self.driver.config
        state = self.driver.state
        active_gains = state.active_gains
        live_gains = self._live_gain_values()

        lines = ["", "========== Tuning Analysis =========="]

        # -- Status --
        lines.append(self._format_block_header("Status"))
        lines.append("-- Runtime status --")
        lines.append(self._format_pair("autotune_status", config.autotune_status))
        lines.append(self._format_pair("runtime_status", state.runtime_status))
        lines.append(
            self._format_pair("active_gains_present", "yes" if active_gains is not None else "no")
        )
        lines.append(self._format_pair("autotune_profile", config.autotune_profile))
        lines.append(self._format_pair("autotune_mode", config.autotune_mode))
        persisted_status = config.autotune_status or "uncommissioned"
        if persisted_status != state.runtime_status:
            lines.append(
                f"  WARNING: autotune_status/runtime_status divergence persisted="
                f"{persisted_status} validated={state.runtime_status}"
            )
        readiness = resolve_autotune_readiness(
            self.driver,
            live_current_gains={
                "flux_p": live_gains.get("flux_p"),
                "flux_i": live_gains.get("flux_i"),
                "torque_p": live_gains.get("torque_p"),
                "torque_i": live_gains.get("torque_i"),
            },
        )
        lines.extend(format_readiness_report(readiness, self.driver.name))

        # -- Persisted --
        lines.append(self._format_block_header("Persisted"))
        lines.append("-- Persisted config gains --")
        lines.extend(
            self._format_pair(f"config.{field_name}", getattr(config, field_name))
            for field_name in CONFIG_GAIN_FIELDS
        )
        lines.append("-- Identified count-space model --")
        lines.extend(
            self._format_pair(f"config.{field_name}", getattr(config, field_name))
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
            self._format_pair(f"config.{field_name}", getattr(config, field_name))
            for field_name in CURRENT_LOOP_IDENTIFICATION_FIELDS
        )
        lines.append(
            "  Note: identified_current_* fields are firmware-reported"
            " current-loop evidence (accepted gains source/tier, retry"
            " budget, failure reason); the host performs no gain"
            " selection or quality-gate evaluation."
        )
        lines.append("-- Resistance identification evidence --")
        lines.extend(
            self._format_pair(f"config.{field_name}", getattr(config, field_name))
            for field_name in RESISTANCE_IDENTIFICATION_FIELDS
        )
        lines.append("-- Velocity tune provenance --")
        lines.extend(
            self._format_pair(f"config.{field_name}", getattr(config, field_name))
            for field_name in VELOCITY_TUNE_PROVENANCE_FIELDS
        )
        lines.append("-- Position tune provenance --")
        lines.extend(self._format_position_tune_provenance(config))

        # -- Volatile --
        lines.append(self._format_block_header("Volatile"))
        lines.append("-- Live TMC gains --")
        lines.extend(
            self._format_pair(f"live.{field_name}", value)
            for field_name, value in live_gains.items()
        )
        lines.append("-- Host active gains --")
        if active_gains is None:
            lines.append("  active_gains unavailable")
        else:
            lines.extend(
                self._format_pair(f"active.{field_name}", active_gains.get(field_name))
                for field_name in ACTIVE_GAIN_FIELDS
            )
        last_current_loop = self.driver.diagnostics.active.last_current_loop_evidence(
            self.driver.oid
        )
        if last_current_loop:
            lines.append("-- Last current-loop run (not persisted) --")
            lines.extend(self._format_last_current_loop_summary(last_current_loop))
            lines.extend(
                self._format_last_current_validation_samples(
                    self.driver.diagnostics.active.last_current_loop_samples(self.driver.oid)
                )
            )
        last_current_loop_hold = self.driver.diagnostics.active.last_current_loop_hold_evidence(
            self.driver.oid
        )
        if last_current_loop_hold:
            lines.append("-- Last sustained-hold gate (not persisted) --")
            lines.extend(self._format_last_current_loop_hold(last_current_loop_hold))
        last_closed_loop_activation = (
            self.driver.diagnostics.active.last_closed_loop_activation_evidence(self.driver.oid)
        )
        if last_closed_loop_activation:
            lines.append("-- Last closed-loop entry (not persisted) --")
            lines.extend(self._format_last_closed_loop_activation(last_closed_loop_activation))
        last_encoder_alignment = self.driver.diagnostics.active.last_encoder_alignment_evidence(
            self.driver.oid
        )
        if last_encoder_alignment:
            lines.append("-- Last encoder alignment (not persisted) --")
            lines.extend(self._format_last_encoder_alignment(last_encoder_alignment))
        last_inductance = self.driver.diagnostics.active.last_inductance_evidence(self.driver.oid)
        if last_inductance:
            lines.append("-- Last inductance evidence (not persisted) --")
            lines.extend(self._format_last_inductance_evidence(last_inductance))

        # -- Comparison --
        lines.append(self._format_block_header("Comparison"))
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
        return (
            f"{reg_name + ':':30} {reg_value:08x} adc_vm_raw="
            f"{fmt_adc_vm_raw(raw, constants, self.driver.state.adc_vm_offset_raw)}"
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
                    f"  WARNING: {field_name} live value unavailable host="
                    f"{self._display_value(host_value)}"
                )
            elif host_value is None:
                warnings.append(
                    f"  WARNING: {field_name} host value unavailable live="
                    f"{self._display_value(live_value)}"
                )
            elif live_value != host_value:
                warnings.append(
                    f"  WARNING: {field_name} mismatch live={self._display_value(live_value)} "
                    f"host={self._display_value(host_value)}"
                )

        if warnings:
            return warnings
        return ["  live register gains match host active_gains"]

    def _format_persisted_inductance_evidence(self) -> list[str]:
        config = self.driver.config
        return [
            self._format_pair(f"config.{field_name}", getattr(config, field_name))
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
            self._format_pair(f"{prefix}.{field_name}", values.get(field_name))
            for field_name in field_names
        ]

    def _format_current_loop_summary(self) -> list[str]:
        config = self.driver.config
        gains_source_name = self._label_code(
            config.identified_current_gains_source, CURRENT_GAINS_SOURCE_NAMES
        )
        gains_tier_name = self._label_code(
            config.identified_current_gains_tier, CURRENT_GAINS_TIER_NAMES
        )
        failure_reason_name = self._label_code(
            config.identified_current_failure_reason, CURRENT_LOOP_FAILURE_REASON_NAMES
        )
        return [
            f"  current_gains_source: {gains_source_name}",
            f"  current_gains_tier: {gains_tier_name}",
            (
                f"  retry_budget_exhausted: "
                f"{self._bool_code(config.identified_current_retry_budget_exhausted)}"
            ),
            f"  failure_reason: {failure_reason_name}",
        ]

    def _format_last_current_loop_summary(self, run: dict) -> list[str]:
        validation_axes = run.get("current_validation_axes")
        flux_sample_count = run.get("flux_validation_sample_count")
        torque_sample_count = run.get("torque_validation_sample_count")
        flux_validation_name = self._axis_validation_label_for_count(
            validation_axes, CURRENT_VALIDATION_AXIS_FLUX, flux_sample_count
        )
        torque_validation_name = self._axis_validation_label_for_count(
            validation_axes, CURRENT_VALIDATION_AXIS_TORQUE, torque_sample_count
        )
        return [
            self._format_pair(
                "last.current_gains_source",
                self._label_code(run.get("gains_source"), CURRENT_GAINS_SOURCE_NAMES),
            ),
            self._format_pair(
                "last.candidate_gains_source",
                self._label_code(run.get("candidate_gains_source"), CURRENT_GAINS_SOURCE_NAMES),
            ),
            self._format_pair(
                "last.axis_split_source",
                self._label_code(run.get("axis_split_source"), AXIS_SPLIT_SOURCE_NAMES),
            ),
            self._format_pair(
                "last.candidate_axis_split_source",
                self._label_code(run.get("candidate_axis_split_source"), AXIS_SPLIT_SOURCE_NAMES),
            ),
            self._format_pair(
                "last.current_gains_tier",
                self._label_code(run.get("gains_tier"), CURRENT_GAINS_TIER_NAMES),
            ),
            self._format_pair(
                "last.candidate_gains_tier",
                self._label_code(run.get("candidate_gains_tier"), CURRENT_GAINS_TIER_NAMES),
            ),
            self._format_pair("last.candidate_flux_p", run.get("candidate_flux_p")),
            self._format_pair("last.candidate_flux_i", run.get("candidate_flux_i")),
            self._format_pair("last.candidate_torque_p", run.get("candidate_torque_p")),
            self._format_pair("last.candidate_torque_i", run.get("candidate_torque_i")),
            self._format_pair("last.candidate_attempt", run.get("candidate_attempt")),
            self._format_pair(
                "last.current_validation",
                f"flux={flux_validation_name} torque={torque_validation_name}",
            ),
            self._format_pair(
                "last.retry_budget_exhausted",
                self._bool_code(run.get("retry_budget_exhausted")),
            ),
            self._format_pair(
                "last.failure_reason",
                self._label_code(run.get("failure_reason"), CURRENT_LOOP_FAILURE_REASON_NAMES),
            ),
        ]

    def _format_last_current_loop_hold(self, evidence: dict) -> list[str]:
        return [
            self._format_hold_pair(
                "last.hold_status",
                self._label_code(evidence.get("hold_status"), CURRENT_LOOP_HOLD_STATUS_NAMES),
            ),
            self._format_hold_pair(
                "last.hold_samples",
                (
                    f"{evidence.get('sample_count')} @ {evidence.get('requested_sample_period_us')}"
                    f" us, elapsed_us={evidence.get('elapsed_us')}"
                ),
            ),
            self._format_hold_pair(
                "last.hold_position",
                (
                    f"span={evidence.get('position_span_count')} drift="
                    f"{evidence.get('position_drift_count')}"
                ),
            ),
            self._format_hold_pair(
                "last.hold_torque",
                (
                    f"mean={evidence.get('torque_mean_count')} rms="
                    f"{evidence.get('torque_rms_count')} span="
                    f"{evidence.get('torque_peak_to_peak_count')} crossings="
                    f"{evidence.get('torque_crossing_count')}"
                ),
            ),
            self._format_hold_pair(
                "last.hold_flux",
                (
                    f"mean={evidence.get('flux_mean_count')} rms={evidence.get('flux_rms_count')} "
                    f"span={evidence.get('flux_peak_to_peak_count')} crossings="
                    f"{evidence.get('flux_crossing_count')}"
                ),
            ),
            self._format_hold_pair(
                "last.hold_status_flags",
                (
                    f"or={evidence.get('status_flags_or')} actionable_count="
                    f"{evidence.get('actionable_status_count')} warnings="
                    f"{evidence.get('warning_flags')}"
                ),
            ),
        ]

    def _format_last_closed_loop_activation(self, evidence: dict) -> list[str]:
        return [
            self._format_hold_pair(
                "last.entry_status",
                self._label_code(evidence.get("entry_status"), CLOSED_LOOP_ACTIVATION_STATUS_NAMES),
            ),
            self._format_hold_pair(
                "last.entry_position",
                f"pos1={evidence.get('position_1')} pos2={evidence.get('position_2')}",
            ),
            self._format_hold_pair(
                "last.entry_drift",
                f"drift={evidence.get('drift_count')} threshold={evidence.get('threshold_count')}",
            ),
            self._format_hold_pair(
                "last.entry_runaway",
                self._bool_code(evidence.get("runaway")),
            ),
        ]

    def _format_last_current_validation_samples(self, samples: dict) -> list[str]:
        lines = []
        for axis_key in ("flux", "torque"):
            for sample in samples.get(axis_key, []):
                label = f"last.current_validation_sample[{axis_key}:{sample.get('sample_index')}]"
                value = (
                    f"role={sample.get('gate_role', 'unknown')} delay_ms="
                    f"{sample.get('sample_delay_ms')} status={sample.get('status')} response="
                    f"{sample.get('positive_response_permille')}/"
                    f"{sample.get('negative_response_permille')} cross="
                    f"{sample.get('cross_axis_permille')} cross_peak="
                    f"{sample.get('cross_axis_peak_permille', sample.get('cross_axis_permille'))} "
                    f"voltage={sample.get('voltage_output_permille')} encoder_delta="
                    f"{sample.get('encoder_delta_counts')} signed_encoder_delta="
                    f"{sample.get('positive_encoder_delta_counts', 0)}/"
                    f"{sample.get('negative_encoder_delta_counts', 0)}"
                )
                lines.append(self._format_pair(label, value))
        return lines

    def _format_last_encoder_alignment(self, evidence: dict) -> list[str]:
        residual = (
            f"{evidence.get('electrical_residual_counts')}/"
            f"{evidence.get('counts_per_electrical_rev')} counts"
        )
        return [
            self._format_pair("last.encoder_alignment_count", evidence.get("encoder_count")),
            self._format_pair("last.encoder_alignment_residual", residual),
            self._format_pair(
                "last.encoder_alignment_stability",
                f"{evidence.get('stability_counts')} counts",
            ),
            self._format_pair(
                "last.encoder_alignment_movement",
                f"{evidence.get('movement_counts')} counts",
            ),
            self._format_pair(
                "last.encoder_alignment_min_movement",
                f"{evidence.get('min_movement_counts')} counts",
            ),
        ]

    def _label_code(self, value: int | None, labels: dict[int, str]) -> str:
        if value is None:
            return "unknown"
        return labels.get(value, f"unknown({int(value)})")

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
        return f"  {name:34} = {self._display_value(value)}"

    def _format_position_tune_provenance(self, config) -> list[str]:
        rotation_distance = config.rotation_distance
        lines = []
        for field_name, label in POSITION_TUNE_FIELDS:
            value = getattr(config, field_name)
            if value is None:
                lines.append(self._format_pair(label, None))
                continue
            mm = value / POSITION_UNITS_PER_REV * rotation_distance
            lines.append(self._format_pair(label, f"{int(value)}u ({mm:.3f}mm)"))
        return lines

    def _format_block_header(self, title: str) -> str:
        return f"== {title} =="

    def _format_hold_pair(self, name: str, value: object | None) -> str:
        return f"  {name:32} = {self._display_value(value)}"

    def _display_value(self, value: object | None) -> str:
        if value is None:
            return "(unset)"
        return str(value)
