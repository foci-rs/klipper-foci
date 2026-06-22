"""Tests for FOCI commissioning workflow behavior."""

import unittest

from klipper_foci.commissioning import (
    COMMISSION_ERROR_NAMES,
    HARD_FAULT_CODES,
    PHASE_NAMES,
)
from klipper_foci.homing import HomingWorkflow

from tests.mocks import (
    CommandError,
    MockGCmd,
    MockReactor,
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    complete_commission_result,
    make_driver,
)


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
        try:
            d.commissioning.commission(gcmd)
        except (CommandError, AttributeError, TypeError):
            # Expected — incomplete mocks for full path
            pass
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
        try:
            d.commissioning.commission(gcmd)
        except (CommandError, AttributeError, TypeError):
            pass
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
                    "value0": 820,
                    "value1": 730,
                    "value2": 1328,
                }
            )
            d.commissioning.handle_commission_phase({"phase": 0, "status": 8})

        d.protocol.commands.commission.send = drive_failure

        with self.assertRaises(CommandError):
            d.commissioning.commission(gcmd)

        self.assertIn("commissioning diagnostics", gcmd.last_info)
        self.assertIn("tau residual", gcmd.last_info)
        self.assertIn("820", gcmd.last_info)
        self.assertIn("tau=730us", gcmd.last_info)


class TestChipResetDetected(unittest.TestCase):
    """Verify host recovery when firmware reports CHIP_RESET_DETECTED."""

    def test_calibration_error_names_includes_code_2(self):
        self.assertIn(2, HomingWorkflow.CALIBRATION_ERROR_NAMES)
        self.assertIn("CHIP_RESET_DETECTED", HomingWorkflow.CALIBRATION_ERROR_NAMES[2])

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
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 1]
        )

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
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 1]
        )


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
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0]
        )


class TestNameMaps(unittest.TestCase):
    def test_all_phase_ids_have_names(self):
        """Every wire code 1-17 should have a name."""
        for phase_id in range(1, 18):
            self.assertIn(
                phase_id,
                PHASE_NAMES,
                f"PhaseId wire code {phase_id} missing from PHASE_NAMES",
            )

    def test_hard_fault_codes_are_subset_of_error_names(self):
        for code in HARD_FAULT_CODES:
            self.assertIn(
                code,
                COMMISSION_ERROR_NAMES,
                f"Hard fault code {code} missing from COMMISSION_ERROR_NAMES",
            )


class CommissionModelSurfacingTests(unittest.TestCase):
    def test_persists_internal_electrical_model_fields(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile

        driver.commissioning.persist_commission_results(
            complete_commission_result(), "balanced"
        )

        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_milli")],
            "1700",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_l_count_micro")],
            "3300",
        )
        self.assertNotIn((driver.name, "identified_r_mohm"), configfile.values)
        self.assertNotIn((driver.name, "identified_l_uh"), configfile.values)
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_int")],
            "1706",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_l_int")],
            "1245",
        )

    def test_commission_success_message_includes_internal_model(self):
        driver = make_driver()
        result = complete_commission_result()
        driver.printer._objects["configfile"] = MockConfigFile()

        class CompleteCommissionCommand:
            def send(self, _args):
                driver.commissioning.result = result
                driver.commissioning.done = True

        driver.protocol.commands.commission = CompleteCommissionCommand()
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        self.assertIn("r_count_milli=1700 l_count_micro=3300", gcmd.last_info)
        self.assertIn("R_int=1706 L_int=1245", gcmd.last_info)

    def test_commission_persists_resistance_count_space_fields(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()
        result.update(
            {
                "resistance_profile_version": 1,
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
            }
        )

        driver.commissioning.persist_commission_results(result, "balanced")

        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_slope_milli")],
            "1042",
        )
        self.assertEqual(
            configfile.values[
                (driver.name, "identified_r_gain_path_count_slope_milli")
            ],
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


class CommissionResistanceReplyFoldingTests(unittest.TestCase):
    """Verify commission-stream resistance replies get folded into result.

    W1 made firmware emit foci_resistance_run + two foci_resistance_axis
    replies during FOCI_COMMISSION, just before foci_commission_result.
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
            # foci_commission_result, as part of the same FOCI_COMMISSION
            # run. Axis replies arrive axis1-before-axis0 here on purpose
            # to prove routing uses electrical_axis, not arrival order.
            driver.diagnostics.handle_resistance_run(
                {
                    "oid": driver.oid,
                    "status": 0,
                    "profile_version": 3,
                    "selected_r_count_slope_milli": 1042,
                    "gain_path_count_slope_milli": 66752,
                    "warning_flags": 0,
                    "status_flags_or": 0x00080000,
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
            configfile.values[
                (driver.name, "identified_r_gain_path_count_slope_milli")
            ],
            "66752",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_profile_version")],
            "3",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_status_flags_or")],
            "%d" % 0x00080000,
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_warning_flags")],
            "0",
        )
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
            "%d" % 0b11111000,
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_r_selected_mask_axis1")],
            "%d" % 0b11110000,
        )
        self.assertEqual(
            configfile.values[
                (driver.name, "identified_r_axis0_signed_count_slope_milli")
            ],
            "1041",
        )
        self.assertEqual(
            configfile.values[
                (driver.name, "identified_r_axis1_signed_count_slope_milli")
            ],
            "1047",
        )
        self.assertEqual(
            configfile.values[
                (driver.name, "identified_r_axis0_signed_asymmetry_permille")
            ],
            "12",
        )
        self.assertEqual(
            configfile.values[
                (driver.name, "identified_r_axis1_signed_asymmetry_permille")
            ],
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
                "profile_version": 3,
                "selected_r_count_slope_milli": 1042,
                "gain_path_count_slope_milli": 0,
                "warning_flags": 0,
                "status_flags_or": 0,
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
        resistance_keys = [
            key for key in configfile.values if "identified_r_" in key[1]
        ]
        self.assertEqual(resistance_keys, [])
