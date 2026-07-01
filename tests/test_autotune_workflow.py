"""Tests for FOCI autotune workflow behavior."""

import unittest

from klipper_foci.commissioning import format_inner_warning_flags

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    MockNoneKinematics,
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    make_driver,
)


class TestAutotuneGates(unittest.TestCase):
    def _commissioned_driver(self, kinematics=None, homed_axes="xyz"):
        d = make_driver(kinematics=kinematics, homed_axes=homed_axes)
        d.state.is_calibrated = True
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "commissioned"
        d.state.commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        return d

    def test_raises_if_lock_held(self):
        d = self._commissioned_driver()
        d.state.operation_lock = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_raises_if_inhibited(self):
        d = self._commissioned_driver()
        d.state.inhibited = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_not_commissioned(self):
        d = self._commissioned_driver()
        d.state.runtime_status = "uncommissioned"
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("not commissioned", str(ctx.exception))

    def test_raises_if_not_calibrated(self):
        d = self._commissioned_driver()
        d.state.is_calibrated = False
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("not calibrated", str(ctx.exception))

    def test_raises_if_not_homed_with_kinematics(self):
        kin = MockCartesianKinematics()
        d = self._commissioned_driver(kinematics=kin, homed_axes="x")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("not fully homed", str(ctx.exception))

    def test_skips_homing_check_for_none_kinematics(self):
        """NoneKinematics (manual_stepper) has no axes to home."""
        d = self._commissioned_driver(kinematics=MockNoneKinematics(), homed_axes="")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        # Should get past the homing gate. Will fail later in the
        # polling loop due to incomplete mocks, but should NOT raise
        # "not fully homed".
        try:
            d.autotune.autotune(gcmd)
        except (CommandError, AttributeError, TypeError) as e:
            self.assertNotIn("not fully homed", str(e))

    def test_rejects_invalid_profile(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "turbo", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("unknown profile", str(ctx.exception).lower())

    def test_rejects_invalid_mode(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "extreme"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("unknown mode", str(ctx.exception))

    def test_accepts_tuned_conservative_as_commissioned(self):
        """A motor with tuned_conservative status can be re-tuned."""
        d = self._commissioned_driver()
        d.state.runtime_status = "tuned_conservative"
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        # Should get past the "not commissioned" gate
        try:
            d.autotune.autotune(gcmd)
        except (CommandError, AttributeError, TypeError) as e:
            self.assertNotIn("not commissioned", str(e))

    def test_admission_failure_reports_error_instead_of_timeout(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_admission_failure(deadline):
            reactor._time = deadline
            d.commissioning.handle_commission_phase({"phase": 0, "status": 15})
            return reactor._time

        reactor.pause = pause_and_report_admission_failure

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("commissioning already running", str(ctx.exception))
        self.assertNotIn("timed out", str(ctx.exception))

    def test_hard_fault_inhibits_future_raw_enable(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(
            d.stepper_name
        )
        enable_line.motor_enable(0.0)

        def pause_and_report_hard_fault(deadline):
            reactor._time = deadline
            d.autotune.handle_tune_result({"status": 17})
            return reactor._time

        reactor.pause = pause_and_report_hard_fault

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("safety fault", str(ctx.exception))
        self.assertFalse(enable_line.is_motor_enabled())
        self.assertFalse(d.state.is_calibrated)
        self.assertTrue(d.state.inhibited)
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0]
        )


class TestAutotuneStateTransitions(unittest.TestCase):
    def test_inhibited_blocks_autotune(self):
        d = make_driver()
        d.state.inhibited = True
        d.state.runtime_status = "commissioned"
        d.state.is_calibrated = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("inhibited", str(ctx.exception))


class InnerConfidenceRoundtripTests(unittest.TestCase):
    """Phase 1 inner-confidence resolution and persistence roundtrip.

    See docs/specs/2026-04-30-inner-commissioning-stability.md §4.
    """

    def test_default_persisted_values_resolve_to_documented_defaults(self):
        driver = make_driver()
        driver.state.commissioned_result = None
        driver.config.identified_lambda_us = 700
        # All identified_tau_*/identified_inner_warning_flags default None
        tau, flags = driver.autotune.resolve_inner_confidence()
        # `tau_e_us = max(identified_lambda_us, 1000)` for old configs.
        self.assertEqual(tau, 1000)
        # Bit 6 = host-default confidence.
        self.assertEqual(flags, 0x40)

    def test_fresh_stage1_result_wins_over_persisted(self):
        driver = make_driver()
        driver.state.commissioned_result = {
            "tau_e_us": 1234,
            "inner_warning_flags": 0x02,
        }
        driver.config.identified_tau_e_us = 9999
        tau, flags = driver.autotune.resolve_inner_confidence()
        self.assertEqual((tau, flags), (1234, 0x02))

    def test_persisted_values_load_from_config(self):
        driver = make_driver()
        driver.state.commissioned_result = None
        driver.config.identified_tau_e_us = 800
        driver.config.identified_inner_warning_flags = 0x01
        tau, flags = driver.autotune.resolve_inner_confidence()
        self.assertEqual((tau, flags), (800, 0x01))

    def test_format_inner_warning_flags_lists_active_bits(self):
        text = format_inner_warning_flags((1 << 0) | (1 << 5))
        self.assertIn("coil R mismatch", text)
        self.assertIn("current gains fell back to defaults", text)

    def test_format_inner_warning_flags_empty_when_clean(self):
        self.assertEqual(format_inner_warning_flags(0), "none")

    def test_format_inner_warning_flags_ignores_tau_residual_telemetry(self):
        self.assertEqual(format_inner_warning_flags(1 << 2), "none")
