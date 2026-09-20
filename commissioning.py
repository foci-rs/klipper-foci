"""Commissioning workflow for FOCI host commands."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ._vocabulary_generated import PHASE_NAMES
from .constants import COMMISSION_CANCEL_GRACE_PERIOD_S, ELECTRICAL_ID_WAIT_TIMEOUT_S
from .report import report_detail, report_summary

log = logging.getLogger(__name__)

COMMISSION_REASON_NAMES: dict[int, str] = {
    1: "motor already enabled",
    2: "no current detected",
    3: "SPI communication error",
    4: "ADC calibration fault",
    5: "coil connectivity fault",
    6: "phase wiring fault",
    7: "encoder fault",
    8: "electrical identification failed",
    9: "current validation failed",
    10: "mechanical identification failed",
    11: "velocity validation failed",
    12: "position tune failed",
    13: "encoder not aligned",
    14: "shutdown requested",
    15: "commissioning already running",
    16: "command queue full",
    17: "safety envelope violation",
    18: "CHIP_RESET_DETECTED (TMC4671 lost state, re-commission required)",
    19: "resistance identification failed",
    20: "resistance ADC not ready",
    21: "resistance diagnostic not armed",
    22: "resistance wrong power stage",
    23: "resistance insufficient linear points",
    24: "resistance thermal drift",
    25: "resistance electrical axis mismatch",
    26: "resistance high fit residual",
    27: "resistance invalid motor type",
    28: "resistance peak current exceeded",
    29: "resistance unsupported profile",
    30: "resistance parameter out of bounds",
    31: "resistance measurement envelope unsupported",
    32: "inductance open-loop velocity timeout",
    33: "inductance AC capture rejected",
    34: "inductance encoder motion during AC capture",
    35: "inductance capture window incomplete",
    36: "inductance realized frequency out of range",
    37: "inductance quadrature current too low",
    38: "inductance missing resistance evidence",
    39: "inductance reactance calculation invalid",
    40: "inductance drift calculation invalid",
    41: "inductance saliency calculation invalid",
    42: "sustained hold validation failed",
    43: "closed-loop entry stability failed",
    44: "electrical model had no usable samples",
    45: "electrical model scale rounded to zero",
    46: "electrical theta too large for measured tau",
    47: "invalid_schedule",
    48: "resistance_timing",
    49: "resistance_timeout",
    50: "inductance_timing",
    51: "delay_timing",
    52: "velocity sweep analysis overrun",
    53: "velocity rest not confirmed",
    54: "invalid current limit",
    55: "evidence buffer full",
    56: "rung index out of range",
    57: "frozen plan input changed mid-campaign",
    58: "rung-origin recovery planning failed",
    59: "encoder domain invalid",
    60: "missing capture state",
    61: "search grid invalid",
    62: "target rate invalid",
    63: "zero-elapsed encoder sample",
    64: "campaign plan could not be constructed",
    65: "velocity-integral authority denied",
    66: "discovery selected no in-band ladder",
    67: "sampling grid period is zero",
    68: "grid deadline advanced before it was due",
    69: "grid deadline arithmetic overflowed",
    70: "safety primitive already open",
    71: "primitive start timestamp is in the future",
    72: "origin recovery start offset mismatch",
    73: "resistance nonpositive slope (reversed current polarity or sign error)",
    74: "cancelled",
    75: "safe-state cleanup incomplete",
    76: "inductance current envelope exceeded",
    79: "pid gain invalid",
    80: "malformed interval",
    81: "missing rate table entry",
    82: "mismatched observation",
    83: "elapsed time conversion invalid",
    84: "velocity envelope ceiling zero",
    85: "velocity envelope exceeds ceiling",
    86: "safety timing gap invalid",
    87: "net displacement overflow",
    88: "capture timing: time moved backwards or violated poll ordering",
    89: "capture timing: deadline or interval arithmetic overflowed",
    90: "capture timing: sample-start lateness exceeded one quarter period",
    91: "capture timing: sample service exceeded one requested period",
    92: "capture timing: missed more sample slots than permitted",
    93: "capture timing: too many consecutive missed sample slots",
    94: "capture timing: SPI time exceeded poll wall time",
    95: "capture timing: telemetry counter or duration saturated",
    96: "capture timing: timestamp offset out of range",
    97: "capture buffer desync (internal invariant violation)",
    98: "velocity confidence estimation failed",
    99: "velocity rate calculation failed",
    100: "velocity conversion invalid",
    101: "velocity disturbance calculation failed",
    102: "velocity block geometry invalid",
    103: "velocity interval invalid",
    104: "velocity lag-one evaluation failed",
    105: "velocity analysis poll failed",
    106: "velocity unexpected poll variant",
    107: "velocity wrong direction",
    108: "velocity invalid evidence",
    109: "velocity integral plan invalid",
    110: "gain floor insufficient linear points",
    111: "gain floor non-positive slope",
    112: "gain floor current fit rejected (legacy, not produced by current firmware)",
    113: "gain floor insufficient coverage",
    114: "gain floor peak current exceeded",
    115: "gain floor motion envelope exceeded",
    116: "gain floor velocity gain unrepresentable",
    117: "gain floor position gain unrepresentable",
}

_FAILURE_PHRASE_OVERRIDES: dict[int, str] = {
    18: "the TMC4671 lost its calibration state and needs to be re-commissioned",
    47: "an invalid measurement schedule",
    48: "a resistance-measurement timing fault",
    49: "a resistance-measurement timeout",
    50: "an inductance-measurement timing fault",
    51: "a measurement delay timing fault",
    73: "a resistance measurement with reversed current polarity or a sign error",
    97: "an internal capture-buffer synchronization fault",
    110: "not enough clean position samples during the gain-floor measurement to fit a response",
    111: "the gain-floor measurement showed zero, negative, or wrong-direction acceleration",
    112: "legacy code from older firmware: the gain floor had no usable current-loop bandwidth",
    113: "the gain-floor measurement missed a sample deadline before it could finish",
    114: "motor current exceeded its safety limit during the gain-floor measurement",
    115: "the motor moved further than allowed during the gain-floor measurement",
    116: "the computed gain-floor velocity gain is outside the range the firmware can represent",
    117: "the computed gain-floor position gain is outside the range the firmware can represent",
}


def operator_failure_phrase(code: int) -> str:
    """Console-safe FAILED phrase for a COMMISSION_REASON_NAMES code.

    Plain English only: no doc links, no raw evidence, no enum-symbol
    names. Used exclusively for the report_summary FAILED line -- never for
    gcmd.error()/command_error() text, which keeps using
    format_commission_failure()/COMMISSION_REASON_NAMES directly, unchanged.
    """
    if code in _FAILURE_PHRASE_OVERRIDES:
        return _FAILURE_PHRASE_OVERRIDES[code]
    return COMMISSION_REASON_NAMES.get(code, f"unknown error {int(code)}")


# Error codes for which the failure message should point at a dedicated
# troubleshooting doc instead of just the bare error name.
TROUBLESHOOTING_DOC_LINKS: dict[int, str] = dict.fromkeys(
    [*range(19, 32), 73], "docs/troubleshooting/resistance-identification.md"
)

# Resistance-identification failures that are not operator-remediable by
# changing a printer setting. The firmware could not find a safe resistance
# measurement envelope, or a safety backstop rejected the envelope it tried.
RESISTANCE_MEASUREMENT_UNSUPPORTED_CODES: frozenset[int] = frozenset({23, 28, 31})

# Error codes that indicate a hard-disable fault: firmware has disabled the
# motor and cleared its state. The host must sync its enable line and clear
# is_calibrated.
HARD_FAULT_CODES: frozenset[int] = frozenset({3, 9, 14, 17, 42})

INNER_WARNING_GAIN_FLOOR_SKIPPED = 1 << 7

# Bit-to-name mapping for the firmware-side `inner_warning_flags` bitfield.
INNER_WARNING_FLAG_NAMES: list[tuple[int, str]] = [
    (1 << 0, "coil R mismatch"),
    (1 << 1, "coil control-model tau mismatch"),
    (1 << 3, "theta/tau ratio"),
    (1 << 5, "current gains fell back to defaults"),
    (1 << 6, "host-default confidence (no fresh measurement)"),
    (INNER_WARNING_GAIN_FLOOR_SKIPPED, "gain floor skipped, outer gains are the built-in defaults"),
]

PROFILE_MAP: dict[str, int] = {
    "conservative": 0,
    "balanced": 1,
    "stiff": 2,
}

ELECTRICAL_ID_DETAIL_NAMES: dict[int, str] = {
    1: "excitation",
    2: "coil A resistance",
    3: "coil B resistance",
    20: "no usable per-coil samples",
    21: "only one coil produced non-zero control-model tau",
    22: "model scale rounded to zero",
    23: "resistance below short threshold",
    24: "resistance above open threshold",
    25: "coil resistance mismatch",
    26: "coil control-model tau mismatch",
    28: "legacy inductance fit rejected",
    29: "transport delay too large",
    30: "legacy inductance fit point",
    31: "legacy inductance fit correction",
    32: "inductance frequency out of range",
    33: "inductance AC capture rejected",
    41: "inductance status rejected",
    47: "invalid_schedule",
    48: "resistance_timing",
    49: "resistance_timeout",
    50: "inductance_timing",
    51: "delay_timing",
}

TIMING_METHOD_NAMES: dict[int, str] = {
    0: "resistance",
    1: "inductance",
    2: "delay",
}

TIMING_STATUS_NAMES: dict[int, str] = {
    0: "not-run",
    1: "accepted",
    2: "rejected",
}

TIMING_REJECTION_ERROR_CODES: dict[int, int] = {
    0: 48,
    1: 50,
    2: 51,
}

INDUCTANCE_CAPTURE_REJECT_REASON_NAMES: dict[int, str] = {
    1: "phi interval invalid",
    2: "zero phi delta",
    3: "frame accumulator",
    4: "saliency accumulator",
    5: "first-half accumulator",
    6: "second-half accumulator",
    7: "elapsed interpolation",
    8: "saliency bracket invariant",
    9: "saliency average below bracket",
    10: "saliency average above bracket",
}

CURRENT_LOOP_FAILURE_REASON_NAMES: dict[int, str] = {
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
    17: "closed_loop_activation",
}

CURRENT_AXIS_STATUS_NAMES: dict[int, str] = {
    0: "pass",
    1: "wrong sign",
    2: "low response",
    3: "high response",
    4: "cross-axis coupling",
    5: "saturation",
    6: "motion",
    7: "status flags",
    8: "zero target",
}


def _decode_coil_point(packed: int) -> tuple[str, int]:
    coil = "A" if ((packed >> 4) & 0xF) == 0 else "B"
    point = packed & 0xF
    return coil, point


def _signed_u32(value: int) -> int:
    return value if value < 0x8000_0000 else value - 0x1_0000_0000


def _signed_u16(value: int) -> int:
    value &= 0xFFFF
    return value if value < 0x8000 else value - 0x1_0000


def _decode_u16_pair(packed: int) -> tuple[int, int]:
    return (packed >> 16) & 0xFFFF, packed & 0xFFFF


def _decode_i16_pair(packed: int) -> tuple[int, int]:
    high, low = _decode_u16_pair(packed)
    return _signed_u16(high), _signed_u16(low)


def format_commission_detail(detail: dict) -> str:
    """Format one structured commissioning diagnostic detail."""
    phase_name = PHASE_NAMES.get(detail["phase"], f"Phase {int(detail['phase'])}")
    code = detail["code"]
    name = ELECTRICAL_ID_DETAIL_NAMES.get(code, f"diagnostic {int(code)}")
    value0 = detail["value0"]
    value1 = detail["value1"]
    value2 = detail["value2"]
    if detail["phase"] == 2 and code in (1, 2):
        coil = "A" if code == 1 else "B"
        expected = value0 if value0 < 0x8000 else value0 - 0x10000
        other = value1 if value1 < 0x8000 else value1 - 0x10000
        status = "FAIL" if detail["status"] else "PASS"
        return (
            f"{phase_name}: coil {coil} sample {status} (expected={int(expected)} counts, other="
            f"{int(other)} counts, raw=0x{value2:08x})"
        )
    if detail["phase"] == 4 and code == 1:
        return (
            f"{phase_name}: ABN read unstable (samples={int(value0)}/{int(value1)}/{int(value2)})"
        )
    if detail["phase"] == 4 and code == 2:
        status = "FAIL" if detail["status"] else "PASS"
        return (
            f"{phase_name}: direction sweep {status} (start={int(value0)}, end={int(value1)}, "
            f"delta={int(value2)})"
        )
    if detail["phase"] == 4 and code == 40:
        expected = _signed_u32(value1)
        observed = _signed_u32(value2)
        wrong_direction = ", wrong direction" if expected * observed < 0 else ""
        return (
            f"{phase_name}: encoder direction FAIL (commanded={int(value0)} PHI_E, "
            f"expected={int(expected)} counts, observed={int(observed)} counts"
            f"{wrong_direction})"
        )
    if detail["phase"] == 4 and code == 41:
        min_counts = _signed_u32(value0)
        max_counts = _signed_u32(value1)
        return (
            f"{phase_name}: encoder direction bounds (accepted={int(min_counts)}.."
            f"{int(max_counts)} counts, pole_pairs={int(value2)})"
        )
    if detail["phase"] == 16 and code == 1:
        status = "FAIL" if detail["status"] else "PASS"
        return (
            f"{phase_name}: alignment movement {status} (movement={int(value0)}, min={int(value1)}"
            f", stability={int(value2)})"
        )
    if detail["phase"] == 17 and code == 1:
        kind = "runaway" if detail["status"] == 2 else "drift"
        position_1 = value0 if value0 < 0x8000_0000 else value0 - 0x1_0000_0000
        position_2 = value1 if value1 < 0x8000_0000 else value1 - 0x1_0000_0000
        return (
            f"{phase_name}: {kind} FAIL (position_1={int(position_1)}, "
            f"position_2={int(position_2)}, drift={int(value2)})"
        )
    if code == 1:
        return (
            f"{phase_name}: {name} (voltage_count={int(value0)}, legacy_didt_cycles={int(value1)}, "
            f"sample_period={int(value2)}us)"
        )
    if code in (2, 3):
        return (
            f"{phase_name}: {name} (avg_current={int(value0)} counts, r_count_milli={int(value1)}, "
            f"samples={int(value2)})"
        )
    if code in (25, 26):
        return f"{phase_name}: {name} ({int(value0)} permille, limit={int(value1)})"
    if code == 28:
        coil = "A" if value0 == 0 else "B"
        return (
            f"{phase_name}: {name} (coil={coil}, usable_points={int(value1)}, selected_mask=0x"
            f"{value2:04x})"
        )
    if code == 30:
        coil, point = _decode_coil_point(value0)
        return (
            f"{phase_name}: {name} (coil={coil} point={int(point)}, ud={int(value1)}, avg_delta="
            f"{int(value2)} counts)"
        )
    if code == 31:
        coil, point = _decode_coil_point(value0)
        return (
            f"{phase_name}: {name} (coil={coil} point={int(point)}, samples={int(value1)}, "
            f"effective_ud={int(_signed_u32(value2))})"
        )
    if code == 32:
        return (
            f"{phase_name}: {name} (realized_frequency_millihz={int(value0)}, elapsed_us="
            f"{int(value1)}, samples={int(value2)})"
        )
    if code == 33:
        reason = INDUCTANCE_CAPTURE_REJECT_REASON_NAMES.get(value0, f"reason {int(value0)}")
        if value0 in (1, 2):
            previous_phi, current_phi = _decode_u16_pair(value2)
            return (
                f"{phase_name}: {name} (reason={reason}, samples={int(value1)}, previous_phi="
                f"{int(previous_phi)}, current_phi={int(current_phi)})"
            )
        if value0 in (3, 4, 5, 6):
            id_count, iq_count = _decode_i16_pair(value2)
            return (
                f"{phase_name}: {name} (reason={reason}, samples={int(value1)}, id={int(id_count)}"
                f", iq={int(iq_count)})"
            )
        if value0 == 7:
            previous_elapsed_us, current_elapsed_us = _decode_u16_pair(value2)
            return (
                f"{phase_name}: {name} (reason={reason}, samples={int(value1)}, "
                f"previous_elapsed_us={int(previous_elapsed_us)}, current_elapsed_us="
                f"{int(current_elapsed_us)})"
            )
        if value0 == 8:
            x_d, x_q = _decode_u16_pair(value2)
            return (
                f"{phase_name}: {name} (reason={reason}, samples={int(value1)}, x_d={int(x_d)}, "
                f"x_q={int(x_q)})"
            )
        if value0 in (9, 10):
            x_average, bound = _decode_u16_pair(value2)
            bound_name = "low" if value0 == 9 else "high"
            return (
                f"{phase_name}: {name} (reason={reason}, saliency_permille={int(value1)}, "
                f"x_average={int(x_average)}, {bound_name}_bound={int(bound)})"
            )
        return f"{phase_name}: {name} (reason={reason}, samples={int(value1)}, aux={int(value2)})"
    if code == 41:
        return (
            f"{phase_name}: {name} (status_flags_or=0x{int(value0):08x}, "
            f"entry_mask=0x{int(value1):02x})"
        )
    if code in (23, 24):
        return f"{phase_name}: {name} (r_count_milli={int(value0)}, limit={int(value1)})"
    if code == 22:
        return f"{phase_name}: {name} (l_count_micro={int(value0)})"
    if code == 29:
        return f"{phase_name}: {name} (theta_us={int(value0)}, tau_us={int(value1)})"
    if value0 or value1 or value2:
        return (
            f"{phase_name}: {name} (value0={int(value0)}, value1={int(value1)}, value2="
            f"{int(value2)})"
        )
    return f"{phase_name}: {name}"


def _encoder_direction_sweep_failed(details: list[dict]) -> bool:
    """True when the collected details include a failed direction-sweep
    result (phase 4/"EncoderCheck", code 2, DIAG_ENCODER_DIRECTION_RESULT,
    status != 0) -- the specific diagnostic format_encoder_direction_failure
    interprets. A phase-4 detail of any other code (e.g. code 1, unstable
    encoder read) is a different failure and must not take this path.
    """
    return any(
        detail["phase"] == 4 and detail["code"] == 2 and detail["status"] != 0 for detail in details
    )


def format_encoder_direction_failure(details: list[dict]) -> str:
    """Build the FAILED summary phrase for a failed direction-sweep phase.

    Only call this when _encoder_direction_sweep_failed(details) is True.

    Correlates code 2 (DIAG_ENCODER_DIRECTION_RESULT, unsigned delta only)
    with code 40 (DIAG_ENCODER_DIRECTION_EXPECTED, signed expected/observed),
    which the firmware pushes alongside code 2 whenever pole_pairs != 0.
    """
    generic = "encoder direction sweep didn't move as expected"
    expected_detail = next((d for d in details if d["phase"] == 4 and d["code"] == 40), None)
    if expected_detail is None:
        return generic
    expected = _signed_u32(expected_detail["value1"])
    observed = _signed_u32(expected_detail["value2"])
    if expected * observed < 0:
        return "encoder_direction looks inverted"
    return generic


def format_inner_warning_flags(flags: int) -> str:
    """Decode an inner_warning_flags bitfield into warning names."""
    names = [name for bit, name in INNER_WARNING_FLAG_NAMES if flags & bit]
    return ", ".join(names) if names else "none"


def decode_timing_summary(packed: int) -> dict:
    """Decode the terminal timing bitfield emitted by commissioning."""
    return {
        "statuses": {method: (packed >> (method * 2)) & 0x03 for method in range(3)},
        "rejected": bool(packed & (1 << 6)),
        "overflowed": bool(packed & (1 << 7)),
        "missed_samples": (packed >> 8) & 0xFF,
        "max_lateness_us": (packed >> 16) & 0xFFFF,
    }


def format_timing_evidence(method_name: str, evidence: dict) -> str:
    """Format one detailed timing reply without changing microsecond units."""
    status = evidence["status"]
    status_name = TIMING_STATUS_NAMES.get(status, f"unknown({int(status)})")
    return (
        f"timing {method_name}: status={status_name} period_us="
        f"{int(evidence['requested_period_us'])} valid={int(evidence['valid_samples'])} missed="
        f"{int(evidence['missed_samples'])} max_lateness_us={int(evidence['max_lateness_us'])} "
        f"max_interval_us={int(evidence['max_interval_us'])} max_poll_wall_us="
        f"{int(evidence['max_poll_wall_us'])} max_spi_wall_us={int(evidence['max_spi_wall_us'])}"
    )


def format_commission_error_name(code: int) -> str:
    """Render a commission status code's name, with a doc link if one exists."""
    detail_name = format_commission_error_detail_name(code)
    if code in RESISTANCE_MEASUREMENT_UNSUPPORTED_CODES:
        error_name = (
            f"resistance measurement unsupported by current firmware (detail: {detail_name})"
        )
    else:
        error_name = detail_name
    doc_link = TROUBLESHOOTING_DOC_LINKS.get(code)
    if doc_link is not None:
        return f"{error_name} (see {doc_link})"
    return error_name


def format_commission_error_detail_name(code: int) -> str:
    """Render the precise firmware status code name without operator grouping."""
    return COMMISSION_REASON_NAMES.get(code, f"UNKNOWN({int(code)})")


def _format_current_axis_sample(sample: dict) -> str:
    status = sample.get("status")
    status_name = CURRENT_AXIS_STATUS_NAMES.get(status, f"status {status}")
    return (
        f"{status_name} at delay={sample.get('sample_delay_ms')}ms response="
        f"{sample.get('positive_response_permille')}/{sample.get('negative_response_permille')} "
        f"permille cross={sample.get('cross_axis_permille')} permille cross_peak="
        f"{sample.get('cross_axis_peak_permille', sample.get('cross_axis_permille'))} permille "
        f"voltage={sample.get('voltage_output_permille')} permille encoder_delta="
        f"{sample.get('encoder_delta_counts')} status_flags_or=0x"
        f"{sample.get('status_flags_or', 0):08x}"
    )


def _first_current_gate_failure(samples: Sequence[dict]) -> dict | None:
    for sample in samples:
        if sample.get("gate_role") == "gate" and sample.get("status", 0) != 0:
            return sample
    for sample in samples:
        if sample.get("status", 0) != 0:
            return sample
    return None


def format_current_loop_failure_summary(
    run: dict | None, samples: dict[str, list[dict]] | None = None
) -> str | None:
    """Format subordinate current-loop failure evidence for live errors."""
    if not run:
        return None
    reason = run.get("failure_reason")
    if reason in (None, 0):
        return None
    reason_name = CURRENT_LOOP_FAILURE_REASON_NAMES.get(reason, f"reason {reason}")
    parts = [reason_name]
    axis_key = "flux" if reason == 4 else "torque" if reason == 5 else None
    if samples is not None and axis_key is not None:
        sample = _first_current_gate_failure(samples.get(axis_key, []))
        if sample is not None:
            parts.append(_format_current_axis_sample(sample))
    if run.get("retry_budget_exhausted"):
        parts.append("retry budget exhausted")
    parts.append(
        f"candidate_attempt={run.get('candidate_attempt')} candidate_flux="
        f"{run.get('candidate_flux_p')}/{run.get('candidate_flux_i')} candidate_torque="
        f"{run.get('candidate_torque_p')}/{run.get('candidate_torque_i')}"
    )
    return "; ".join(parts)


class CommissioningWorkflow:
    """Run commissioning and track commissioning responses."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.last_phase_id: int | None = None
        self.result: dict | None = None
        self.done = False
        self.error_code = 0
        self.details: list[dict] = []
        self.timing_by_method: dict[int, dict] = {}

    def clear_details(self) -> None:
        """Clear structured commissioning diagnostic details."""
        self.details = []

    def handle_commission_phase(self, params: dict) -> None:
        """Handle foci_commission_phase messages from firmware."""
        phase_id = params.get("phase", 0)
        status = params.get("status", 0)
        if phase_id > 0 and status == 0:
            self.last_phase_id = phase_id
            phase_name = PHASE_NAMES.get(phase_id, f"Phase {int(phase_id)}")
            gcode = self.driver.printer.lookup_object("gcode")
            active_label = self.driver.state.active_label or "commissioning"
            report_summary(gcode, f"FOCI {self.driver.stepper_name} {active_label}: {phase_name}")
        elif phase_id == 0 and status != 0:
            self.error_code = status

    def handle_commission_result(self, params: dict) -> None:
        """Handle foci_commission_result from firmware."""
        self.result = params
        self.done = True

    def handle_commission_detail(self, params: dict) -> None:
        """Collect structured commissioning diagnostic detail."""
        self.details.append(
            {
                "phase": params["phase"],
                "code": params["code"],
                "status": params["status"],
                "value0": params["value0"],
                "value1": params["value1"],
                "value2": params["value2"],
            }
        )

    def handle_commission_timing(self, params: dict) -> None:
        """Cache detailed timing quality for one electrical method."""
        method = params["method"]
        if method in TIMING_METHOD_NAMES:
            self.timing_by_method[method] = dict(params)

    def clear_timing_evidence(self) -> None:
        """Clear detailed timing replies from the current or prior run."""
        self.timing_by_method = {}

    def consume_timing_evidence(self, packed: int) -> dict[int, dict]:
        """Validate detailed replies against a terminal summary and consume them."""
        summary = decode_timing_summary(packed)
        details = self.timing_by_method
        self.clear_timing_evidence()
        rejected = False
        accepted = {}
        for method, method_name in TIMING_METHOD_NAMES.items():
            summary_status = summary["statuses"][method]
            if summary_status not in TIMING_STATUS_NAMES:
                raise ValueError(
                    f"{method_name} timing summary has reserved status {int(summary_status)}"
                )
            detail = details.get(method)
            if summary_status == 0 and detail is None:
                continue
            if detail is None:
                raise ValueError(f"{method_name} timing detail is missing")
            detail_status = detail["status"]
            if detail_status != summary_status:
                detail_status_name = TIMING_STATUS_NAMES.get(
                    detail_status, f"unknown({int(detail_status)})"
                )
                raise ValueError(
                    f"{method_name} timing status mismatch: "
                    f"detail={detail_status_name} summary={TIMING_STATUS_NAMES[summary_status]}"
                )
            if detail_status == 2:
                rejected = True
                continue
            if detail_status == 1:
                accepted[method] = detail
        if summary["rejected"] != rejected:
            raise ValueError("timing rejection flag does not match method statuses")
        if rejected:
            method = next(method for method in details if details[method]["status"] == 2)
            raise ValueError(COMMISSION_REASON_NAMES[TIMING_REJECTION_ERROR_CODES[method]])
        return accepted

    def cancel_and_await_quiescence(self, reactor, wait_predicate, eventtime: float) -> float:
        """Send foci_commission_cancel and poll until wait_predicate() is true
        or COMMISSION_CANCEL_GRACE_PERIOD_S elapses, whichever comes first.

        Returns the eventtime this call stopped at. Callers still raise their
        own "timed out" error regardless of the outcome here -- this method
        only decides how long to wait before that raise, and whether firmware
        actually quiesced in time (observable via wait_predicate() afterward).
        It never touches the caller's operation lock; the caller's own
        try/finally holds and releases it around this call.
        """
        self.driver.protocol.run_commission_cancel()
        deadline = eventtime + COMMISSION_CANCEL_GRACE_PERIOD_S
        while not wait_predicate() and eventtime < deadline:
            eventtime = reactor.pause(min(eventtime + 0.1, deadline))
        return eventtime

    def commission(self, gcmd) -> None:
        """Commission motor for safe printer motion."""
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        if profile_name not in PROFILE_MAP:
            raise gcmd.error(
                f"Unknown profile '{profile_name}'. Options: {', '.join(PROFILE_MAP.keys())}"
            )
        profile_code = PROFILE_MAP[profile_name]

        if not self.driver.state.try_acquire("setup"):
            raise gcmd.error(f"FOCI {self.driver.name}: another FOCI operation is in progress")
        try:
            toolhead = self.driver.printer.lookup_object("toolhead")
            toolhead.wait_moves()

            stepper_enable = self.driver.printer.lookup_object("stepper_enable")
            enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
            if enable_line.is_motor_enabled():
                enable_line.motor_disable(toolhead.get_last_move_time())
                toolhead.wait_moves()

            self.driver.state.is_calibrated = False
            self.driver.homing.invalidate_homing()

            self.done = False
            self.result = None
            self.error_code = 0
            self.last_phase_id = None
            self.clear_details()
            self.clear_timing_evidence()

            # Clear any resistance-reply cache left over from a standalone
            # FOCI_RESISTANCE_TEST run before this commission's firmware
            # stream can emit its own foci_resistance_run/axis replies.
            # The cache is otherwise only cleared at commission exit
            # (success via pop_resistance_cache, failure/timeout via
            # clear_resistance_cache below), so without this start-of-run
            # clear a full standalone run+axis0+axis1 entry could survive
            # to pre-populate this commission's cache. If this commission
            # then delivered only a partial set of replies (e.g. run+axis0,
            # axis1 dropped), handle_resistance_axis would overwrite only
            # the received axis, leaving the stale axis1 in place; the
            # all-or-nothing pop_resistance_cache would see run+axis0+
            # axis1 all "present" (axis1 stale) and fold/persist a result
            # blending data from two unrelated runs.
            self.driver.diagnostics.clear_resistance_cache(self.driver.oid)
            self.driver.diagnostics.active.clear_inductance_cache(self.driver.oid)
            self.driver.diagnostics.active.clear_current_loop_cache(self.driver.oid)
            self.driver.diagnostics.active.clear_last_encoder_alignment_evidence(self.driver.oid)

            self.driver.protocol.run_commission(profile_code)

            reactor = self.driver.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + ELECTRICAL_ID_WAIT_TIMEOUT_S
            while not self.done:
                eventtime = reactor.pause(eventtime + 0.1)
                if eventtime > timeout:
                    self.cancel_and_await_quiescence(reactor, lambda: self.done, eventtime)
                    self.on_commission_failure()
                    self.driver.diagnostics.clear_resistance_cache(self.driver.oid)
                    self.driver.diagnostics.active.clear_inductance_cache(self.driver.oid)
                    self.driver.diagnostics.active.clear_current_loop_cache(self.driver.oid)
                    report_summary(
                        gcmd,
                        f"FOCI_SETUP {self.driver.stepper_name}: FAILED — timed out waiting "
                        "for the commissioning firmware.",
                    )
                    raise gcmd.error(f"FOCI {self.driver.name}: FOCI_SETUP timed out")
                if self.error_code != 0:
                    error_name = self.format_commission_failure(self.error_code)
                    if self.error_code == 18:
                        self.handle_chip_reset_detected()
                    else:
                        self.on_commission_failure(error_name)
                    self.driver.diagnostics.clear_resistance_cache(self.driver.oid)
                    self.driver.diagnostics.active.clear_inductance_cache(self.driver.oid)
                    self.driver.diagnostics.active.clear_current_loop_cache(self.driver.oid)
                    phase_name = PHASE_NAMES.get(self.last_phase_id or 0, "unknown")
                    if self.details:
                        detail_lines = [
                            f"FOCI {self.driver.stepper_name} commissioning diagnostics:"
                        ]
                        detail_lines.extend(
                            f"  {format_commission_detail(detail)}" for detail in self.details
                        )
                        report_detail(log, self.driver.global_config.debug, "\n".join(detail_lines))
                    if self.last_phase_id == 4 and _encoder_direction_sweep_failed(self.details):
                        phrase = format_encoder_direction_failure(self.details)
                    else:
                        phrase = operator_failure_phrase(self.error_code)
                    report_summary(
                        gcmd,
                        f"FOCI_SETUP {self.driver.stepper_name}: FAILED — {phrase}.",
                    )
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: FOCI_SETUP failed at {phase_name}: {error_name}"
                    )

            result = self.result
            # W1 firmware emits foci_resistance_run + two
            # foci_resistance_axis replies during FOCI_SETUP, just
            # before foci_commission_result. The diagnostics handlers
            # cache those reply values (keyed by oid); fold them into the
            # result dict now so persist_commission_results' presence-gated
            # resistance block sees them below. pop_resistance_cache always
            # clears the per-oid cache entry here, and is all-or-nothing:
            # it only returns folded values when run + axis0 + axis1 are
            # all cached, so a commission that completed before every
            # resistance reply arrived folds in nothing rather than a
            # partial set. The two early-exit failure paths above
            # (timeout, mid-phase error) clear the cache directly via
            # clear_resistance_cache since they return before reaching
            # here; together these guarantee no stale or partial
            # resistance cache entry ever survives past this method.
            result.update(self.driver.diagnostics.pop_resistance_cache(self.driver.oid))
            result.update(self.driver.diagnostics.active.pop_inductance_cache(self.driver.oid))
            result.update(self.driver.diagnostics.active.pop_current_loop_cache(self.driver.oid))
            try:
                result["commission_timing"] = self.consume_timing_evidence(
                    result.get("timing_summary", 0)
                )
            except ValueError as error:
                self.on_commission_failure(str(error))
                # This branch only runs once the firmware itself reported success,
                # meaning closed-loop entry already armed the motor directly
                # through the commissioning backend, bypassing EnableLine. Sync
                # EnableLine to that armed state before disabling, or its own
                # is_enabled bookkeeping (still False) makes motor_disable() a
                # no-op and no command ever reaches the MCU.
                enable_line.motor_enable(toolhead.get_last_move_time())
                enable_line.motor_disable(toolhead.get_last_move_time())
                toolhead.wait_moves()
                report_summary(
                    gcmd,
                    f"FOCI_SETUP {self.driver.stepper_name}: FAILED — timing evidence "
                    "was rejected.",
                )
                raise gcmd.error(
                    f"FOCI {self.driver.name}: FOCI_SETUP timing evidence rejected: {error}"
                ) from error
            status = result.get("status", 255)
            if status > 1:
                error_name = self.format_commission_failure(status)
                if status == 18:
                    self.handle_chip_reset_detected()
                else:
                    self.on_commission_failure(error_name)
                report_summary(
                    gcmd,
                    f"FOCI_SETUP {self.driver.stepper_name}: FAILED — "
                    f"{operator_failure_phrase(status)}.",
                )
                raise gcmd.error(f"FOCI {self.driver.name}: FOCI_SETUP failed: {error_name}")

            self.driver.state.is_calibrated = True
            self.driver.state.inhibited = False
            self.driver.state.last_commission_failure = None
            self.driver.homing.set_auto_calibrate_on_enable_allowed(True)
            self.driver.state.commissioned_result = result
            self.driver.state.active_gains = {
                "flux_p": result["flux_p"],
                "flux_i": result["flux_i"],
                "torque_p": result["torque_p"],
                "torque_i": result["torque_i"],
                "velocity_p": result["fallback_velocity_p"],
                "velocity_i": result["fallback_velocity_i"],
                "position_p": result["fallback_position_p"],
                "position_i": result["fallback_position_i"],
                "velocity_limit": result["fallback_velocity_limit"],
                "velocity_filter_hz": result.get("velocity_filter_hz", 0),
                "torque_filter_hz": result.get(
                    "current_torque_filter_hz",
                    self.driver.settings.torque_filter_hz,
                ),
                "position_filter_hz": result.get("position_filter_hz", 0),
                "flux_filter_hz": result.get(
                    "current_flux_filter_hz",
                    self.driver.settings.flux_filter_hz,
                ),
            }
            self.driver.state.runtime_status = "commissioned"
            enable_line.motor_enable(toolhead.get_last_move_time())

            self.persist_commission_results(result, profile_name)

            report_summary(
                gcmd,
                f"FOCI_SETUP {self.driver.stepper_name}: SUCCEEDED — resistance/inductance "
                "identified, current gains applied.",
            )
            status_str = "accepted" if status == 0 else "accepted with warnings"
            report_detail(
                log,
                self.driver.global_config.debug,
                f"FOCI {self.driver.name} commissioned ({status_str}): r_count_milli="
                f"{int(result['r_count_milli'])} l_count_micro={int(result['l_count_micro'])} "
                f"bandwidth_hz={int(result.get('bandwidth_hz', 0))} current_candidate_attempt="
                f"{int(result.get('current_candidate_attempt', 0))}",
            )
            flags = result.get("inner_warning_flags", 0)
            if flags & INNER_WARNING_GAIN_FLOOR_SKIPPED:
                report_summary(
                    gcmd,
                    f"FOCI {self.driver.name} warning: gain floor skipped, outer gains are "
                    "the built-in defaults, not measured from this motor.",
                )
            if flags:
                report_detail(
                    log,
                    self.driver.global_config.debug,
                    f"FOCI {self.driver.name} inner confidence: "
                    f"{format_inner_warning_flags(flags)}",
                )
            for method, evidence in result["commission_timing"].items():
                report_detail(
                    log,
                    self.driver.global_config.debug,
                    format_timing_evidence(TIMING_METHOD_NAMES[method], evidence),
                )
        finally:
            self.clear_timing_evidence()
            self.driver.state.release()

    def format_commission_failure(self, status: int) -> str:
        """Format a commission terminal status with cached subordinate evidence."""
        error_name = format_commission_error_name(status)
        if status == 9:
            detail = format_current_loop_failure_summary(
                self.driver.diagnostics.active.last_current_loop_evidence(self.driver.oid),
                self.driver.diagnostics.active.last_current_loop_samples(self.driver.oid),
            )
            if detail is not None:
                return f"{error_name} ({detail})"
        return error_name

    def on_commission_failure(self, failure: str | None = None) -> None:
        """Handle commissioning failure state transitions."""
        self.driver.state.is_calibrated = False
        self.driver.state.commissioned_result = None
        self.driver.state.active_gains = None
        self.driver.state.runtime_status = "uncommissioned"
        self.driver.state.inhibited = True
        self.driver.state.last_commission_failure = failure
        self.driver.homing.set_auto_calibrate_on_enable_allowed(False)

    def handle_chip_reset_detected(self) -> None:
        """Clear calibration after firmware reports chip reset without inhibiting."""
        self.driver.state.is_calibrated = False
        self.driver.state.inhibited = False
        self.driver.state.last_commission_failure = None
        self.driver.homing.set_auto_calibrate_on_enable_allowed(True)

    def maybe_clear_calibration_for_chip_reset(self, status: int) -> None:
        """Apply chip-reset recovery for CommissionError status 18."""
        if status == 18:
            self.handle_chip_reset_detected()

    def persist_commission_results(self, result: dict, profile_name: str) -> None:
        """Persist commissioning results to printer.cfg pending SAVE_CONFIG."""
        configfile = self.driver.printer.lookup_object("configfile")
        configfile.set(self.driver.name, "pid_flux_p", f"{int(result['flux_p'])}")
        configfile.set(self.driver.name, "pid_flux_i", f"{int(result['flux_i'])}")
        configfile.set(self.driver.name, "pid_torque_p", f"{int(result['torque_p'])}")
        configfile.set(self.driver.name, "pid_torque_i", f"{int(result['torque_i'])}")
        configfile.set(
            self.driver.name,
            "commissioned_velocity_p",
            f"{int(result['fallback_velocity_p'])}",
        )
        configfile.set(
            self.driver.name,
            "commissioned_velocity_i",
            f"{int(result['fallback_velocity_i'])}",
        )
        configfile.set(
            self.driver.name,
            "commissioned_position_p",
            f"{int(result['fallback_position_p'])}",
        )
        configfile.set(
            self.driver.name,
            "commissioned_position_i",
            f"{int(result['fallback_position_i'])}",
        )
        configfile.set(
            self.driver.name,
            "commissioned_velocity_limit",
            f"{int(result['fallback_velocity_limit'])}",
        )
        configfile.set(
            self.driver.name,
            "identified_r_count_milli",
            f"{int(result['r_count_milli'])}",
        )
        configfile.set(self.driver.name, "identified_lambda_us", f"{int(result['lambda_us'])}")
        configfile.set(
            self.driver.name,
            "identified_theta_e_us",
            f"{int(result['theta_e_us'])}",
        )
        configfile.set(
            self.driver.name,
            "identified_theta_source",
            f"{int(result.get('theta_source', 1))}",
        )
        configfile.set(
            self.driver.name,
            "identified_ringing_count",
            f"{int(result['ringing_count'])}",
        )
        configfile.set(
            self.driver.name,
            "identified_bandwidth_hz",
            f"{int(result['bandwidth_hz'])}",
        )
        configfile.set(
            self.driver.name,
            "identified_tau_e_us",
            f"{int(result.get('tau_e_us', 0))}",
        )
        configfile.set(
            self.driver.name,
            "identified_inner_warning_flags",
            f"{int(result.get('inner_warning_flags', 0))}",
        )
        self._persist_resistance_identification(configfile, result)
        self._persist_inductance_identification(configfile, result)
        self._persist_current_loop_identification(configfile, result)
        configfile.set(self.driver.name, "autotune_profile", profile_name)
        configfile.set(self.driver.name, "autotune_status", "commissioned")

    # Maps each firmware-reported resistance-identification result key to
    # the persisted config key. All values are firmware-owned: the host
    # neither fits, selects points, nor evaluates quality gates here, it
    # only stores what firmware already decided. The
    # `foci_commission_result` wire reply does not carry these fields yet
    # (tracked separately); `persist_commission_results` skips this group
    # entirely when firmware has not reported it, rather than persist
    # fabricated zeros.
    RESISTANCE_RESULT_KEYS: tuple[tuple[str, str], ...] = (
        ("resistance_selected_count_slope_milli", "identified_r_count_slope_milli"),
    )

    def _persist_resistance_identification(self, configfile, result: dict) -> None:
        """Persist firmware-owned resistance-identification evidence.

        Persists only the selected count-space slope, reported by firmware
        as-is; the host performs no fitting, point selection, unit
        conversion, or quality-gate evaluation.

        Skips this group entirely when ``result`` does not contain this
        key, so commissioning against older firmware that has not yet
        added it to its reply still persists cleanly.
        """
        if "resistance_selected_count_slope_milli" not in result:
            return
        for result_key, config_key in self.RESISTANCE_RESULT_KEYS:
            configfile.set(self.driver.name, config_key, f"{int(result[result_key])}")

    INDUCTANCE_RESULT_KEYS: Sequence[tuple[str, str]] = (
        ("inductance_source", "identified_l_source"),
        (
            "inductance_reactance_count_ratio_milli",
            "identified_l_reactance_count_ratio_milli",
        ),
        ("inductance_saliency_status", "identified_l_saliency_status"),
    )

    def _persist_inductance_identification(self, configfile, result: dict) -> None:
        """Persist firmware-owned production inductance evidence."""
        if "inductance_reactance_count_ratio_milli" not in result:
            return
        for result_key, config_key in self.INDUCTANCE_RESULT_KEYS:
            configfile.set(self.driver.name, config_key, f"{int(result[result_key])}")

    CURRENT_LOOP_RESULT_KEYS: tuple[tuple[str, str], ...] = (
        ("current_gains_source", "identified_current_gains_source"),
        ("current_gains_tier", "identified_current_gains_tier"),
        (
            "current_retry_budget_exhausted",
            "identified_current_retry_budget_exhausted",
        ),
        ("current_failure_reason", "identified_current_failure_reason"),
    )

    def _persist_current_loop_identification(self, configfile, result: dict) -> None:
        """Persist firmware-owned current-loop commissioning evidence."""
        if "current_gains_source" not in result:
            return
        for result_key, config_key in self.CURRENT_LOOP_RESULT_KEYS:
            configfile.set(self.driver.name, config_key, f"{int(result[result_key])}")
