"""FOCI register dump workflow."""

from __future__ import annotations

from .commissioning import CURRENT_LOOP_FAILURE_REASON_NAMES
from .config import POSITION_UNITS_PER_REV
from .readiness import readiness_fields, resolve_autotune_readiness
from .registers import (
    DUMP_GROUPS,
    DUMP_NAME_WIDTH,
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

GAIN_TABLE_ROWS: tuple[tuple[str, str, str], ...] = (
    ("flux_p", "pid_flux_p", "p"),
    ("flux_i", "pid_flux_i", "i"),
    ("torque_p", "pid_torque_p", "p"),
    ("torque_i", "pid_torque_i", "i"),
    ("velocity_p", "pid_velocity_p", "p"),
    ("velocity_i", "pid_velocity_i", "i"),
    ("position_p", "pid_position_p", "p"),
    ("position_i", "pid_position_i", "i"),
    ("velocity_limit", "pid_velocity_limit", "raw"),
)

FILTER_FIELDS: tuple[tuple[str, str], ...] = (
    ("velocity", "velocity_filter_hz"),
    ("torque", "torque_filter_hz"),
    ("position", "position_filter_hz"),
    ("flux", "flux_filter_hz"),
)

KV_WIDTH = 26

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

POSITION_TUNE_FIELDS: tuple[tuple[str, str], ...] = (
    ("autotune_position_bound_units", "bound"),
    ("autotune_position_homing_peak_units", "homing_peak"),
    ("autotune_position_motion_cruise_units", "motion_cruise"),
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

        deadline = reactor.monotonic() + 5.0
        while not self._dump_complete and reactor.monotonic() < deadline:
            reactor.pause(reactor.monotonic() + 0.05)

        return self._dump_complete

    def dump_registers(self, gcmd) -> None:
        """Handler for DUMP_FOCI and DUMP_TMC GCode commands.

        ``TUNING=1`` appends host-derived read-only tuning analysis using the same dump response.
        """
        include_tuning = bool(gcmd.get_int("TUNING", 0, minval=0, maxval=1))
        if not self._request_dump_values():
            gcmd.respond_info("FOCI register dump timed out")
            return

        rule = "=" * 64
        lines: list[str] = [rule, f"FOCI {self.driver.stepper_name}", rule]
        for group_name, regs in DUMP_GROUPS:
            lines.append(f"---------- {group_name} ----------")
            for reg_name in regs:
                addr = REGISTERS[reg_name]
                if addr in self._dump_buffer:
                    val = self._dump_buffer[addr]
                    lines.append(self._pretty_format_register(reg_name, val))
                else:
                    lines.append(f"{reg_name + ':':{DUMP_NAME_WIDTH}}(not in dump)")

        lines.extend(self._format_firmware_state())

        if include_tuning:
            lines.extend(self._format_tuning_analysis())

        gcmd.respond_info("\n".join(lines))

    def _format_firmware_state(self) -> list[str]:
        buffer = self._dump_buffer
        latched = buffer.get(REGISTERS["VELOCITY_FF_CLAMP_LATCHED"])
        count = buffer.get(REGISTERS["VELOCITY_FF_CLAMP_COUNT"])
        stall = self.driver.protocol.query_stall()
        return [
            "---------- Firmware state (not chip registers) ----------",
            f"velocity_ff_clamp: latched={'?' if latched is None else latched} "
            f"count={'?' if count is None else count}",
            f"homing: clamp_active={stall['clamp_active']} last_stall(latched={stall['latched']} "
            f"peak_error_units={stall['peak_error_units']} trigger_tick={stall['trigger_tick']})",
        ]

    def _format_tuning_analysis(self) -> list[str]:
        config = self.driver.config
        state = self.driver.state
        active_gains = state.active_gains
        live_gains = self._live_gain_values()
        readiness = resolve_autotune_readiness(
            self.driver,
            live_current_gains={
                name: live_gains.get(name) for name in ("flux_p", "flux_i", "torque_p", "torque_i")
            },
        )
        sync_summary, sync_warnings = self._compare_live_to_host(live_gains, active_gains)
        persisted_status = config.autotune_status or "uncommissioned"

        rule = "=" * 64
        lines = [
            "",
            rule,
            f"FOCI {self.driver.stepper_name} tuning analysis",
            rule,
            f"verdict: {persisted_status} (persisted) / {state.runtime_status} (runtime)"
            f" | readiness: {readiness.result} | {sync_summary}",
            *sync_warnings,
        ]

        lines.append(self._section_header("Autotune status"))
        lines.append(self._kv("autotune_status", self._display_value(config.autotune_status)))
        lines.append(self._kv("runtime_status", self._display_value(state.runtime_status)))
        lines.append(self._kv("active_gains_present", "yes" if active_gains is not None else "no"))
        lines.append(self._kv("autotune_profile", self._display_value(config.autotune_profile)))
        lines.append(self._kv("autotune_mode", self._display_value(config.autotune_mode)))
        if persisted_status != state.runtime_status:
            lines.append(
                f"WARNING: autotune_status/runtime_status divergence persisted="
                f"{persisted_status} validated={state.runtime_status}"
            )

        lines.append(self._section_header("Readiness"))
        lines.extend(self._kv(name, value) for name, value in readiness_fields(readiness))

        lines.append(self._section_header("Gains"))
        lines.extend(self._format_gain_table(live_gains, active_gains))

        lines.append(self._section_header("Identified model (count-space, not physical units)"))
        lines.extend(self._format_identified_model())

        lines.append(self._section_header("Velocity tune provenance"))
        lines.append(self._format_velocity_tune_provenance())
        lines.append(self._section_header("Position tune provenance"))
        lines.append(self._format_position_tune_provenance(config))

        last_current_loop = self.driver.diagnostics.active.last_current_loop_evidence(
            self.driver.oid
        )
        if last_current_loop:
            lines.append(self._section_header("Last current-loop run (not persisted)"))
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
            lines.append(self._section_header("Last sustained-hold gate (not persisted)"))
            lines.extend(self._format_last_current_loop_hold(last_current_loop_hold))
        last_closed_loop_activation = (
            self.driver.diagnostics.active.last_closed_loop_activation_evidence(self.driver.oid)
        )
        if last_closed_loop_activation:
            lines.append(self._section_header("Last closed-loop entry (not persisted)"))
            lines.extend(self._format_last_closed_loop_activation(last_closed_loop_activation))
        last_inductance = self.driver.diagnostics.active.last_inductance_evidence(self.driver.oid)
        if last_inductance:
            lines.append(self._section_header("Last inductance evidence (not persisted)"))
            lines.extend(self._format_last_inductance_evidence(last_inductance))
        return lines

    def _section_header(self, title: str) -> str:
        return f"---------- {title} ----------"

    def _kv(self, name: str, value: object) -> str:
        return f"{name + ':':{KV_WIDTH}}{value}"

    def _format_gain_table(
        self,
        live_gains: dict[str, int | None],
        active_gains: dict[str, int | None] | None,
    ) -> list[str]:
        config = self.driver.config

        def cell(value: int | None) -> str:
            return "-" if value is None else str(value)

        def scaled(value: int | None, kind: str) -> str:
            if value is None:
                return "-"
            if kind == "p":
                return f"{value} ({value / 256:.3f})"
            if kind == "i":
                return f"{value} ({value / 4096:.4f})"
            return str(value)

        lines = [f"{'gain':16}{'live (scaled)':20}{'config':>8}{'active':>10}"]
        for field_name, config_field, kind in GAIN_TABLE_ROWS:
            active = None if active_gains is None else active_gains.get(field_name)
            lines.append(
                f"{field_name:16}{scaled(live_gains.get(field_name), kind):20}"
                f"{cell(getattr(config, config_field)):>8}{cell(active):>10}"
            )
        if active_gains is not None:
            filters = " ".join(
                f"{label}={cell(active_gains.get(field_name))}"
                for label, field_name in FILTER_FIELDS
            )
            lines.append(self._kv("filters_hz", filters))
        return lines

    def _format_identified_model(self) -> list[str]:
        config = self.driver.config
        show = self._display_value
        tau_e_us = config.identified_tau_e_us
        tau_text = show(tau_e_us) if tau_e_us is None else f"{tau_e_us} ({tau_e_us / 1000:.2f} ms)"
        source = self._coded(config.identified_current_gains_source, CURRENT_GAINS_SOURCE_NAMES)
        tier = self._coded(config.identified_current_gains_tier, CURRENT_GAINS_TIER_NAMES)
        retry = self._bool_code(config.identified_current_retry_budget_exhausted)
        failure = self._coded(
            config.identified_current_failure_reason, CURRENT_LOOP_FAILURE_REASON_NAMES
        )
        current_loop = (
            f"gains_source={source} gains_tier={tier} retry_budget_exhausted={retry}"
            f" failure_reason={failure}"
        )
        reactance = show(config.identified_l_reactance_count_ratio_milli)
        return [
            self._kv(
                "resistance",
                f"r_count_milli={show(config.identified_r_count_milli)}"
                f" r_count_slope_milli={show(config.identified_r_count_slope_milli)}",
            ),
            self._kv(
                "electrical",
                f"lambda_us={show(config.identified_lambda_us)} tau_e_us={tau_text}"
                f" theta_e_us={show(config.identified_theta_e_us)}"
                f" theta_source={show(config.identified_theta_source)}",
            ),
            self._kv("bandwidth_hz", show(config.identified_bandwidth_hz)),
            self._kv("inner_warning_flags", show(config.identified_inner_warning_flags)),
            self._kv(
                "inductance",
                f"l_source={show(config.identified_l_source)}"
                f" l_reactance_count_ratio_milli={reactance}"
                f" l_saliency_status={show(config.identified_l_saliency_status)}",
            ),
            self._kv("current_loop", current_loop),
        ]

    def _format_velocity_tune_provenance(self) -> str:
        config = self.driver.config
        show = self._display_value
        probed = config.autotune_probed_velocity_mrev_s
        probed_text = show(probed) if probed is None else f"{probed} ({probed / 1000:.3f} rev/s)"
        lower = config.autotune_band_lower_percent
        upper = config.autotune_band_upper_percent
        band_text = "(unset)" if lower is None or upper is None else f"{lower}..{upper}%"
        return (
            f"probed_velocity_mrev_s={probed_text} band={band_text}"
            f" d_eq_q={show(config.autotune_d_eq_q)}"
            f" confidence_q={show(config.autotune_confidence_q)}"
            f" band_position_q={show(config.autotune_band_position_q)}"
        )

    def _coded(self, value: int | None, labels: dict[int, str]) -> str:
        if value is None:
            return "unknown"
        return f"{labels.get(value, 'unknown')}({int(value)})"

    def _pretty_format_register(self, reg_name: str, reg_value: int) -> str:
        if reg_name == "PID_POSITION_ACTUAL":
            return self._format_position_actual(reg_value)
        if reg_name != "ADC_VM_RAW":
            return self.fields.pretty_format(reg_name, reg_value)

        constants = {}
        get_constants = getattr(self.driver.mcu, "get_constants", None)
        if get_constants is not None:
            constants = get_constants()
        raw = self.fields.get_field("adc_vm_raw", reg_name, reg_value)
        return (
            f"{reg_name + ':':{DUMP_NAME_WIDTH}}{reg_value:08x}  adc_vm_raw="
            f"{fmt_adc_vm_raw(raw, constants, self.driver.state.adc_vm_offset_raw)}"
        )

    def _format_position_actual(self, reg_value: int) -> str:
        line = self.fields.pretty_format("PID_POSITION_ACTUAL", reg_value)
        target = self._dump_buffer.get(REGISTERS["PID_POSITION_TARGET"])
        if target is None:
            return line
        actual = self.fields.get_field("position_actual", "PID_POSITION_ACTUAL", reg_value)
        target = self.fields.get_field("position_target", "PID_POSITION_TARGET", target)
        return f"{line} (error={target - actual})"

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

    def _compare_live_to_host(
        self,
        live_gains: dict[str, int | None],
        active_gains: dict[str, int | None] | None,
    ) -> tuple[str, list[str]]:
        if active_gains is None:
            return "host active gains unavailable", []

        differing: list[str] = []
        warnings: list[str] = []
        for field_name in COMPARE_GAIN_FIELDS:
            live_value = live_gains.get(field_name)
            host_value = active_gains.get(field_name)
            if live_value is None:
                warnings.append(
                    f"WARNING: {field_name} live value unavailable host="
                    f"{self._display_value(host_value)}"
                )
            elif host_value is None:
                warnings.append(
                    f"WARNING: {field_name} host value unavailable live="
                    f"{self._display_value(live_value)}"
                )
            elif live_value != host_value:
                warnings.append(
                    f"WARNING: {field_name} mismatch live={self._display_value(live_value)} "
                    f"host={self._display_value(host_value)}"
                )
            else:
                continue
            differing.append(field_name)

        if differing:
            return f"live registers differ from host active gains: {' '.join(differing)}", warnings
        return "live registers match host active gains", warnings

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

    def _format_position_tune_provenance(self, config) -> str:
        values = {name: getattr(config, field) for field, name in POSITION_TUNE_FIELDS}
        if all(value is None for value in values.values()):
            return "not run (bound, homing peak, motion cruise all unset)"
        rotation_distance = config.rotation_distance
        parts = []
        for name, value in values.items():
            if value is None:
                parts.append(f"{name}=(unset)")
                continue
            mm = value / POSITION_UNITS_PER_REV * rotation_distance
            parts.append(f"{name}={int(value)}u ({mm:.3f}mm)")
        return " ".join(parts)

    def _format_hold_pair(self, name: str, value: object | None) -> str:
        return f"  {name:32} = {self._display_value(value)}"

    def _display_value(self, value: object | None) -> str:
        if value is None:
            return "(unset)"
        return str(value)
