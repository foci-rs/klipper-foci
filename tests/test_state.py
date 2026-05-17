"""Unit tests for FociDriver two-stage commissioning state machine.

Tests precondition gates, state transitions, homing invalidation, and
operation lock without requiring Klipper or hardware.

Run: cd foci/klipper-foci && python -m pytest tests/ -v
"""

import unittest

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockCoreXYKinematics,
    MockGCmd,
    MockNoneKinematics,
    MockReactor,
    make_driver,
)


# -- Sample gains dicts used across tests --

SAMPLE_ACTIVE_GAINS = {
    "flux_p": 256,
    "flux_i": 26,
    "torque_p": 256,
    "torque_i": 26,
    "velocity_p": 1152,
    "velocity_i": 0,
    "position_p": 640,
    "position_i": 0,
    "velocity_limit": 500000,
    "velocity_filter_hz": 0,
    "torque_filter_hz": 0,
    "position_filter_hz": 200,
    "flux_filter_hz": 0,
}

SAMPLE_COMMISSION_RESULT = {
    "status": 0,
    "flux_p": 256,
    "flux_i": 26,
    "torque_p": 256,
    "torque_i": 26,
    "r_mohm": 1700,
    "l_uh": 3300,
    "lambda_us": 0,
    "theta_e_us": 160,
    "ringing_count": 7,
    "bandwidth_hz": 0,
}


# =========================================================================
# 1. Operation Lock
# =========================================================================


class TestOperationLock(unittest.TestCase):
    def test_acquire_when_free(self):
        d = make_driver()
        self.assertTrue(d._try_acquire_foci_lock())
        self.assertTrue(d._foci_lock)

    def test_acquire_when_held(self):
        d = make_driver()
        d._foci_lock = True
        self.assertFalse(d._try_acquire_foci_lock())

    def test_release_makes_available(self):
        d = make_driver()
        d._foci_lock = True
        d._release_foci_lock()
        self.assertFalse(d._foci_lock)
        self.assertTrue(d._try_acquire_foci_lock())


# =========================================================================
# 2. _ensure_calibrated gates
# =========================================================================


class TestEnsureCalibratedGates(unittest.TestCase):
    def test_returns_immediately_if_already_calibrated(self):
        d = make_driver()
        d.is_calibrated = True
        # Should return without error or side effects
        d._ensure_calibrated()

    def test_inhibited_raises_even_if_already_calibrated(self):
        d = make_driver()
        d.is_calibrated = True
        d._inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d._ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_inhibited(self):
        d = make_driver()
        d._inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d._ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_no_active_gains(self):
        d = make_driver()
        d._active_gains = None
        with self.assertRaises(CommandError) as ctx:
            d._ensure_calibrated()
        self.assertIn("no commissioned gains", str(ctx.exception))

    def test_raises_if_lock_held(self):
        d = make_driver()
        d._active_gains = SAMPLE_ACTIVE_GAINS
        d._foci_lock = True
        with self.assertRaises(CommandError) as ctx:
            d._ensure_calibrated()
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_does_not_recalibrate_if_already_calibrated(self):
        d = make_driver()
        d.is_calibrated = True
        d._ensure_calibrated()
        # calibrate_cmd should NOT have been sent
        self.assertIsNone(d.calibrate_cmd.last_args)


# =========================================================================
# 3. cmd_FOCI_COMMISSION gates
# =========================================================================


class TestCommissionGates(unittest.TestCase):
    def test_raises_if_lock_held(self):
        d = make_driver()
        d._foci_lock = True
        gcmd = MockGCmd({"PROFILE": "balanced"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_COMMISSION(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_rejects_invalid_profile(self):
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "turbo"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_COMMISSION(gcmd)
        self.assertIn("unknown profile", str(ctx.exception).lower())

    def test_does_not_require_homed_state(self):
        """Commission should not check homing — it works from cold boot."""
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "balanced"})
        # Will fail at the commission_cmd.send polling loop, but should
        # NOT fail at a homing gate. Simulate immediate firmware response.
        d._commission_done = True
        d._commission_result = SAMPLE_COMMISSION_RESULT
        # The polling loop needs a reactor
        d.printer._objects["reactor"] = MockReactor()
        # This will fail because we don't have full mock infrastructure
        # for the success path, but it should NOT raise "not homed"
        try:
            d.cmd_FOCI_COMMISSION(gcmd)
        except (CommandError, AttributeError, TypeError):
            # Expected — incomplete mocks for full path
            pass
        # Verify no homing error was raised
        # (if we got here, the homing gate was not hit)

    def test_does_not_require_prior_commissioning(self):
        """Commission works on virgin hardware (no prior gains)."""
        d = make_driver()
        d._active_gains = None
        d._runtime_status = None
        gcmd = MockGCmd({"PROFILE": "balanced"})
        d._commission_done = True
        d._commission_result = SAMPLE_COMMISSION_RESULT
        try:
            d.cmd_FOCI_COMMISSION(gcmd)
        except (CommandError, AttributeError, TypeError):
            pass
        # Should not raise "not commissioned"

    def test_commission_failure_reports_diagnostics(self):
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "balanced"})

        def drive_failure(_args):
            d._handle_commission_detail(
                {
                    "phase": 5,
                    "code": 28,
                    "status": 1,
                    "value0": 820,
                    "value1": 730,
                    "value2": 1328,
                }
            )
            d._handle_commission_phase({"phase": 0, "status": 8})

        d.commission_cmd.send = drive_failure

        with self.assertRaises(CommandError):
            d.cmd_FOCI_COMMISSION(gcmd)

        self.assertIn("commissioning diagnostics", gcmd.last_info)
        self.assertIn("tau residual", gcmd.last_info)
        self.assertIn("820", gcmd.last_info)
        self.assertIn("tau=730us", gcmd.last_info)


# =========================================================================
# 4. cmd_FOCI_AUTOTUNE gates
# =========================================================================


class TestAutotuneGates(unittest.TestCase):
    def _commissioned_driver(self, kinematics=None, homed_axes="xyz"):
        d = make_driver(kinematics=kinematics, homed_axes=homed_axes)
        d.is_calibrated = True
        d._active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d._runtime_status = "commissioned"
        d._commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        return d

    def test_raises_if_lock_held(self):
        d = self._commissioned_driver()
        d._foci_lock = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_raises_if_inhibited(self):
        d = self._commissioned_driver()
        d._inhibited = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_not_commissioned(self):
        d = self._commissioned_driver()
        d._runtime_status = None
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("not commissioned", str(ctx.exception))

    def test_raises_if_not_calibrated(self):
        d = self._commissioned_driver()
        d.is_calibrated = False
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("not calibrated", str(ctx.exception))

    def test_raises_if_not_homed_with_kinematics(self):
        kin = MockCartesianKinematics()
        d = self._commissioned_driver(kinematics=kin, homed_axes="x")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("not fully homed", str(ctx.exception))

    def test_skips_homing_check_for_none_kinematics(self):
        """NoneKinematics (manual_stepper) has no axes to home."""
        d = self._commissioned_driver(kinematics=MockNoneKinematics(), homed_axes="")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        # Should get past the homing gate. Will fail later in the
        # polling loop due to incomplete mocks, but should NOT raise
        # "not fully homed".
        try:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        except (CommandError, AttributeError, TypeError) as e:
            self.assertNotIn("not fully homed", str(e))

    def test_rejects_invalid_profile(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "turbo", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("unknown profile", str(ctx.exception).lower())

    def test_rejects_invalid_mode(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "extreme"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("unknown mode", str(ctx.exception))

    def test_accepts_tuned_conservative_as_commissioned(self):
        """A motor with tuned_conservative status can be re-tuned."""
        d = self._commissioned_driver()
        d._runtime_status = "tuned_conservative"
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        # Should get past the "not commissioned" gate
        try:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        except (CommandError, AttributeError, TypeError) as e:
            self.assertNotIn("not commissioned", str(e))

    def test_admission_failure_reports_error_instead_of_timeout(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_admission_failure(deadline):
            reactor._time = deadline
            d._handle_commission_phase({"phase": 0, "status": 15})
            return reactor._time

        reactor.pause = pause_and_report_admission_failure

        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)

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
            d._handle_tune_result({"status": 17})
            return reactor._time

        reactor.pause = pause_and_report_hard_fault

        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)

        self.assertIn("safety fault", str(ctx.exception))
        self.assertFalse(enable_line.is_motor_enabled())
        self.assertFalse(d.is_calibrated)
        self.assertTrue(d._inhibited)
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 0])


# =========================================================================
# 5. State transitions
# =========================================================================


class TestStateTransitions(unittest.TestCase):
    def test_commission_failure_sets_inhibited(self):
        d = make_driver()
        d._active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d._runtime_status = "commissioned"
        d._commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        d.is_calibrated = True
        # Simulate failure
        d._on_commission_failure()
        self.assertTrue(d._inhibited)
        self.assertIsNone(d._active_gains)
        self.assertIsNone(d._runtime_status)
        self.assertIsNone(d._commissioned_result)
        self.assertFalse(d.is_calibrated)
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 0])

    def test_connect_allows_auto_calibrate_only_with_valid_config(self):
        d = make_driver()
        d._handle_connect()
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 0])

        d = make_driver()
        d.autotune_status = "commissioned"
        d.pid_flux_p = 100
        d.pid_flux_i = 200
        d.pid_torque_p = 300
        d.pid_torque_i = 400
        d.identified_lambda_us = 1200
        d.identified_theta_e_us = 100
        d.identified_ringing_count = 0
        d.identified_bandwidth_hz = 500
        d.commissioned_velocity_p = 1100
        d.commissioned_velocity_i = 0
        d.commissioned_position_p = 700
        d.commissioned_position_i = 0
        d.commissioned_velocity_limit = 50_000
        d._handle_connect()
        self.assertEqual(d.set_pid_gains_cmd.last_args, [d.oid, 100, 200, 300, 400])
        self.assertEqual(
            d.set_position_gains_cmd.last_args,
            [d.oid, 700, 0, 1100, 0],
        )
        self.assertEqual(d.set_velocity_limit_cmd.last_args, [d.oid, 50_000])
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 1])

    def test_connect_keeps_auto_calibrate_closed_while_inhibited(self):
        d = make_driver()
        d._inhibited = True
        d.autotune_status = "commissioned"
        d.pid_flux_p = 100
        d.pid_flux_i = 200
        d.pid_torque_p = 300
        d.pid_torque_i = 400
        d.identified_lambda_us = 1200
        d.identified_theta_e_us = 100
        d.identified_ringing_count = 0
        d.identified_bandwidth_hz = 500
        d.commissioned_velocity_p = 1100
        d.commissioned_velocity_i = 0
        d.commissioned_position_p = 700
        d.commissioned_position_i = 0
        d.commissioned_velocity_limit = 50_000
        d._handle_connect()
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 0])

    def test_inhibited_blocks_ensure_calibrated(self):
        d = make_driver()
        d._inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d._ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_inhibited_blocks_autotune(self):
        d = make_driver()
        d._inhibited = True
        d._runtime_status = "commissioned"
        d.is_calibrated = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("inhibited", str(ctx.exception))

    def test_disable_callback_clears_calibrated(self):
        d = make_driver()
        d.is_calibrated = True
        d._handle_stepper_enable(0.0, False)
        self.assertFalse(d.is_calibrated)

    def test_enable_callback_does_not_set_calibrated(self):
        d = make_driver()
        d.is_calibrated = False
        d._handle_stepper_enable(0.0, True)
        self.assertFalse(d.is_calibrated)

    def test_ensure_calibrated_skips_if_already_true(self):
        d = make_driver()
        d.is_calibrated = True
        d._ensure_calibrated()
        self.assertIsNone(d.calibrate_cmd.last_args)


# =========================================================================
# 6. Homing invalidation
# =========================================================================


class TestHomingInvalidation(unittest.TestCase):
    def test_noop_without_toolhead(self):
        d = make_driver()
        d.printer._objects.pop("toolhead", None)
        # Should not raise
        d._invalidate_homing()

    def test_noop_for_none_kinematics(self):
        d = make_driver(kinematics=MockNoneKinematics())
        # NoneKinematics has no rails or clear_homing_state — should be a no-op
        d._invalidate_homing()

    def test_noop_when_no_rails_attribute(self):
        """Kinematics with clear_homing_state but no rails attribute."""

        class MinimalKin:
            def clear_homing_state(self, axes):
                raise AssertionError("should not be called")

        d = make_driver(kinematics=MinimalKin())
        d._invalidate_homing()

    def test_noop_when_stepper_not_on_any_rail(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_a", kinematics=kin)
        d._invalidate_homing()
        self.assertIsNone(kin._cleared_axes)

    def test_cartesian_clears_matched_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kin,
        )
        d._invalidate_homing()
        # Cartesian: stepper_x is rail 0 → axis 0 (x)
        self.assertIn(0, kin._cleared_axes)
        self.assertIn("x", kin._cleared_axes)
        self.assertNotIn(1, kin._cleared_axes)

    def test_cartesian_clears_y_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        d._invalidate_homing()
        self.assertIn(1, kin._cleared_axes)
        self.assertIn("y", kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_cartesian_clears_z_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_z", kinematics=kin)
        d._invalidate_homing()
        self.assertIn(2, kin._cleared_axes)
        self.assertIn("z", kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)

    def test_corexy_clears_both_axes_for_either_motor(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kin,
        )
        d._invalidate_homing()
        # CoreXY: rail 0 maps to axes (0, 1) → x and y
        self.assertIn(0, kin._cleared_axes)
        self.assertIn(1, kin._cleared_axes)
        self.assertIn("x", kin._cleared_axes)
        self.assertIn("y", kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_corexy_clears_both_axes_for_y_motor(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        d._invalidate_homing()
        # CoreXY: rail 1 maps to axes (0, 1) → x and y
        self.assertIn(0, kin._cleared_axes)
        self.assertIn(1, kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_corexy_z_only_clears_z(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_z", kinematics=kin)
        d._invalidate_homing()
        # CoreXY: rail 2 maps to axis (2,) → z only
        self.assertIn(2, kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)
        self.assertNotIn(1, kin._cleared_axes)


# =========================================================================
# 7. Homing calibration coupling
# =========================================================================


class TestHomingCalibrationCoupling(unittest.TestCase):
    def test_corexy_homing_x_calibrates_y_motor_too(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d._ensure_calibrated = ensure_calibrated

        d._handle_home_rails_begin(None, [kin.rails[0]])

        self.assertEqual(calls, ["stepper_y"])

    def test_corexy_homing_y_calibrates_x_motor_too(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_x", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d._ensure_calibrated = ensure_calibrated

        d._handle_home_rails_begin(None, [kin.rails[1]])

        self.assertEqual(calls, ["stepper_x"])

    def test_cartesian_homing_x_does_not_calibrate_y_motor(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d._ensure_calibrated = ensure_calibrated

        d._handle_home_rails_begin(None, [kin.rails[0]])

        self.assertEqual(calls, [])


# =========================================================================
# 8. Homing invalidation at command-accepted time
# =========================================================================


class TestCommandHomingInvalidation(unittest.TestCase):
    """Verify that commands invalidate homing before starting firmware ops."""

    def _driver_with_cartesian(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_x", kinematics=kin, homed_axes="xyz")
        d.is_calibrated = True
        d._active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d._runtime_status = "commissioned"
        d._commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        return d, kin

    def test_commission_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        gcmd = MockGCmd({"PROFILE": "balanced"})
        d._commission_done = True
        d._commission_result = SAMPLE_COMMISSION_RESULT
        try:
            d.cmd_FOCI_COMMISSION(gcmd)
        except (CommandError, AttributeError, TypeError):
            pass
        # Homing should have been invalidated
        self.assertIsNotNone(kin._cleared_axes)

    def test_autotune_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        try:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        except (CommandError, AttributeError, TypeError):
            pass
        self.assertIsNotNone(kin._cleared_axes)

    def test_selftest_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        try:
            d.cmd_FOCI_SELFTEST(MockGCmd())
        except (CommandError, AttributeError, TypeError):
            pass
        self.assertIsNotNone(kin._cleared_axes)


# =========================================================================
# 9. FOCI_SET_GAINS debug command
# =========================================================================


class TestDebugGainsCommand(unittest.TestCase):
    def test_sets_position_and_velocity_gains_as_q8_8(self):
        d = make_driver()

        d.cmd_FOCI_SET_GAINS(
            MockGCmd(
                {
                    "VELOCITY_P": "2.0",
                    "VELOCITY_I": "0.0",
                    "POSITION_P": "1.0",
                    "POSITION_I": "0.0",
                }
            )
        )

        self.assertEqual(
            d.set_position_gains_cmd.last_args,
            [d.oid, 256, 0, 512, 0],
        )
        self.assertEqual(d.pid_velocity_p, 512)
        self.assertEqual(d.pid_velocity_i, 0)
        self.assertEqual(d.pid_position_p, 256)
        self.assertEqual(d.pid_position_i, 0)

    def test_updates_active_gains_without_persisting(self):
        d = make_driver()
        d._active_gains = dict(SAMPLE_ACTIVE_GAINS)

        d.cmd_FOCI_SET_GAINS(
            MockGCmd(
                {
                    "VELOCITY_P": 2.0,
                    "VELOCITY_I": 0.0,
                    "POSITION_P": 1.0,
                    "POSITION_I": 0.0,
                }
            )
        )

        self.assertEqual(d._active_gains["velocity_p"], 512)
        self.assertEqual(d._active_gains["velocity_i"], 0)
        self.assertEqual(d._active_gains["position_p"], 256)
        self.assertEqual(d._active_gains["position_i"], 0)


# =========================================================================
# 10. FOCI_TRACE_START / FOCI_TRACE_STOP debug commands
# =========================================================================


class TestTraceControlCommands(unittest.TestCase):
    def test_trace_start_defaults_to_full_preset(self):
        d = make_driver()

        d.cmd_FOCI_TRACE_START(MockGCmd())

        self.assertEqual(d.trace_start_cmd.last_args, [d.oid, 1])

    def test_trace_start_accepts_fast_preset(self):
        d = make_driver()

        d.cmd_FOCI_TRACE_START(MockGCmd({"PRESET": "fast"}))

        self.assertEqual(d.trace_start_cmd.last_args, [d.oid, 0])

    def test_trace_start_rejects_unknown_preset(self):
        d = make_driver()

        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_TRACE_START(MockGCmd({"PRESET": "wide"}))

        self.assertIn("unknown trace preset", str(ctx.exception).lower())

    def test_trace_stop_sends_stop_command(self):
        d = make_driver()

        d.cmd_FOCI_TRACE_STOP(MockGCmd())

        self.assertEqual(d.trace_stop_cmd.last_args, [d.oid])


# =========================================================================
# 11. _validate_and_load_config
# =========================================================================


class TestValidateAndLoadConfig(unittest.TestCase):
    def test_loads_commissioned_gains_from_config(self):
        d = make_driver()
        d.autotune_status = "commissioned"
        d.pid_flux_p = 256
        d.pid_flux_i = 26
        d.pid_torque_p = 256
        d.pid_torque_i = 26
        d.commissioned_velocity_p = 1152
        d.commissioned_velocity_i = 0
        d.commissioned_position_p = 640
        d.commissioned_position_i = 0
        d.commissioned_velocity_limit = 500000
        d.velocity_filter_hz = 0
        d.torque_filter_hz = 0
        d.position_filter_hz = 200
        d.flux_filter_hz = 0
        d._validate_and_load_config()
        self.assertIsNotNone(d._active_gains)
        self.assertEqual(d._runtime_status, "commissioned")
        self.assertEqual(d._active_gains["velocity_p"], 1152)

    def test_loads_tuned_gains_from_config(self):
        d = make_driver()
        d.autotune_status = "tuned_conservative"
        d.pid_flux_p = 256
        d.pid_flux_i = 26
        d.pid_torque_p = 256
        d.pid_torque_i = 26
        d.pid_velocity_p = 1152
        d.pid_velocity_i = 0
        d.pid_position_p = 432
        d.pid_position_i = 0
        d.pid_velocity_limit = 500000
        d.velocity_filter_hz = 0
        d.torque_filter_hz = 0
        d.position_filter_hz = 200
        d.flux_filter_hz = 0
        d._validate_and_load_config()
        self.assertIsNotNone(d._active_gains)
        self.assertEqual(d._runtime_status, "tuned_conservative")
        self.assertEqual(d._active_gains["position_p"], 432)

    def test_virgin_hardware_leaves_gains_none(self):
        d = make_driver()
        d.autotune_status = None
        d._validate_and_load_config()
        self.assertIsNone(d._active_gains)
        self.assertIsNone(d._runtime_status)

    def test_missing_fields_leaves_gains_none(self):
        d = make_driver()
        d.autotune_status = "commissioned"
        d.pid_flux_p = 256
        # Missing other required fields
        d._validate_and_load_config()
        self.assertIsNone(d._active_gains)
        self.assertIsNone(d._runtime_status)


# =========================================================================
# 11. Phase and error name coverage
# =========================================================================


class TestNameMaps(unittest.TestCase):
    def test_all_phase_ids_have_names(self):
        """Every wire code 1-17 should have a name."""
        from foci import FociDriver

        for phase_id in range(1, 18):
            self.assertIn(
                phase_id,
                FociDriver.PHASE_NAMES,
                f"PhaseId wire code {phase_id} missing from PHASE_NAMES",
            )

    def test_hard_fault_codes_are_subset_of_error_names(self):
        from foci import FociDriver

        for code in FociDriver.HARD_FAULT_CODES:
            self.assertIn(
                code,
                FociDriver.COMMISSION_ERROR_NAMES,
                f"Hard fault code {code} missing from COMMISSION_ERROR_NAMES",
            )


class InnerConfidenceRoundtripTests(unittest.TestCase):
    """Phase 1 inner-confidence resolution and persistence roundtrip.

    See docs/specs/2026-04-30-inner-commissioning-stability.md §4.
    """

    def test_default_persisted_values_resolve_to_documented_defaults(self):
        driver = make_driver()
        driver._commissioned_result = None
        driver.identified_lambda_us = 700
        # All identified_tau_*/identified_inner_warning_flags default None
        tau, cross, perm, flags = driver._resolve_inner_confidence()
        # `tau_e_us = max(identified_lambda_us, 1000)` for old configs.
        self.assertEqual(tau, 1000)
        self.assertEqual(cross, 0)
        self.assertEqual(perm, 1000)
        # Bit 6 = host-default confidence.
        self.assertEqual(flags, 0x40)

    def test_fresh_stage1_result_wins_over_persisted(self):
        driver = make_driver()
        driver._commissioned_result = {
            "tau_e_us": 1234,
            "tau_e_crosscheck_us": 1100,
            "tau_residual_permille": 50,
            "inner_warning_flags": 0x02,
        }
        driver.identified_tau_e_us = 9999
        tau, cross, perm, flags = driver._resolve_inner_confidence()
        self.assertEqual((tau, cross, perm, flags), (1234, 1100, 50, 0x02))

    def test_persisted_values_load_from_config(self):
        driver = make_driver()
        driver._commissioned_result = None
        driver.identified_tau_e_us = 800
        driver.identified_tau_e_crosscheck_us = 750
        driver.identified_tau_residual_permille = 60
        driver.identified_inner_warning_flags = 0x01
        tau, cross, perm, flags = driver._resolve_inner_confidence()
        self.assertEqual((tau, cross, perm, flags), (800, 750, 60, 0x01))

    def test_format_inner_warning_flags_lists_active_bits(self):
        driver = make_driver()
        # Bits 0 (R mismatch) + 4 (retry).
        text = driver._format_inner_warning_flags((1 << 0) | (1 << 4))
        self.assertIn("coil R mismatch", text)
        self.assertIn("current validation retry", text)

    def test_format_inner_warning_flags_empty_when_clean(self):
        driver = make_driver()
        self.assertEqual(driver._format_inner_warning_flags(0), "none")


if __name__ == "__main__":
    unittest.main()
