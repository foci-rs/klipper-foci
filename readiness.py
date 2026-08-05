"""Autotune readiness resolver for FOCI host workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .commissioning import format_inner_warning_flags

RESULT_READY = "ready"
RESULT_READY_WITH_WARNINGS = "ready_with_warnings"
RESULT_BLOCKED = "blocked"

POLICY_NORMAL = "normal"
POLICY_DERATED = "derated"
POLICY_CONSERVATIVE = "conservative"
POLICY_UNAVAILABLE = "unavailable"

CURRENT_GAIN_FIELDS: tuple[str, ...] = ("flux_p", "flux_i", "torque_p", "torque_i")
CONSERVATIVE_INNER_FLAGS = (1 << 5) | (1 << 6)
DERATING_INNER_FLAGS = (1 << 0) | (1 << 1) | (1 << 3)
CURRENT_HOLD_BLOCKING_STATUSES = frozenset((2, 3, 4))
CLOSED_LOOP_ENTRY_BLOCKING_STATUSES = frozenset((2, 3))
CLOSED_LOOP_ENTRY_WARN_DRIFT = 4
REQUIRED_STAGE2_INPUTS = frozenset(("average_inductance",))


@dataclass(frozen=True)
class AutotuneReadiness:
    """Computed readiness report for Stage 2 autotune admission."""

    result: str
    stage2_policy: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    trusted_inputs: tuple[str, ...]
    unavailable_inputs: tuple[str, ...]
    tau_e_us: int
    inner_warning_flags: int
    current_bandwidth_hz: int | None

    @property
    def blocked(self) -> bool:
        """Return true when Stage 2 must refuse before starting."""
        return self.result == RESULT_BLOCKED


def resolve_autotune_readiness(
    driver,
    live_current_gains: Mapping[str, int | None] | None = None,
) -> AutotuneReadiness:
    """Resolve host-visible Stage 2 readiness from firmware-classified evidence."""
    blockers: list[str] = []
    warnings: list[str] = []
    trusted_inputs: list[str] = []
    unavailable_inputs: list[str] = []

    state = driver.state
    if state.inhibited:
        blockers.append("inhibited after failed FOCI_COMMISSION")
    if state.runtime_status == "uncommissioned":
        blockers.append("not commissioned")
    if not state.is_calibrated:
        blockers.append("not calibrated")

    current_loop_evidence = _resolve_current_loop_evidence(driver)
    inductance_evidence = _resolve_inductance_evidence(driver)
    resistance_evidence = _resolve_resistance_evidence(driver)
    tau_e_us, inner_warning_flags = _resolve_inner_confidence(driver)
    current_bandwidth_hz = _resolve_current_bandwidth(driver)
    if current_loop_evidence["gains_source"] == 2 or current_loop_evidence["gains_tier"] == 3:
        inner_warning_flags |= 1 << 5

    _classify_current_gains(
        state.active_gains,
        live_current_gains,
        blockers,
        trusted_inputs,
    )
    _classify_current_loop_evidence(current_loop_evidence, blockers, warnings)
    _classify_inner_warnings(inner_warning_flags, warnings)
    _classify_bandwidth(current_bandwidth_hz, warnings, trusted_inputs)
    _classify_inductance(inductance_evidence, trusted_inputs, unavailable_inputs)
    _classify_resistance(resistance_evidence, trusted_inputs)
    _classify_last_hold_and_entry(driver, blockers, warnings)

    stage2_policy = _stage2_policy(
        blockers,
        warnings,
        unavailable_inputs,
        inner_warning_flags,
        current_bandwidth_hz,
    )
    if blockers:
        result = RESULT_BLOCKED
    elif warnings or unavailable_inputs:
        result = RESULT_READY_WITH_WARNINGS
    else:
        result = RESULT_READY

    return AutotuneReadiness(
        result=result,
        stage2_policy=stage2_policy,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        trusted_inputs=tuple(_dedupe(trusted_inputs)),
        unavailable_inputs=tuple(_dedupe(unavailable_inputs)),
        tau_e_us=tau_e_us,
        inner_warning_flags=inner_warning_flags,
        current_bandwidth_hz=current_bandwidth_hz,
    )


def format_readiness_report(report: AutotuneReadiness, stepper_name: str) -> list[str]:
    """Format a readiness report for DUMP_FOCI TUNING=1."""
    lines = [
        "-- Autotune readiness --",
        f"  FOCI {stepper_name} autotune readiness:",
        f"    result: {report.result}",
        f"    stage2_policy: {report.stage2_policy}",
        f"    blockers: {_format_list(report.blockers)}",
        f"    warnings: {_format_list(report.warnings)}",
        f"    trusted_inputs: {_format_list(report.trusted_inputs)}",
        f"    unavailable_inputs: {_format_list(report.unavailable_inputs)}",
    ]
    return lines


def _resolve_inner_confidence(driver) -> tuple[int, int]:
    if driver.state.commissioned_result is not None:
        result = driver.state.commissioned_result
        return result.get("tau_e_us", 0), result.get("inner_warning_flags", 0)

    config = driver.config
    tau_e_us = config.identified_tau_e_us
    if tau_e_us is None:
        if config.identified_lambda_us is None:
            tau_e_us = 1000
        else:
            tau_e_us = max(config.identified_lambda_us, 1000)

    inner_warning_flags = config.identified_inner_warning_flags
    if inner_warning_flags is None:
        inner_warning_flags = 0x40

    return tau_e_us, inner_warning_flags


def _resolve_current_bandwidth(driver) -> int | None:
    if driver.state.commissioned_result is not None:
        return driver.state.commissioned_result.get("bandwidth_hz")
    return driver.config.identified_bandwidth_hz


def _resolve_current_loop_evidence(driver) -> dict[str, int | None]:
    if driver.state.commissioned_result is not None:
        result = driver.state.commissioned_result
        if any(
            key in result
            for key in (
                "current_gains_source",
                "current_gains_tier",
                "current_retry_budget_exhausted",
                "current_failure_reason",
            )
        ):
            return {
                "gains_source": result.get("current_gains_source"),
                "gains_tier": result.get("current_gains_tier"),
                "retry_budget_exhausted": result.get("current_retry_budget_exhausted"),
                "failure_reason": result.get("current_failure_reason"),
            }

    config = driver.config
    return {
        "gains_source": config.identified_current_gains_source,
        "gains_tier": config.identified_current_gains_tier,
        "retry_budget_exhausted": config.identified_current_retry_budget_exhausted,
        "failure_reason": config.identified_current_failure_reason,
    }


def _resolve_inductance_evidence(driver) -> dict[str, int | None]:
    if driver.state.commissioned_result is not None:
        result = driver.state.commissioned_result
        if any(
            key in result
            for key in (
                "inductance_source",
                "inductance_reactance_count_ratio_milli",
                "inductance_saliency_status",
            )
        ):
            return {
                "source": result.get("inductance_source"),
                "reactance_count_ratio_milli": result.get("inductance_reactance_count_ratio_milli"),
                "saliency_status": result.get("inductance_saliency_status"),
            }

    config = driver.config
    return {
        "source": config.identified_l_source,
        "reactance_count_ratio_milli": config.identified_l_reactance_count_ratio_milli,
        "saliency_status": config.identified_l_saliency_status,
    }


def _resolve_resistance_evidence(driver) -> dict[str, int | None]:
    if driver.state.commissioned_result is not None:
        result = driver.state.commissioned_result
        if any(
            key in result
            for key in (
                "resistance_selected_count_slope_milli",
                "r_count_milli",
            )
        ):
            return {
                "selected_count_slope_milli": result.get("resistance_selected_count_slope_milli"),
                "r_count_milli": result.get("r_count_milli"),
            }

    config = driver.config
    return {
        "selected_count_slope_milli": config.identified_r_count_slope_milli,
        "r_count_milli": config.identified_r_count_milli,
    }


def _classify_current_gains(
    active_gains: Mapping[str, int | None] | None,
    live_current_gains: Mapping[str, int | None] | None,
    blockers: list[str],
    trusted_inputs: list[str],
) -> None:
    if active_gains is None:
        blockers.append("active gains unavailable")
        return

    current_gain_blocked = False
    for field_name in CURRENT_GAIN_FIELDS:
        active_value = active_gains.get(field_name)
        if active_value is None:
            blockers.append(f"active current-loop gain {field_name} unavailable")
            current_gain_blocked = True
            continue
        if live_current_gains is None:
            continue
        live_value = live_current_gains.get(field_name)
        if live_value is None:
            blockers.append(f"live current-loop gain {field_name} unavailable")
            current_gain_blocked = True
        elif live_value != active_value:
            blockers.append(
                f"live current-loop gain {field_name} mismatch live={live_value} host="
                f"{active_value}"
            )
            current_gain_blocked = True

    if not current_gain_blocked:
        trusted_inputs.append("current_loop_gains")


def _classify_current_loop_evidence(
    evidence: Mapping[str, int | None],
    blockers: list[str],
    warnings: list[str],
) -> None:
    if evidence.get("retry_budget_exhausted"):
        blockers.append("current-loop retry exhausted")
    failure_reason = evidence.get("failure_reason")
    if failure_reason not in (None, 0):
        blockers.append(f"current-loop failure reason={failure_reason}")


def _classify_inner_warnings(inner_warning_flags: int, warnings: list[str]) -> None:
    if inner_warning_flags == 0:
        return
    formatted = format_inner_warning_flags(inner_warning_flags)
    if formatted != "none":
        warnings.append(f"inner confidence: {formatted}")


def _classify_bandwidth(
    current_bandwidth_hz: int | None,
    warnings: list[str],
    trusted_inputs: list[str],
) -> None:
    if current_bandwidth_hz in (None, 0):
        warnings.append("current bandwidth missing or zero")
    else:
        trusted_inputs.append("current_bandwidth")


def _classify_inductance(
    evidence: Mapping[str, int | None],
    trusted_inputs: list[str],
    unavailable_inputs: list[str],
) -> None:
    if evidence.get("source") == 1 or evidence.get("reactance_count_ratio_milli") is not None:
        trusted_inputs.append("average_inductance")
    else:
        unavailable_inputs.append("average_inductance")

    if evidence.get("saliency_status") == 1:
        trusted_inputs.append("ld_lq_split")
    else:
        unavailable_inputs.append("ld_lq_split")


def _classify_resistance(
    evidence: Mapping[str, int | None],
    trusted_inputs: list[str],
) -> None:
    if (
        evidence.get("selected_count_slope_milli") is not None
        or evidence.get("r_count_milli") is not None
    ):
        trusted_inputs.append("count_space_resistance")


def _classify_last_hold_and_entry(
    driver,
    blockers: list[str],
    warnings: list[str],
) -> None:
    active = driver.diagnostics.active
    hold = active.last_current_loop_hold_evidence(driver.oid)
    hold_status = hold.get("hold_status") if hold else None
    if hold_status in CURRENT_HOLD_BLOCKING_STATUSES:
        blockers.append(f"sustained-hold hard failure status={hold_status}")
    elif hold and hold.get("warning_flags", 0):
        warnings.append(f"bounded sustained-hold warning flags={hold['warning_flags']}")

    entry = active.last_closed_loop_entry_evidence(driver.oid)
    entry_status = entry.get("entry_status") if entry else None
    if entry_status in CLOSED_LOOP_ENTRY_BLOCKING_STATUSES:
        blockers.append(f"closed-loop entry hard failure status={entry_status}")
    elif entry_status == CLOSED_LOOP_ENTRY_WARN_DRIFT:
        warnings.append("bounded closed-loop entry drift")


def _stage2_policy(
    blockers: list[str],
    warnings: list[str],
    unavailable_inputs: list[str],
    inner_warning_flags: int,
    current_bandwidth_hz: int | None,
) -> str:
    if blockers:
        return POLICY_UNAVAILABLE
    if _required_stage2_inputs_missing(unavailable_inputs):
        return POLICY_UNAVAILABLE
    if inner_warning_flags & CONSERVATIVE_INNER_FLAGS or current_bandwidth_hz in (
        None,
        0,
    ):
        return POLICY_CONSERVATIVE
    if inner_warning_flags & DERATING_INNER_FLAGS:
        return POLICY_DERATED
    return POLICY_NORMAL


def _required_stage2_inputs_missing(unavailable_inputs: list[str]) -> bool:
    return any(value in REQUIRED_STAGE2_INPUTS for value in unavailable_inputs)


def _format_list(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
