"""Tests for FOCI autotune-readiness resolution."""

from __future__ import annotations

from klipper_foci.readiness import (
    POLICY_CONSERVATIVE,
    POLICY_DERATED,
    POLICY_NORMAL,
    POLICY_UNAVAILABLE,
    RESULT_BLOCKED,
    RESULT_READY,
    RESULT_READY_WITH_WARNINGS,
    resolve_autotune_readiness,
)

from tests.mocks import SAMPLE_ACTIVE_GAINS, make_driver


def _driver_ready_for_autotune():
    driver = make_driver()
    driver.state.is_calibrated = True
    driver.state.runtime_status = "commissioned"
    driver.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()

    driver.config.identified_lambda_us = 700
    driver.config.identified_tau_e_us = 730
    driver.config.identified_theta_e_us = 160
    driver.config.identified_bandwidth_hz = 1600
    driver.config.identified_inner_warning_flags = 0

    driver.config.identified_current_gains_source = 1
    driver.config.identified_current_gains_tier = 1
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0

    driver.config.identified_l_source = 1
    driver.config.identified_l_reactance_count_ratio_milli = 8600
    driver.config.identified_l_saliency_status = 1

    driver.config.identified_r_count_slope_milli = 1042
    return driver


def test_clean_substrate_is_ready_normal():
    driver = _driver_ready_for_autotune()

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY
    assert report.installed_tuning_policy == POLICY_NORMAL
    assert report.blockers == ()
    assert report.warnings == ()
    assert report.tau_e_us == 730
    assert report.inner_warning_flags == 0
    assert "current_loop_gains" in report.trusted_inputs
    assert "current_bandwidth" in report.trusted_inputs
    assert "average_inductance" in report.trusted_inputs
    assert "count_space_resistance" in report.trusted_inputs


def test_missing_inner_confidence_sets_bit6_and_forces_conservative():
    driver = _driver_ready_for_autotune()
    driver.config.identified_inner_warning_flags = None

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY_WITH_WARNINGS
    assert report.installed_tuning_policy == POLICY_CONSERVATIVE
    assert report.inner_warning_flags == 0x40
    assert any("host-default confidence" in item for item in report.warnings)


def test_default_current_gains_force_conservative():
    driver = _driver_ready_for_autotune()
    driver.config.identified_current_gains_source = 2
    driver.config.identified_current_gains_tier = 3

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY_WITH_WARNINGS
    assert report.installed_tuning_policy == POLICY_CONSERVATIVE
    assert any("current gains fell back" in item for item in report.warnings)


def test_default_current_gain_warning_is_reported_once():
    driver = _driver_ready_for_autotune()
    driver.config.identified_current_gains_source = 2
    driver.config.identified_current_gains_tier = 3

    report = resolve_autotune_readiness(driver)

    fallback_warnings = [
        item for item in report.warnings if "current gains fell back to defaults" in item
    ]
    assert fallback_warnings == ["inner confidence: current gains fell back to defaults"]


def test_model_quality_flags_derate_without_forcing_conservative():
    driver = _driver_ready_for_autotune()
    driver.config.identified_inner_warning_flags = (1 << 0) | (1 << 3)

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY_WITH_WARNINGS
    assert report.installed_tuning_policy == POLICY_DERATED
    assert any("coil R mismatch" in item for item in report.warnings)
    assert any("theta/tau ratio" in item for item in report.warnings)


def test_inner_warning_bit4_alone_is_ignored():
    driver = _driver_ready_for_autotune()
    driver.config.identified_inner_warning_flags = 1 << 4

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY
    assert report.installed_tuning_policy == POLICY_NORMAL
    assert report.warnings == ()


def test_saliency_status_does_not_affect_readiness():
    driver = _driver_ready_for_autotune()
    driver.config.identified_l_saliency_status = 0

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY
    assert report.installed_tuning_policy == POLICY_NORMAL
    assert report.unavailable_inputs == ()
    assert "ld_lq_split" not in report.trusted_inputs
    assert "average_inductance" in report.trusted_inputs


def test_average_inductance_missing_marks_installed_tuning_policy_unavailable():
    driver = _driver_ready_for_autotune()
    driver.config.identified_l_source = 0
    driver.config.identified_l_reactance_count_ratio_milli = None

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY_WITH_WARNINGS
    assert report.installed_tuning_policy == POLICY_UNAVAILABLE
    assert "average_inductance" in report.unavailable_inputs


def test_current_loop_failure_blocks_autotune():
    driver = _driver_ready_for_autotune()
    driver.config.identified_current_failure_reason = 6

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_BLOCKED
    assert report.installed_tuning_policy == POLICY_UNAVAILABLE
    assert any("current-loop failure" in item for item in report.blockers)


def test_retry_exhaustion_blocks_autotune():
    driver = _driver_ready_for_autotune()
    driver.config.identified_current_retry_budget_exhausted = 1

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_BLOCKED
    assert any("retry exhausted" in item for item in report.blockers)


def test_active_current_gain_missing_blocks_autotune():
    driver = _driver_ready_for_autotune()
    driver.state.active_gains["flux_p"] = None

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_BLOCKED
    assert any("active current-loop gain flux_p unavailable" in item for item in report.blockers)


def test_current_loop_gains_trusted_with_unrelated_blocker():
    driver = _driver_ready_for_autotune()
    driver.state.runtime_status = "uncommissioned"

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_BLOCKED
    assert any("not commissioned" in item for item in report.blockers)
    assert "current_loop_gains" in report.trusted_inputs


def test_live_current_gain_mismatch_blocks_when_live_readback_provided():
    driver = _driver_ready_for_autotune()
    live_current_gains = {
        "flux_p": SAMPLE_ACTIVE_GAINS["flux_p"] + 1,
        "flux_i": SAMPLE_ACTIVE_GAINS["flux_i"],
        "torque_p": SAMPLE_ACTIVE_GAINS["torque_p"],
        "torque_i": SAMPLE_ACTIVE_GAINS["torque_i"],
    }

    report = resolve_autotune_readiness(driver, live_current_gains=live_current_gains)

    assert report.result == RESULT_BLOCKED
    assert any("live current-loop gain flux_p mismatch" in item for item in report.blockers)


def test_fresh_commissioned_evidence_overrides_stale_config_for_readiness():
    driver = _driver_ready_for_autotune()
    driver.config.identified_current_gains_source = 2
    driver.config.identified_current_gains_tier = 3
    driver.config.identified_l_source = 0
    driver.config.identified_l_reactance_count_ratio_milli = None
    driver.config.identified_l_saliency_status = 0
    driver.config.identified_r_count_slope_milli = None
    driver.state.commissioned_result = {
        "tau_e_us": 730,
        "inner_warning_flags": 0,
        "bandwidth_hz": 1600,
        "current_gains_source": 1,
        "current_gains_tier": 1,
        "current_retry_budget_exhausted": 0,
        "current_failure_reason": 0,
        "inductance_source": 1,
        "inductance_reactance_count_ratio_milli": 8600,
        "inductance_saliency_status": 1,
        "resistance_selected_count_slope_milli": 1042,
        "r_count_milli": 1706,
    }

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY
    assert report.installed_tuning_policy == POLICY_NORMAL
    assert report.warnings == ()
    assert report.unavailable_inputs == ()
    assert "average_inductance" in report.trusted_inputs
    assert "ld_lq_split" not in report.trusted_inputs
    assert "count_space_resistance" in report.trusted_inputs


def test_fresh_commissioned_current_loop_failure_blocks_despite_stale_config():
    driver = _driver_ready_for_autotune()
    driver.config.identified_current_failure_reason = 0
    driver.state.commissioned_result = {
        "tau_e_us": 730,
        "inner_warning_flags": 0,
        "bandwidth_hz": 1600,
        "current_gains_source": 1,
        "current_gains_tier": 1,
        "current_retry_budget_exhausted": 0,
        "current_failure_reason": 6,
        "inductance_source": 1,
        "inductance_reactance_count_ratio_milli": 8600,
        "inductance_saliency_status": 1,
        "resistance_selected_count_slope_milli": 1042,
    }

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_BLOCKED
    assert report.installed_tuning_policy == POLICY_UNAVAILABLE
    assert any("current-loop failure reason=6" in item for item in report.blockers)


def test_sustained_hold_hard_failure_blocks_autotune():
    driver = _driver_ready_for_autotune()
    driver.diagnostics.active.last_current_loop_hold[driver.oid] = {
        "hold_status": 3,
        "warning_flags": 0,
    }

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_BLOCKED
    assert any("sustained-hold hard failure status=3" in item for item in report.blockers)


def test_closed_loop_activation_warning_is_ready_with_warnings_and_normal_policy():
    driver = _driver_ready_for_autotune()
    driver.diagnostics.active.last_closed_loop_activation[driver.oid] = {
        "entry_status": 4,
    }

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY_WITH_WARNINGS
    assert report.installed_tuning_policy == POLICY_NORMAL
    assert any("bounded closed-loop entry drift" in item for item in report.warnings)


def test_sustained_hold_warning_flags_are_ready_with_warnings_and_normal_policy():
    driver = _driver_ready_for_autotune()
    driver.diagnostics.active.last_current_loop_hold[driver.oid] = {
        "hold_status": 1,
        "warning_flags": 3,
    }

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_READY_WITH_WARNINGS
    assert report.installed_tuning_policy == POLICY_NORMAL
    assert any("bounded sustained-hold warning flags=3" in item for item in report.warnings)


def test_closed_loop_activation_hard_failures_block_autotune():
    for status in (2, 3):
        driver = _driver_ready_for_autotune()
        driver.diagnostics.active.last_closed_loop_activation[driver.oid] = {
            "entry_status": status,
        }

        report = resolve_autotune_readiness(driver)

        assert report.result == RESULT_BLOCKED
        assert any(
            f"closed-loop entry hard failure status={int(status)}" in item
            for item in report.blockers
        )


def test_sustained_hold_status_4_blocks_autotune():
    driver = _driver_ready_for_autotune()
    driver.diagnostics.active.last_current_loop_hold[driver.oid] = {
        "hold_status": 4,
        "warning_flags": 0,
    }

    report = resolve_autotune_readiness(driver)

    assert report.result == RESULT_BLOCKED
    assert any("sustained-hold hard failure status=4" in item for item in report.blockers)
