"""MCU response registration helpers for klipper-foci."""

from __future__ import annotations

import logging


MOTION_SCALE_REJECTION_NAMES = {
    1: "encoder_ppr is zero",
    2: "encoder_ppr exceeds 1073741823",
    3: "planner_steps_per_rev is zero",
    4: "planner_steps_per_rev exceeds 16777216",
    5: "motor runtime is enabled",
    6: "armed mirror is set",
    7: "physical step queue is not empty",
    8: "physical step timer is active",
    9: "mapper installation failed",
    10: "ABN_DECODER_PPR write failed",
    11: "STEP_WIDTH write failed",
    12: "TMC request queue is full",
    13: "board channel is unavailable",
}


def register_motion_scale_responses(serial, driver, oid: int) -> None:
    """Register the cause-specific motion-scale rejection diagnostic."""

    def handle_rejection(params) -> None:
        stage = {0: "P2", 1: "P1"}.get(params["stage"], "stage %d" % params["stage"])
        reason = MOTION_SCALE_REJECTION_NAMES.get(
            params["reason"], "unknown reason %d" % params["reason"]
        )
        logging.error(
            "FOCI %s motion-scale configuration rejected in %s: %s",
            driver.stepper_name,
            stage,
            reason,
        )

    serial.register_response(handle_rejection, "foci_motion_scale_rejected", oid)


def register_dump_responses(serial, driver, oid: int) -> None:
    serial.register_response(driver.dump.handle_dump_value, "foci_dump_value", oid)
    serial.register_response(driver.dump.handle_dump_done, "foci_dump_done", oid)


_LAST_BOOT_FAULT_KIND_NAMES = {1: "rust_panic", 2: "hard_fault"}


def register_last_boot_diagnostic_response(serial, driver, oid: int) -> None:
    """Log a previous-boot fault or interrupted breakaway campaign."""

    def handle_last_boot_diagnostic(params: dict) -> None:
        fault_kind = params.get("fault_kind", 0)
        breakaway_interrupted = params.get("breakaway_interrupted", 0) != 0
        checkpoint = params.get("breakaway_checkpoint", 0)

        if fault_kind != 0:
            fault_name = _LAST_BOOT_FAULT_KIND_NAMES.get(
                fault_kind, "unknown(%s)" % fault_kind
            )
            logging.error(
                "FOCI board recovered last-boot fault: kind=%s line=%s pc=0x%08x"
                " file_hash=0x%08x",
                fault_name,
                params.get("line"),
                params.get("pc", 0),
                params.get("file_hash", 0),
            )
        if breakaway_interrupted:
            logging.error(
                "FOCI board recovered interrupted breakaway campaign: checkpoint=%s",
                checkpoint,
            )

    serial.register_response(
        handle_last_boot_diagnostic, "foci_last_boot_diagnostic", oid
    )


def register_homing_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.homing.handle_calibrate_response,
        "foci_calibrate_result",
        oid,
    )


def register_commissioning_responses(serial, driver, oid: int) -> None:
    for callback, name in (
        (
            driver.autotune.handle_commissioning_workflow_plan,
            "foci_commissioning_workflow_plan",
        ),
        (
            driver.autotune.handle_velocity_sweep_plan_limits,
            "foci_velocity_sweep_plan_limits",
        ),
        (
            driver.autotune.handle_velocity_sweep_plan_geometry,
            "foci_velocity_sweep_plan_geometry",
        ),
        (
            driver.autotune.handle_velocity_sweep_plan_timing,
            "foci_velocity_sweep_plan_timing",
        ),
        (
            driver.autotune.handle_velocity_sweep_plan_recovery,
            "foci_velocity_sweep_plan_recovery",
        ),
        (
            driver.autotune.handle_rung_origin_recovery_summary,
            "foci_rung_origin_recovery_summary",
        ),
        (
            driver.autotune.handle_velocity_observation_core,
            "foci_velocity_observation_core",
        ),
        (
            driver.autotune.handle_velocity_observation_rate,
            "foci_velocity_observation_rate",
        ),
        (
            driver.autotune.handle_velocity_observation_stationarity,
            "foci_velocity_observation_stationarity",
        ),
        (
            driver.autotune.handle_velocity_observation_disturbance,
            "foci_velocity_observation_disturbance",
        ),
        (
            driver.autotune.handle_velocity_rung_consensus_core,
            "foci_velocity_rung_consensus_core",
        ),
        (
            driver.autotune.handle_velocity_rung_consensus_component,
            "foci_velocity_rung_consensus_component",
        ),
        (
            driver.autotune.handle_velocity_rung_consensus_pool,
            "foci_velocity_rung_consensus_pool",
        ),
        (
            driver.autotune.handle_velocity_structured_boundary,
            "foci_velocity_structured_boundary",
        ),
        (
            driver.autotune.handle_velocity_directional_region_core,
            "foci_velocity_directional_region_core",
        ),
        (
            driver.autotune.handle_velocity_directional_region_model,
            "foci_velocity_directional_region_model",
        ),
        (
            driver.autotune.handle_velocity_directional_region_rates,
            "foci_velocity_directional_region_rates",
        ),
        (
            driver.autotune.handle_velocity_directional_region_boundary,
            "foci_velocity_directional_region_boundary",
        ),
        (driver.autotune.handle_velocity_joint_region, "foci_velocity_joint_region"),
        (
            driver.autotune.handle_velocity_stage_b_handoff_core,
            "foci_velocity_stage_b_handoff_core",
        ),
        (
            driver.autotune.handle_velocity_stage_b_nomination,
            "foci_velocity_stage_b_nomination",
        ),
        (
            driver.autotune.handle_velocity_stage_b_directional_handoff,
            "foci_velocity_stage_b_directional_handoff",
        ),
        (
            driver.autotune.handle_velocity_stage_b_reproduction_v4_core,
            "foci_velocity_stage_b_reproduction_v4_core",
        ),
        (
            driver.autotune.handle_velocity_stage_b_reproduction_v4_membership,
            "foci_velocity_stage_b_reproduction_v4_membership",
        ),
        (
            driver.autotune.handle_velocity_stage_b_reproduction_v4_pooled,
            "foci_velocity_stage_b_reproduction_v4_pooled",
        ),
        (
            driver.autotune.handle_velocity_stage_b_reproduction_v4_common,
            "foci_velocity_stage_b_reproduction_v4_common",
        ),
        (
            driver.autotune.handle_velocity_stage_b_reproduction_v4_coverage,
            "foci_velocity_stage_b_reproduction_v4_coverage",
        ),
        (
            driver.autotune.handle_velocity_stage_b_reproduction_v4_digest,
            "foci_velocity_stage_b_reproduction_v4_digest",
        ),
        (
            driver.autotune.handle_velocity_stage_b_terminal_core,
            "foci_velocity_stage_b_terminal_core",
        ),
        (
            driver.autotune.handle_velocity_stage_b_terminal_identity,
            "foci_velocity_stage_b_terminal_identity",
        ),
        (
            driver.autotune.handle_velocity_stage_b_terminal_interval,
            "foci_velocity_stage_b_terminal_interval",
        ),
        (
            driver.autotune.handle_velocity_sweep_terminal_direction,
            "foci_velocity_sweep_terminal_direction",
        ),
        (
            driver.autotune.handle_velocity_sweep_terminal_integrity,
            "foci_velocity_sweep_terminal_integrity",
        ),
        (driver.autotune.handle_outer_inconclusive, "foci_outer_inconclusive"),
        (
            driver.autotune.handle_velocity_integral_plan_core,
            "foci_velocity_integral_plan_core",
        ),
        (
            driver.autotune.handle_velocity_integral_plan_geometry,
            "foci_velocity_integral_plan_geometry",
        ),
        (
            driver.autotune.handle_velocity_integral_plan_authority,
            "foci_velocity_integral_plan_authority",
        ),
        (
            driver.autotune.handle_velocity_integral_plan_timing,
            "foci_velocity_integral_plan_timing",
        ),
        (
            driver.autotune.handle_velocity_integral_plan_travel,
            "foci_velocity_integral_plan_travel",
        ),
        (
            driver.autotune.handle_velocity_integral_plan_recovery,
            "foci_velocity_integral_plan_recovery",
        ),
        (
            driver.autotune.handle_velocity_integral_plan_rung,
            "foci_velocity_integral_plan_rung",
        ),
        (
            driver.autotune.handle_velocity_integral_observation_core,
            "foci_velocity_integral_observation_core",
        ),
        (
            driver.autotune.handle_velocity_integral_observation_rate,
            "foci_velocity_integral_observation_rate",
        ),
        (
            driver.autotune.handle_velocity_integral_observation_quality,
            "foci_velocity_integral_observation_quality",
        ),
        (
            driver.autotune.handle_velocity_integral_rung_core,
            "foci_velocity_integral_rung_core",
        ),
        (
            driver.autotune.handle_velocity_integral_rung_component,
            "foci_velocity_integral_rung_component",
        ),
        (
            driver.autotune.handle_velocity_integral_run_summary,
            "foci_velocity_integral_run_summary",
        ),
        (
            driver.autotune.handle_velocity_integral_curve_interval,
            "foci_velocity_integral_curve_interval",
        ),
        (
            driver.autotune.handle_velocity_integral_drift,
            "foci_velocity_integral_drift",
        ),
        (
            driver.autotune.handle_velocity_integral_stage_b_comparison,
            "foci_velocity_integral_stage_b_comparison",
        ),
        (
            driver.autotune.handle_velocity_integral_reproduction_core,
            "foci_velocity_integral_reproduction_core",
        ),
        (
            driver.autotune.handle_velocity_integral_reproduction_mask,
            "foci_velocity_integral_reproduction_mask",
        ),
        (
            driver.autotune.handle_velocity_integral_reproduction_interval,
            "foci_velocity_integral_reproduction_interval",
        ),
        (
            driver.autotune.handle_velocity_integral_reproduction_digest,
            "foci_velocity_integral_reproduction_digest",
        ),
        (
            driver.autotune.handle_velocity_integral_terminal_core,
            "foci_velocity_integral_terminal_core",
        ),
        (
            driver.autotune.handle_velocity_integral_terminal_identity,
            "foci_velocity_integral_terminal_identity",
        ),
        (
            driver.autotune.handle_velocity_integral_terminal_timing,
            "foci_velocity_integral_terminal_timing",
        ),
        (
            driver.autotune.handle_acceptance_matrix_plan,
            "foci_acceptance_matrix_plan",
        ),
        (
            driver.autotune.handle_acceptance_matrix_terminal,
            "foci_acceptance_matrix_terminal",
        ),
        (
            driver.autotune.handle_breakaway_probe_plan,
            "foci_breakaway_probe_plan",
        ),
        (
            driver.autotune.handle_breakaway_directional_breakaway,
            "foci_breakaway_directional_breakaway",
        ),
        (
            driver.autotune.handle_breakaway_probe_terminal,
            "foci_breakaway_probe_terminal",
        ),
        (
            driver.autotune.handle_breakaway_discovery_plan_identity,
            "foci_breakaway_discovery_plan_identity",
        ),
        (
            driver.autotune.handle_breakaway_discovery_plan_geometry,
            "foci_breakaway_discovery_plan_geometry",
        ),
        (
            driver.autotune.handle_breakaway_discovery_ceiling_source,
            "foci_breakaway_ceiling_source",
        ),
        (
            driver.autotune.handle_breakaway_discovery_rung_zero_diagnostic,
            "foci_breakaway_rung_zero_diagnostic",
        ),
        (
            driver.autotune.handle_breakaway_discovery_terminal,
            "foci_breakaway_discovery_terminal",
        ),
        (
            driver.autotune.handle_breakaway_confirmation_plan,
            "foci_breakaway_confirmation_plan",
        ),
        (
            driver.autotune.handle_breakaway_confirmation_terminal_identity,
            "foci_breakaway_confirmation_terminal_identity",
        ),
        (
            driver.autotune.handle_breakaway_confirmation_terminal_masks,
            "foci_breakaway_confirmation_terminal_masks",
        ),
        (
            driver.autotune.handle_breakaway_campaign_terminal,
            "foci_breakaway_campaign_terminal",
        ),
    ):
        serial.register_response(callback, name, oid)
    serial.register_response(
        driver.commissioning.handle_commission_phase,
        "foci_commission_phase",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_result,
        "foci_commission_result",
        oid,
    )
    serial.register_response(
        driver.autotune.handle_tune_result,
        "foci_tune_result",
        oid,
    )
    serial.register_response(
        driver.autotune.handle_outer_safety_fault,
        "foci_outer_safety_fault",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_detail,
        "foci_commission_detail",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_timing,
        "foci_commission_timing",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_run,
        "foci_inductance_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_frame,
        "foci_inductance_frame",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_estimate,
        "foci_inductance_estimate",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_filters,
        "foci_current_loop_filters",
        oid,
    )


def register_selftest_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.selftest.handle_selftest_result,
        "foci_selftest_result",
        oid,
    )
    serial.register_response(
        driver.selftest.handle_selftest_done,
        "foci_selftest_done",
        oid,
    )


def register_active_diagnostic_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.diagnostics.active.handle_velocity_limit_latch_flags,
        "foci_velocity_limit_latch_flags",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_velocity_limit_latch_motion,
        "foci_velocity_limit_latch_motion",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_velocity_limit_latch_restore,
        "foci_velocity_limit_latch_restore",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_velocity_limit_latch_core,
        "foci_velocity_limit_latch_core",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_step_result,
        "foci_current_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_vector_step_result,
        "foci_current_vector_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_torque_sample_result,
        "foci_current_torque_sample_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_torque_sample_detail_result,
        "foci_current_torque_sample_detail_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_voltage_step_result,
        "foci_voltage_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_profile,
        "foci_resistance_profile",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_run,
        "foci_resistance_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_axis,
        "foci_resistance_axis",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_run,
        "foci_current_loop_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_hold,
        "foci_current_loop_hold",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_closed_loop_entry,
        "foci_closed_loop_entry",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_encoder_alignment,
        "foci_encoder_alignment",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_adc_residual,
        "foci_adc_residual",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_axis,
        "foci_current_validation_axis",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_settled_sample,
        "foci_current_validation_settled_sample",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_envelope,
        "foci_current_validation_envelope",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_stepper_event,
        "foci_stepper_event",
    )
    serial.register_response(
        driver.diagnostics.handle_stepper_perf_event,
        "foci_stepper_perf_event",
    )
