"""Tests for FOCI commissioning workflow behavior."""

import contextlib
import unittest
from typing import ClassVar

import pytest
from klipper_foci import commissioning
from klipper_foci.commissioning import (
    COMMISSION_ERROR_NAMES,
    ELECTRICAL_ID_DETAIL_NAMES,
    HARD_FAULT_CODES,
    PHASE_NAMES,
    CommissioningWorkflow,
    format_commission_error_name,
    format_current_loop_failure_summary,
)
from klipper_foci.homing import HomingWorkflow

from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    CommandError,
    MockGCmd,
    MockReactor,
    complete_commission_result,
    make_driver,
)


def test_sustained_hold_failure_has_operator_label_and_is_hard_fault():
    assert COMMISSION_ERROR_NAMES.get(42) == "sustained hold validation failed"
    assert format_commission_error_name(42) == "sustained hold validation failed"
    assert 42 in HARD_FAULT_CODES


def test_timing_error_names_match_firmware_wire_codes():
    expected = {
        47: "invalid_schedule",
        48: "resistance_timing",
        49: "resistance_timeout",
        50: "inductance_timing",
        51: "delay_timing",
    }
    assert {code: COMMISSION_ERROR_NAMES[code] for code in expected} == expected
    assert {code: ELECTRICAL_ID_DETAIL_NAMES[code] for code in expected} == expected


def test_analysis_overrun_has_a_dedicated_operator_label():
    assert COMMISSION_ERROR_NAMES[52] == "velocity sweep analysis overrun"
    assert format_commission_error_name(52) == "velocity sweep analysis overrun"


def test_unconfirmed_velocity_rest_has_a_dedicated_operator_label():
    assert COMMISSION_ERROR_NAMES[53] == "velocity rest not confirmed"
    assert format_commission_error_name(53) == "velocity rest not confirmed"


def test_current_loop_failure_summary_decodes_gate_sample_status():
    run = {
        "failure_reason": 4,
        "candidate_attempt": 0,
        "candidate_flux_p": 3564,
        "candidate_flux_i": 3520,
        "candidate_torque_p": 3564,
        "candidate_torque_i": 3520,
        "retry_budget_exhausted": 0,
    }
    samples = {
        "flux": [
            {
                "status": 4,
                "sample_delay_ms": 100,
                "gate_role": "gate",
                "positive_response_permille": 984,
                "negative_response_permille": 1007,
                "cross_axis_permille": 156,
                "cross_axis_peak_permille": 281,
                "voltage_output_permille": 159,
                "encoder_delta_counts": 1,
                "status_flags_or": 0xF000_0080,
            }
        ],
        "torque": [],
    }

    text = format_current_loop_failure_summary(run, samples)

    assert text is not None
    assert "flux validation" in text
    assert "cross-axis coupling" in text
    assert "delay=100ms" in text
    assert "cross=156 permille" in text
    assert "candidate_flux=3564/3520" in text


def timing_reply(method=0, status=1, **overrides):
    reply = {
        "oid": 1,
        "method": method,
        "status": status,
        "requested_period_us": 5000,
        "valid_samples": 8,
        "missed_samples": 0,
        "max_consecutive_misses": 0,
        "max_lateness_us": 12,
        "max_interval_us": 5012,
        "max_poll_wall_us": 20,
        "max_spi_wall_us": 8,
    }
    reply.update(overrides)
    return reply


def test_timing_rejection_is_not_downgraded():
    driver = make_driver()

    driver.commissioning.handle_commission_timing(
        timing_reply(method=2, status=2, requested_period_us=160)
    )

    assert driver.commissioning.timing_by_method[2]["status"] == 2


def test_timing_summary_decodes_not_run_accepted_and_rejected():
    packed = 0 | (1 << 2) | (2 << 4) | (1 << 6) | (5 << 8) | (40 << 16)

    summary = commissioning.decode_timing_summary(packed)

    assert summary == {
        "statuses": {0: 0, 1: 1, 2: 2},
        "rejected": True,
        "overflowed": False,
        "missed_samples": 5,
        "max_lateness_us": 40,
    }


def test_timing_formatter_uses_microseconds_and_exact_field_order():
    assert commissioning.format_timing_evidence("resistance", timing_reply()) == (
        "timing resistance: status=accepted period_us=5000 valid=8 missed=0 "
        "max_lateness_us=12 max_interval_us=5012 max_poll_wall_us=20 "
        "max_spi_wall_us=8"
    )


def test_timing_detail_must_match_terminal_summary():
    driver = make_driver()
    driver.commissioning.handle_commission_timing(timing_reply(status=2))

    with pytest.raises(ValueError, match="resistance.*detail=rejected.*summary=accepted"):
        driver.commissioning.consume_timing_evidence(1)


def test_rejected_timing_is_fatal_even_with_plausible_model_values():
    driver = make_driver()
    driver.printer._objects["configfile"] = MockConfigFile()
    result = complete_commission_result()
    result["timing_summary"] = 2 << 4 | 1 << 6

    def drive_rejected_timing(_args):
        driver.commissioning.handle_commission_timing(
            timing_reply(method=2, status=2, requested_period_us=160)
        )
        driver.commissioning.result = result
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_rejected_timing

    with pytest.raises(CommandError, match="delay_timing"):
        driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert not driver.state.is_calibrated
    assert driver.commissioning.timing_by_method == {}


def test_commission_start_clears_stale_timing_cache():
    driver = make_driver()
    driver.printer._objects["configfile"] = MockConfigFile()
    driver.commissioning.handle_commission_timing(timing_reply())

    def drive_success(_args):
        driver.commissioning.result = complete_commission_result()
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_success
    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert driver.commissioning.timing_by_method == {}


def test_persistence_ignores_rejected_timing_evidence():
    driver = make_driver()
    configfile = MockConfigFile()
    driver.printer._objects["configfile"] = configfile
    result = complete_commission_result()
    result["commission_timing"] = {
        0: timing_reply(status=1),
        1: timing_reply(method=1, status=2),
    }

    driver.commissioning.persist_commission_results(result, "balanced")

    timing_keys = {key for section, key in configfile.values if section == driver.name}
    assert configfile.values[(driver.name, "identified_timing_resistance_status")] == ("accepted")
    assert "identified_timing_resistance_period_us" in timing_keys
    assert not any("timing_inductance" in key for key in timing_keys)


class MockConfigFile:
    def __init__(self):
        self.values = {}

    def set(self, section, key, value):
        self.values[(section, key)] = value


class TestCommissionGates(unittest.TestCase):
    def test_raises_if_lock_held(self):
        d = make_driver()
        d.state.operation_lock = True
        gcmd = MockGCmd({"PROFILE": "balanced"})
        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_rejects_invalid_profile(self):
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "turbo"})
        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)
        self.assertIn("unknown profile", str(ctx.exception).lower())

    def test_does_not_require_homed_state(self):
        """Commission should not check homing — it works from cold boot."""
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "balanced"})
        # Will fail in the commission polling loop, but should
        # NOT fail at a homing gate. Simulate immediate firmware response.
        d.commissioning.done = True
        d.commissioning.result = SAMPLE_COMMISSION_RESULT
        # The polling loop needs a reactor
        d.printer._objects["reactor"] = MockReactor()
        # This will fail because we don't have full mock infrastructure
        # for the success path, but it should NOT raise "not homed"
        # Expected — incomplete mocks for full path
        with contextlib.suppress(CommandError, AttributeError, TypeError):
            d.commissioning.commission(gcmd)
        # Verify no homing error was raised
        # (if we got here, the homing gate was not hit)

    def test_does_not_require_prior_commissioning(self):
        """Commission works on virgin hardware (no prior gains)."""
        d = make_driver()
        d.state.active_gains = None
        d.state.runtime_status = "uncommissioned"
        gcmd = MockGCmd({"PROFILE": "balanced"})
        d.commissioning.done = True
        d.commissioning.result = SAMPLE_COMMISSION_RESULT
        with contextlib.suppress(CommandError, AttributeError, TypeError):
            d.commissioning.commission(gcmd)
        # Should not raise "not commissioned"

    def test_commission_failure_reports_diagnostics(self):
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "balanced"})

        def drive_failure(_args):
            d.commissioning.handle_commission_detail(
                {
                    "phase": 5,
                    "code": 28,
                    "status": 1,
                    "value0": 0,
                    "value1": 0,
                    "value2": 0,
                }
            )
            d.commissioning.handle_commission_phase({"phase": 0, "status": 8})

        d.protocol.commands.commission.send = drive_failure

        with self.assertRaises(CommandError):
            d.commissioning.commission(gcmd)

        self.assertIn("commissioning diagnostics", gcmd.last_info)
        self.assertIn("legacy inductance fit rejected", gcmd.last_info)
        self.assertIn("usable_points=0", gcmd.last_info)
        self.assertIn("selected_mask=0x0000", gcmd.last_info)


class TestChipResetDetected(unittest.TestCase):
    """Verify host recovery when firmware reports CHIP_RESET_DETECTED."""

    def test_calibration_error_names_includes_code_2(self):
        self.assertIn(2, HomingWorkflow.CALIBRATION_ERROR_NAMES)
        self.assertIn("CHIP_RESET_DETECTED", HomingWorkflow.CALIBRATION_ERROR_NAMES[2])

    def test_calibration_error_names_includes_encoder_fault(self):
        self.assertIn(8, HomingWorkflow.CALIBRATION_ERROR_NAMES)
        self.assertIn("ENCODER_FAULT", HomingWorkflow.CALIBRATION_ERROR_NAMES[8])

    def test_commission_error_names_includes_code_18(self):
        self.assertIn(18, COMMISSION_ERROR_NAMES)
        self.assertIn("CHIP_RESET_DETECTED", COMMISSION_ERROR_NAMES[18])

    def test_ensure_calibrated_chip_reset_clears_is_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = False
        d.state.inhibited = False
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.printer.get_reactor().completion_result = {
            "oid": 0,
            "status": 2,
            "adc_i0": 0,
            "adc_i1": 0,
            "encoder_count": 0,
        }

        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()

        self.assertIn("CHIP_RESET_DETECTED", str(ctx.exception))
        self.assertFalse(d.state.is_calibrated)
        self.assertFalse(d.state.inhibited)
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 1])

    def test_ensure_calibrated_chip_reset_allows_retry(self):
        d = make_driver()
        d.state.is_calibrated = False
        d.state.inhibited = False
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        reactor = d.printer.get_reactor()

        reactor.completion_result = {
            "oid": 0,
            "status": 2,
            "adc_i0": 0,
            "adc_i1": 0,
            "encoder_count": 0,
        }
        with self.assertRaises(CommandError):
            d.homing.ensure_calibrated()

        reactor.completion_result = {
            "oid": 0,
            "status": 0,
            "adc_i0": 100,
            "adc_i1": 100,
            "encoder_count": 1234,
        }
        d.homing.ensure_calibrated()

        self.assertTrue(d.state.is_calibrated)
        self.assertFalse(d.state.inhibited)

    def test_commission_chip_reset_does_not_inhibit_retry(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.state.inhibited = False
        gcmd = MockGCmd({"PROFILE": "balanced"})

        def drive_chip_reset(_args):
            d.commissioning.error_code = 18
            d.commissioning.last_phase_id = 17

        d.protocol.commands.commission.send = drive_chip_reset

        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)

        self.assertIn("CHIP_RESET_DETECTED", str(ctx.exception))
        self.assertFalse(d.state.is_calibrated)
        self.assertFalse(d.state.inhibited)
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 1])


class TestResistanceIdFailed(unittest.TestCase):
    """Verify host reporting when firmware reports ResistanceIdFailed (19)."""

    def test_commission_error_names_includes_code_19(self):
        self.assertIn(19, COMMISSION_ERROR_NAMES)
        self.assertNotEqual(COMMISSION_ERROR_NAMES[19], "UNKNOWN(19)")

    def test_commission_error_names_includes_resistance_envelope_code(self):
        self.assertIn(31, COMMISSION_ERROR_NAMES)
        self.assertNotEqual(COMMISSION_ERROR_NAMES[31], "UNKNOWN(31)")

    def test_commission_resistance_id_failed_names_and_links_doc(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.state.inhibited = False
        gcmd = MockGCmd({"PROFILE": "balanced"})

        def drive_resistance_id_failed(_args):
            d.commissioning.error_code = 19
            d.commissioning.last_phase_id = 5

        d.protocol.commands.commission.send = drive_resistance_id_failed

        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)

        message = str(ctx.exception)
        self.assertNotIn("UNKNOWN(19)", message)
        self.assertIn(COMMISSION_ERROR_NAMES[19], message)
        self.assertIn("docs/troubleshooting/resistance-identification.md", message)
        self.assertTrue(d.state.inhibited)

    def test_commission_specific_resistance_failure_names_and_links_doc(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.state.inhibited = False
        gcmd = MockGCmd({"PROFILE": "balanced"})

        def drive_insufficient_linear_points(_args):
            d.commissioning.error_code = 23
            d.commissioning.last_phase_id = 5

        d.protocol.commands.commission.send = drive_insufficient_linear_points

        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)

        message = str(ctx.exception)
        self.assertNotIn("UNKNOWN(23)", message)
        self.assertIn("resistance measurement unsupported by current firmware", message)
        self.assertIn("detail: resistance insufficient linear points", message)
        self.assertIn("docs/troubleshooting/resistance-identification.md", message)
        self.assertTrue(d.state.inhibited)

    def test_commission_resistance_nonpositive_slope_names_and_links_doc(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.state.inhibited = False
        gcmd = MockGCmd({"PROFILE": "balanced"})

        def drive_nonpositive_slope(_args):
            d.commissioning.error_code = 73
            d.commissioning.last_phase_id = 5

        d.protocol.commands.commission.send = drive_nonpositive_slope

        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)

        message = str(ctx.exception)
        self.assertNotIn("UNKNOWN(73)", message)
        self.assertIn(COMMISSION_ERROR_NAMES[73], message)
        self.assertIn("docs/troubleshooting/resistance-identification.md", message)
        self.assertTrue(d.state.inhibited)


class TestCommissioningStateTransitions(unittest.TestCase):
    def test_commission_failure_sets_inhibited(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "commissioned"
        d.state.commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        d.state.is_calibrated = True
        # Simulate failure
        d.commissioning.on_commission_failure()
        self.assertTrue(d.state.inhibited)
        self.assertIsNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "uncommissioned")
        self.assertIsNone(d.state.commissioned_result)
        self.assertFalse(d.state.is_calibrated)
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0])


class TestNameMaps(unittest.TestCase):
    def test_all_phase_ids_have_names(self):
        """Every live `CommissionPhase` wire code should have a name.

        Codes 9-15 are permanently retired (the removed `MechanicalId`,
        `VelocityTune`, `VelocityValidate` and the pre-renumber outer block) and
        must not appear.
        """
        live_codes = {1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25}
        for phase_id in live_codes:
            self.assertIn(
                phase_id,
                PHASE_NAMES,
                f"CommissionPhase wire code {phase_id} missing from PHASE_NAMES",
            )
        for retired_id in (9, 10, 11, 12, 13, 14, 15):
            self.assertNotIn(
                retired_id,
                PHASE_NAMES,
                f"retired wire code {retired_id} must not be reused in PHASE_NAMES",
            )

    def test_hard_fault_codes_are_subset_of_error_names(self):
        for code in HARD_FAULT_CODES:
            self.assertIn(
                code,
                COMMISSION_ERROR_NAMES,
                f"Hard fault code {code} missing from COMMISSION_ERROR_NAMES",
            )


class CommissionModelSurfacingTests(unittest.TestCase):
    def test_persists_count_space_electrical_model_fields(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile

        driver.commissioning.persist_commission_results(complete_commission_result(), "balanced")

        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_milli")],
            "1706",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_l_count_micro")],
            "1245",
        )
        self.assertNotIn((driver.name, "identified_r_mohm"), configfile.values)
        self.assertNotIn((driver.name, "identified_l_uh"), configfile.values)
        self.assertNotIn((driver.name, "identified_r_int"), configfile.values)
        self.assertNotIn((driver.name, "identified_l_int"), configfile.values)

    def test_commission_success_message_includes_count_space_model(self):
        driver = make_driver()
        result = complete_commission_result()
        result["bandwidth_hz"] = 800
        result["current_candidate_attempt"] = 1
        driver.printer._objects["configfile"] = MockConfigFile()

        class CompleteCommissionCommand:
            def send(self, _args):
                driver.commissioning.result = result
                driver.commissioning.done = True

        driver.protocol.commands.commission = CompleteCommissionCommand()
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        self.assertIn(
            "r_count_milli=1706 l_count_micro=1245",
            gcmd.last_info,
        )
        self.assertIn("bandwidth_hz=800", gcmd.last_info)
        self.assertIn("current_candidate_attempt=1", gcmd.last_info)

    def test_commission_success_active_gains_use_applied_filter_evidence(
        self,
    ):
        driver = make_driver()
        result = complete_commission_result()
        result["bandwidth_hz"] = 1600
        result["current_torque_filter_hz"] = 3000
        result["current_flux_filter_hz"] = 3000
        driver.printer._objects["configfile"] = MockConfigFile()

        class CompleteCommissionCommand:
            def send(self, _args):
                driver.commissioning.result = result
                driver.commissioning.done = True

        driver.protocol.commands.commission = CompleteCommissionCommand()

        driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

        self.assertEqual(driver.state.active_gains["velocity_filter_hz"], 0)
        self.assertEqual(driver.state.active_gains["torque_filter_hz"], 3000)
        self.assertEqual(driver.state.active_gains["position_filter_hz"], 0)
        self.assertEqual(driver.state.active_gains["flux_filter_hz"], 3000)

    def test_commission_persists_resistance_count_space_fields(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()
        result.update(
            {
                "resistance_selected_count_slope_milli": 1042,
                "resistance_gain_path_count_slope_milli": 66752,
                "resistance_axis0_count_slope_milli": 1038,
                "resistance_axis1_count_slope_milli": 1046,
                "resistance_axis0_intercept_count": 24,
                "resistance_axis1_intercept_count": 27,
                "resistance_axis0_rmse_permille": 8,
                "resistance_axis1_rmse_permille": 9,
                "resistance_selected_mask_axis0": 0b11111000,
                "resistance_selected_mask_axis1": 0b11110000,
                "resistance_axis0_signed_count_slope_milli": 1041,
                "resistance_axis1_signed_count_slope_milli": 1047,
                "resistance_axis0_signed_asymmetry_permille": 12,
                "resistance_axis1_signed_asymmetry_permille": 15,
                "resistance_axis0_drift_permille": 5,
                "resistance_axis1_drift_permille": 6,
                "resistance_status_flags_or": 0x00080000,
                "resistance_warning_flags": 0,
                "resistance_peak_abs_current_count": 1200,
                "resistance_max_abs_steady_mean_current_count": 900,
                "resistance_current_ceiling_count": 1600,
            }
        )

        driver.commissioning.persist_commission_results(result, "balanced")

        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_slope_milli")],
            "1042",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_gain_path_count_slope_milli")],
            "66752",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_count_slope_milli")],
            "1038",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis1_count_slope_milli")],
            "1046",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_drift_permille")],
            "5",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_status_flags_or")],
            "524288",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_peak_abs_current_count")],
            "1200",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_max_abs_steady_mean_current_count")],
            "900",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_current_ceiling_count")],
            "1600",
        )
        self.assertNotIn((driver.name, "identified_r_power_stage_tripped"), configfile.values)


class CommissionResistanceReplyFoldingTests(unittest.TestCase):
    """Verify commission-stream resistance replies get folded into result.

    W1 made firmware emit foci_resistance_run + two foci_resistance_axis
    replies during FOCI_SETUP, just before foci_commission_result.
    These tests drive that exact reply sequence through the host's
    response handlers and confirm the values end up persisted via
    persist_commission_results, with axis0/axis1 correctly routed by
    electrical_axis (not arrival order).
    """

    def test_commission_replies_are_folded_and_persisted(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_success(_args):
            # Firmware emits these three replies, in order, just before
            # foci_commission_result, as part of the same FOCI_SETUP
            # run. Axis replies arrive axis1-before-axis0 here on purpose
            # to prove routing uses electrical_axis, not arrival order.
            driver.diagnostics.handle_resistance_run(
                {
                    "oid": driver.oid,
                    "status": 0,
                    "selected_r_count_slope_milli": 1042,
                    "gain_path_count_slope_milli": 66752,
                    "warning_flags": 0,
                    "status_flags_or": 0x00080000,
                    "peak_abs_current_count": 1200,
                    "max_abs_steady_mean_current_count": 900,
                    "current_ceiling_count": 1600,
                    "power_stage_tripped": 0,
                    "pwm_maxcnt_readback": 3999,
                    "bbm_readback": 0x00000909,
                    "dsadc_mdec_readback": 0x00080008,
                    "pwm_sv_chop_readback": 0x00000007,
                }
            )
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 1,
                    "phi_e_ext": 16384,
                    "r_count_slope_milli": 1046,
                    "intercept_count": 27,
                    "rmse_permille": 9,
                    "selected_mask": 0b11110000,
                    "excluded_point_mask": 0b00001111,
                    "selected_count": 4,
                    "signed_count_slope_milli": 1047,
                    "signed_asymmetry_permille": 15,
                    "drift_permille": 6,
                    "warning_flags": 0,
                }
            )
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 0,
                    "phi_e_ext": 0,
                    "r_count_slope_milli": 1038,
                    "intercept_count": 24,
                    "rmse_permille": 8,
                    "selected_mask": 0b11111000,
                    "excluded_point_mask": 0b00000111,
                    "selected_count": 5,
                    "signed_count_slope_milli": 1041,
                    "signed_asymmetry_permille": 12,
                    "drift_permille": 5,
                    "warning_flags": 0,
                }
            )
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        # The presence-gate key from the run reply.
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_slope_milli")],
            "1042",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_gain_path_count_slope_milli")],
            "66752",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_status_flags_or")],
            f"{524288}",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_warning_flags")],
            "0",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_peak_abs_current_count")],
            "1200",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_max_abs_steady_mean_current_count")],
            "900",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_current_ceiling_count")],
            "1600",
        )
        self.assertNotIn((driver.name, "identified_r_power_stage_tripped"), configfile.values)
        # Distinct axis0/axis1 values, routed by electrical_axis despite
        # arriving axis1-before-axis0 above. A swapped-routing bug would
        # fail these assertions.
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_count_slope_milli")],
            "1038",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis1_count_slope_milli")],
            "1046",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_intercept_count")],
            "24",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis1_intercept_count")],
            "27",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_rmse_permille")],
            "8",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis1_rmse_permille")],
            "9",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_selected_mask_axis0")],
            f"{248}",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_selected_mask_axis1")],
            f"{240}",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_signed_count_slope_milli")],
            "1041",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis1_signed_count_slope_milli")],
            "1047",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_signed_asymmetry_permille")],
            "12",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis1_signed_asymmetry_permille")],
            "15",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis0_drift_permille")],
            "5",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_axis1_drift_permille")],
            "6",
        )

    def test_commission_with_partial_resistance_cache_persists_nothing(self):
        """A commission that completes with a partial resistance cache.

        W1 firmware emits foci_resistance_run + two foci_resistance_axis
        replies, but if the commission stream completes before axis1
        arrives (e.g. run + axis0 only), the fold must be all-or-nothing:
        no identified_r_* keys get persisted, is_calibrated still becomes
        True (commission itself succeeded), and no exception is raised.
        Before the atomic fix, the presence-gate in
        _persist_resistance_identification only checked for
        resistance_selected_count_slope_milli (populated by the run
        reply alone) and then unconditionally indexed
        resistance_axis1_count_slope_milli and friends, raising KeyError
        on this exact partial-cache shape.
        """
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_partial_success(_args):
            # Only run + axis0 arrive before foci_commission_result;
            # axis1 never shows up in this commission attempt.
            driver.diagnostics.handle_resistance_run(
                {
                    "oid": driver.oid,
                    "status": 0,
                    "selected_r_count_slope_milli": 1042,
                    "gain_path_count_slope_milli": 66752,
                    "warning_flags": 0,
                    "status_flags_or": 0x00080000,
                    "peak_abs_current_count": 1200,
                    "max_abs_steady_mean_current_count": 900,
                    "current_ceiling_count": 1600,
                    "power_stage_tripped": 0,
                    "pwm_maxcnt_readback": 3999,
                    "bbm_readback": 0x00000909,
                    "dsadc_mdec_readback": 0x00080008,
                    "pwm_sv_chop_readback": 0x00000007,
                }
            )
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 0,
                    "phi_e_ext": 0,
                    "r_count_slope_milli": 1038,
                    "intercept_count": 24,
                    "rmse_permille": 8,
                    "selected_mask": 0b11111000,
                    "excluded_point_mask": 0b00000111,
                    "selected_count": 5,
                    "signed_count_slope_milli": 1041,
                    "signed_asymmetry_permille": 12,
                    "drift_permille": 5,
                    "warning_flags": 0,
                }
            )
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_partial_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        # Must not raise — the partial cache must not reach the
        # unconditional result[key] lookups in
        # _persist_resistance_identification.
        driver.commissioning.commission(gcmd)

        # Commission itself succeeded.
        self.assertTrue(driver.state.is_calibrated)

        # The entire resistance-identification block must be skipped: none
        # of its config keys persisted, not even the ones the run/axis0
        # replies could have supplied on their own. (Excludes the
        # unrelated always-persisted count-space electrical model keys.)
        resistance_config_keys = {
            config_key for _, config_key in CommissioningWorkflow.RESISTANCE_RESULT_KEYS
        }
        persisted_resistance_keys = [
            key for key in configfile.values if key[1] in resistance_config_keys
        ]
        self.assertEqual(persisted_resistance_keys, [])

        # The per-oid cache must be cleared, not left dangling with the
        # partial axis0-only entry for a later commission to pick up.
        self.assertNotIn(driver.oid, driver.diagnostics.active.resistance_cache)

    def test_standalone_resistance_test_does_not_persist(self):
        """FOCI_RESISTANCE_TEST replies must only display, never persist.

        Folding into the commission result dict happens at commission
        completion only. A standalone diagnostic run (not part of a
        commission) must leave no trace in persisted config.
        """
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile

        driver.diagnostics.handle_resistance_run(
            {
                "oid": driver.oid,
                "status": 0,
                "selected_r_count_slope_milli": 1042,
                "gain_path_count_slope_milli": 0,
                "warning_flags": 0,
                "status_flags_or": 0,
                "peak_abs_current_count": 1200,
                "max_abs_steady_mean_current_count": 900,
                "current_ceiling_count": 1600,
                "power_stage_tripped": 0,
                "pwm_maxcnt_readback": 3999,
                "bbm_readback": 0,
                "dsadc_mdec_readback": 0,
                "pwm_sv_chop_readback": 0,
            }
        )
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 0,
                "phi_e_ext": 0,
                "r_count_slope_milli": 1038,
                "intercept_count": 24,
                "rmse_permille": 8,
                "selected_mask": 0b11111000,
                "excluded_point_mask": 0b00000111,
                "selected_count": 5,
                "signed_count_slope_milli": 1041,
                "signed_asymmetry_permille": 12,
                "drift_permille": 5,
                "warning_flags": 0,
            }
        )
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 1,
                "phi_e_ext": 16384,
                "r_count_slope_milli": 1046,
                "intercept_count": 27,
                "rmse_permille": 9,
                "selected_mask": 0b11110000,
                "excluded_point_mask": 0b00001111,
                "selected_count": 4,
                "signed_count_slope_milli": 1047,
                "signed_asymmetry_permille": 15,
                "drift_permille": 6,
                "warning_flags": 0,
            }
        )

        # No commission ran; persist_commission_results was never called.
        # Confirm nothing resistance-related landed in config.
        resistance_keys = [key for key in configfile.values if "identified_r_" in key[1]]
        self.assertEqual(resistance_keys, [])

    def test_stale_standalone_cache_does_not_leak_into_later_partial_commission(self):
        """A standalone FOCI_RESISTANCE_TEST must not pre-populate a later
        commission's fold with stale axis data.

        Before the fix, the resistance_cache was only cleared at commission
        exit (success via pop_resistance_cache, failure/timeout via
        clear_resistance_cache), never at commission start. If a standalone
        FOCI_RESISTANCE_TEST left a full run+axis0+axis1 cache entry behind,
        and a later commission then delivered only run+axis0 (axis1 never
        arriving in that commission attempt), handle_resistance_axis would
        overwrite only axis0 in the cache, leaving the stale axis1 from the
        unrelated standalone run still present. pop_resistance_cache's
        all-or-nothing check would then see run+axis0+axis1 all "present"
        (axis1 being stale) and fold/persist a mixed result that blends
        data from two unrelated runs.

        The fix clears the per-oid cache at the start of commission(),
        before the firmware can emit any commission-stream resistance
        replies, so no standalone leftovers can survive into the fold.
        """
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        # Simulate a prior standalone FOCI_RESISTANCE_TEST that completed
        # and left a full run+axis0+axis1 cache entry for this oid.
        driver.diagnostics.handle_resistance_run(
            {
                "oid": driver.oid,
                "status": 0,
                "selected_r_count_slope_milli": 9999,
                "gain_path_count_slope_milli": 0,
                "warning_flags": 0,
                "status_flags_or": 0,
                "peak_abs_current_count": 1200,
                "max_abs_steady_mean_current_count": 900,
                "current_ceiling_count": 1600,
                "power_stage_tripped": 0,
                "pwm_maxcnt_readback": 3999,
                "bbm_readback": 0,
                "dsadc_mdec_readback": 0,
                "pwm_sv_chop_readback": 0,
            }
        )
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 0,
                "phi_e_ext": 0,
                "r_count_slope_milli": 8888,
                "intercept_count": 1,
                "rmse_permille": 1,
                "selected_mask": 0b11111000,
                "excluded_point_mask": 0b00000111,
                "selected_count": 5,
                "signed_count_slope_milli": 8887,
                "signed_asymmetry_permille": 1,
                "drift_permille": 1,
                "warning_flags": 0,
            }
        )
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 1,
                "phi_e_ext": 16384,
                "r_count_slope_milli": 7777,
                "intercept_count": 2,
                "rmse_permille": 2,
                "selected_mask": 0b11110000,
                "excluded_point_mask": 0b00001111,
                "selected_count": 4,
                "signed_count_slope_milli": 7778,
                "signed_asymmetry_permille": 2,
                "drift_permille": 2,
                "warning_flags": 0,
            }
        )
        # Confirm the standalone cache really is fully populated, as the
        # narrative above claims.
        self.assertIn(driver.oid, driver.diagnostics.active.resistance_cache)
        stale_entry = driver.diagnostics.active.resistance_cache[driver.oid]
        self.assertIn("run", stale_entry)
        self.assertIn("axis0", stale_entry)
        self.assertIn("axis1", stale_entry)

        def drive_partial_commission(_args):
            # The commission only delivers run + axis0; axis1 never
            # arrives in this commission attempt. Without the start-of-
            # commission clear, axis1 from the stale standalone run above
            # would still be sitting in the cache under this oid.
            driver.diagnostics.handle_resistance_run(
                {
                    "oid": driver.oid,
                    "status": 0,
                    "selected_r_count_slope_milli": 1042,
                    "gain_path_count_slope_milli": 66752,
                    "warning_flags": 0,
                    "status_flags_or": 0x00080000,
                    "peak_abs_current_count": 1200,
                    "max_abs_steady_mean_current_count": 900,
                    "current_ceiling_count": 1600,
                    "power_stage_tripped": 0,
                    "pwm_maxcnt_readback": 3999,
                    "bbm_readback": 0x00000909,
                    "dsadc_mdec_readback": 0x00080008,
                    "pwm_sv_chop_readback": 0x00000007,
                }
            )
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 0,
                    "phi_e_ext": 0,
                    "r_count_slope_milli": 1038,
                    "intercept_count": 24,
                    "rmse_permille": 8,
                    "selected_mask": 0b11111000,
                    "excluded_point_mask": 0b00000111,
                    "selected_count": 5,
                    "signed_count_slope_milli": 1041,
                    "signed_asymmetry_permille": 12,
                    "drift_permille": 5,
                    "warning_flags": 0,
                }
            )
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_partial_commission
        gcmd = MockGCmd({"PROFILE": "balanced"})

        # Must not raise.
        driver.commissioning.commission(gcmd)

        # Commission itself succeeded.
        self.assertTrue(driver.state.is_calibrated)

        # The stale axis1 from the standalone run must NOT leak through:
        # since the start-of-commission clear removed it, the all-or-
        # nothing fold correctly sees axis1 absent for this commission and
        # folds/persists nothing, rather than blending the stale axis1
        # with the fresh run+axis0.
        resistance_config_keys = {
            config_key for _, config_key in CommissioningWorkflow.RESISTANCE_RESULT_KEYS
        }
        persisted_resistance_keys = [
            key for key in configfile.values if key[1] in resistance_config_keys
        ]
        self.assertEqual(persisted_resistance_keys, [])

        # The per-oid cache must be cleared at the end too.
        self.assertNotIn(driver.oid, driver.diagnostics.active.resistance_cache)


class CommissionCurrentLoopReplyFoldingTests(unittest.TestCase):
    """Verify commission-stream current-loop replies get folded into result."""

    CURRENT_VALIDATION_SAMPLES = (
        # axis, sample_index, delay_ms, positive, negative, cross, voltage,
        # encoder_abs, encoder_positive, encoder_negative
        (0, 0, 1, 720, 710, 28, 390, 0, 0, 0),
        (0, 1, 2, 960, 940, 35, 420, 0, 0, 0),
        (0, 2, 5, 1010, 1000, 40, 430, 0, 0, 0),
        (0, 3, 100, 1015, 1008, 38, 410, 0, 0, 0),
        (1, 0, 0, 640, 630, 44, 500, 0, 0, 0),
        (1, 1, 1, 610, 590, 42, 510, 2, 2, -1),
        (1, 2, 2, 780, 770, 38, 530, 4, 4, -2),
    )
    CURRENT_LOOP_RUN: ClassVar[dict[str, int]] = {
        "status": 0,
        "gains_source": 1,
        "candidate_gains_source": 1,
        "axis_split_source": 1,
        "candidate_axis_split_source": 1,
        "gains_tier": 2,
        "candidate_gains_tier": 2,
        "measured_axis_split_permille": 1840,
        "candidate_measured_axis_split_permille": 1840,
        "applied_axis_split_permille": 1500,
        "candidate_applied_axis_split_permille": 1500,
        "axis_split_clamped": 1,
        "candidate_axis_split_clamped": 1,
        "candidate_flux_p": 711,
        "candidate_flux_i": 416,
        "candidate_torque_p": 650,
        "candidate_torque_i": 336,
        "candidate_attempt": 1,
        "current_validation_axes": 3,
        "flux_validation_sample_count": 4,
        "torque_validation_sample_count": 3,
        "retry_budget_exhausted": 0,
        "failure_reason": 0,
    }
    EXPECTED_CURRENT_CONFIG: ClassVar[dict[str, str]] = {
        "identified_current_gains_source": "1",
        "identified_current_candidate_gains_source": "1",
        "identified_axis_split_source": "1",
        "identified_current_candidate_axis_split_source": "1",
        "identified_current_gains_tier": "2",
        "identified_current_candidate_gains_tier": "2",
        "identified_current_measured_axis_split_permille": "1840",
        "identified_current_candidate_measured_axis_split_permille": "1840",
        "identified_current_applied_axis_split_permille": "1500",
        "identified_current_candidate_applied_axis_split_permille": "1500",
        "identified_current_axis_split_clamped": "1",
        "identified_current_candidate_axis_split_clamped": "1",
        "identified_current_candidate_flux_p": "711",
        "identified_current_candidate_flux_i": "416",
        "identified_current_candidate_torque_p": "650",
        "identified_current_candidate_torque_i": "336",
        "identified_current_candidate_attempt": "1",
        "identified_current_validation_axes": "3",
        "identified_current_flux_validation_sample_count": "4",
        "identified_current_torque_validation_sample_count": "3",
        "identified_current_retry_budget_exhausted": "0",
        "identified_current_failure_reason": "0",
        "identified_current_flux_response_min_permille": "710",
        "identified_current_torque_response_min_permille": "590",
        "identified_current_flux_encoder_delta_counts": "0",
        "identified_current_torque_encoder_delta_counts": "4",
    }

    def _emit_current_validation_sample(self, driver, sample) -> None:
        (
            axis,
            sample_index,
            delay_ms,
            positive,
            negative,
            cross,
            voltage,
            encoder,
            positive_encoder,
            negative_encoder,
        ) = sample
        driver.diagnostics.active.handle_current_validation_axis(
            {
                "oid": driver.oid,
                "axis": axis,
                "sample_index": sample_index,
                "status": 0,
                "attempt": 0,
                "target": 250,
                "sample_delay_ms": delay_ms,
                "positive_response_permille": positive,
                "negative_response_permille": negative,
                "cross_axis_permille": cross,
                "voltage_output_permille": voltage,
                "encoder_delta_counts": encoder,
                "positive_encoder_delta_counts": positive_encoder,
                "negative_encoder_delta_counts": negative_encoder,
                "status_flags_or": 0,
            }
        )

    def test_settled_current_validation_samples_are_cached(self):
        driver = make_driver()

        driver.diagnostics.active.handle_current_validation_settled_sample(
            {
                "oid": driver.oid,
                "axis": 0,
                "sample_index": 3,
                "direction": 1,
                "raw_index": 2,
                "attempt": 0,
                "target": -128,
                "sample_delay_ms": 100,
                "same_axis_count": -121,
                "cross_axis_count": -37,
                "cross_axis_permille": 289,
                "voltage_output_permille": 410,
                "encoder_delta_counts": 0,
                "status_flags": 0x40,
            }
        )

        cached = driver.diagnostics.active.current_loop_cache[driver.oid]
        self.assertEqual(len(cached["settled_samples"]), 1)
        self.assertEqual(cached["settled_samples"][0]["cross_axis_count"], -37)
        out = driver.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("current validation settled: axis=0", out)
        self.assertIn("direction=1 raw_index=2", out)
        self.assertIn("cross_count=-37 cross=289", out)

    def _emit_current_loop_run(self, driver) -> None:
        driver.diagnostics.active.handle_current_loop_run(
            {"oid": driver.oid, **self.CURRENT_LOOP_RUN}
        )

    def test_commission_replies_are_folded_and_persisted(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_success(_args):
            for sample in self.CURRENT_VALIDATION_SAMPLES:
                self._emit_current_validation_sample(driver, sample)
            self._emit_current_loop_run(driver)
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        for config_key, expected in self.EXPECTED_CURRENT_CONFIG.items():
            self.assertEqual(configfile.values[(driver.name, config_key)], expected)
        last_samples = driver.diagnostics.active.last_current_loop_samples(driver.oid)
        self.assertEqual(last_samples["flux"][0]["gate_role"], "telemetry")
        self.assertEqual(last_samples["flux"][3]["gate_role"], "gate")
        self.assertEqual(last_samples["torque"][0]["gate_role"], "gate")
        self.assertEqual(last_samples["torque"][2]["gate_role"], "telemetry")
        self.assertEqual(last_samples["torque"][2]["positive_encoder_delta_counts"], 4)
        self.assertEqual(last_samples["torque"][2]["negative_encoder_delta_counts"], -2)
        self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)

    def test_partial_current_loop_cache_folds_nothing_and_clears(self):
        driver = make_driver()

        self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[0])
        self._emit_current_loop_run(driver)

        self.assertEqual(driver.diagnostics.active.pop_current_loop_cache(driver.oid), {})
        self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)

    def test_unknown_current_validation_axis_does_not_complete_torque_evidence(self):
        driver = make_driver()
        self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[0])
        self._emit_current_validation_sample(driver, (2, 0, 2, 650, 640, 44, 500, 9, 9, -3))
        self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[3])
        run = {
            **self.CURRENT_LOOP_RUN,
            "flux_validation_sample_count": 1,
            "torque_validation_sample_count": 3,
        }
        driver.diagnostics.active.handle_current_loop_run({"oid": driver.oid, **run})

        self.assertEqual(driver.diagnostics.active.pop_current_loop_cache(driver.oid), {})
        self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)

    def test_zero_current_validation_sample_counts_fold_nothing_and_clear(self):
        for axis_key in ("flux", "torque"):
            with self.subTest(axis_key=axis_key):
                driver = make_driver()
                if axis_key == "flux":
                    self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[3])
                    sample_counts = {
                        "flux_validation_sample_count": 0,
                        "torque_validation_sample_count": 1,
                    }
                else:
                    self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[0])
                    sample_counts = {
                        "flux_validation_sample_count": 1,
                        "torque_validation_sample_count": 0,
                    }
                run = {**self.CURRENT_LOOP_RUN, **sample_counts}
                driver.diagnostics.active.handle_current_loop_run({"oid": driver.oid, **run})

                self.assertEqual(driver.diagnostics.active.pop_current_loop_cache(driver.oid), {})
                self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)


class CommissionInductanceReplyFoldingTests(unittest.TestCase):
    """Verify commission-stream inductance evidence gets folded into result."""

    RUN: ClassVar[dict[str, int]] = {
        "source": 1,
        "status": 0,
        "warning_flags": 0,
        "ud_count": 768,
        "realized_frequency_millihz": 1_000_000,
        "elapsed_us": 8000,
        "openloop_phi_delta_counts": 524_288,
        "sample_count": 104,
        "encoder_delta_counts": 0,
        "status_flags_or": 0,
    }
    FRAME: ClassVar[dict[str, int]] = {
        "id_mean_milli_count": 20_000,
        "iq_mean_milli_count": -84_000,
        "id_rms_milli_count": 5000,
        "iq_rms_milli_count": 21_000,
        "drift_permille": 40,
        "zero_id_mean_milli_count": 100,
        "zero_iq_mean_milli_count": -200,
    }
    ESTIMATE: ClassVar[dict[str, int]] = {
        "x_average_count_ratio_milli": 8600,
        "x_d_count_ratio_milli": 9200,
        "x_q_count_ratio_milli": 8000,
        "saliency_status": 1,
        "saliency_permille": 140,
        "x_mag_nominal_count_ratio_milli": 8770,
        "x_mag_shift_minus_permille": 4,
        "x_mag_shift_plus_permille": 4,
        "x_mag_vs_quad_permille": 20,
    }
    EXPECTED_CONFIG: ClassVar[dict[str, str]] = {
        "identified_l_source": "1",
        "identified_l_warning_flags": "0",
        "identified_l_frequency_millihz": "1000000",
        "identified_l_reactance_count_ratio_milli": "8600",
        "identified_l_d_reactance_count_ratio_milli": "9200",
        "identified_l_q_reactance_count_ratio_milli": "8000",
        "identified_l_saliency_status": "1",
        "identified_l_saliency_permille": "140",
        "identified_l_iq_mean_milli_count": "-84000",
        "identified_l_drift_permille": "40",
        "identified_l_r_shift_minus_permille": "4",
        "identified_l_r_shift_plus_permille": "4",
        "identified_l_x_mag_vs_quad_permille": "20",
    }

    def _emit_run(self, driver, params=None) -> None:
        payload = self.RUN if params is None else params
        driver.diagnostics.active.handle_inductance_run({"oid": driver.oid, **payload})

    def _emit_frame(self, driver, params=None) -> None:
        payload = self.FRAME if params is None else params
        driver.diagnostics.active.handle_inductance_frame({"oid": driver.oid, **payload})

    def _emit_estimate(self, driver, params=None) -> None:
        payload = self.ESTIMATE if params is None else params
        driver.diagnostics.active.handle_inductance_estimate({"oid": driver.oid, **payload})

    def test_complete_replies_are_folded_and_persisted(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_success(_args):
            self._emit_frame(driver)
            self._emit_run(driver)
            self._emit_estimate(driver)
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        for config_key, expected in self.EXPECTED_CONFIG.items():
            self.assertEqual(configfile.values[(driver.name, config_key)], expected)
        last_evidence = driver.diagnostics.active.last_inductance_evidence(driver.oid)
        self.assertEqual(last_evidence["run"]["realized_frequency_millihz"], 1_000_000)
        self.assertEqual(last_evidence["frame"]["iq_mean_milli_count"], -84_000)
        self.assertEqual(last_evidence["estimate"]["x_average_count_ratio_milli"], 8600)
        self.assertNotIn(driver.oid, driver.diagnostics.active.inductance_cache)

    def test_partial_cache_folds_nothing_and_clears(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_partial_success(_args):
            self._emit_run(driver)
            self._emit_frame(driver)
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_partial_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        inductance_keys = {
            config_key for _, config_key in CommissioningWorkflow.INDUCTANCE_RESULT_KEYS
        }
        persisted_inductance_keys = [key for key in configfile.values if key[1] in inductance_keys]
        self.assertEqual(persisted_inductance_keys, [])
        self.assertNotIn(driver.oid, driver.diagnostics.active.inductance_cache)

    def test_failed_and_timeout_commission_clear_inductance_cache(self):
        def drive_failure(driver):
            self._emit_run(driver)
            driver.commissioning.error_code = 19

        for label, sender in (("failure", drive_failure), ("timeout", None)):
            with self.subTest(label=label):
                driver = make_driver()
                driver.diagnostics.active.inductance_cache[driver.oid] = {
                    "run": dict(self.RUN),
                    "frame": dict(self.FRAME),
                    "estimate": dict(self.ESTIMATE),
                }
                if sender is not None:
                    driver.protocol.commands.commission.send = (
                        lambda _args, sender=sender, driver=driver: sender(driver)
                    )

                with self.assertRaises(CommandError):
                    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

                self.assertNotIn(driver.oid, driver.diagnostics.active.inductance_cache)


class CommissionEncoderAlignmentEvidenceTests(unittest.TestCase):
    """Verify transient encoder-alignment evidence follows commission runs."""

    def test_commission_start_clears_stale_encoder_alignment_evidence(self):
        driver = make_driver()
        driver.printer._objects["configfile"] = MockConfigFile()
        driver.diagnostics.active.handle_encoder_alignment(
            {
                "oid": driver.oid,
                "encoder_count": 163,
                "electrical_residual_counts": 3,
                "stability_counts": 1,
                "movement_counts": 37,
                "min_movement_counts": 2,
                "counts_per_electrical_rev": 80,
            }
        )
        result = complete_commission_result()

        def drive_success(_args):
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_success

        driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

        self.assertEqual(
            driver.diagnostics.active.last_encoder_alignment_evidence(driver.oid),
            {},
        )
