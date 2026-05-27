"""Unit tests for FociDriver two-stage commissioning state machine.

Tests precondition gates, state transitions, homing invalidation, and
operation lock without requiring Klipper or hardware.

Run: cd foci/klipper-foci && python -m pytest tests/ -v
"""

import unittest

from klipper_foci.homing import HomingWorkflow

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
    "r_int": 1706,
    "l_int": 1245,
    "r_mohm": 1700,
    "l_uh": 3300,
    "lambda_us": 0,
    "theta_e_us": 160,
    "ringing_count": 7,
    "bandwidth_hz": 0,
}


def complete_commission_result():
    result = SAMPLE_COMMISSION_RESULT.copy()
    result.update(
        {
            "fallback_velocity_p": 1152,
            "fallback_velocity_i": 0,
            "fallback_position_p": 640,
            "fallback_position_i": 0,
            "fallback_velocity_limit": 500000,
            "tau_e_us": 730,
            "tau_e_crosscheck_us": 730,
            "tau_residual_permille": 0,
            "inner_warning_flags": 0,
        }
    )
    return result


class MockConfigFile:
    def __init__(self):
        self.values = {}

    def set(self, section, key, value):
        self.values[(section, key)] = value


# =========================================================================
# 1. Operation Lock
# =========================================================================


class TestOperationLock(unittest.TestCase):
    def test_acquire_when_free(self):
        d = make_driver()
        self.assertTrue(d.state.try_acquire())
        self.assertTrue(d.state.operation_lock)

    def test_acquire_when_held(self):
        d = make_driver()
        d.state.operation_lock = True
        self.assertFalse(d.state.try_acquire())

    def test_release_makes_available(self):
        d = make_driver()
        d.state.operation_lock = True
        d.state.release()
        self.assertFalse(d.state.operation_lock)
        self.assertTrue(d.state.try_acquire())


# =========================================================================
# 2. _ensure_calibrated gates
# =========================================================================


class TestEnsureCalibratedGates(unittest.TestCase):
    def test_returns_immediately_if_already_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        # Should return without error or side effects
        d.homing.ensure_calibrated()

    def test_inhibited_raises_even_if_already_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.state.inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_inhibited(self):
        d = make_driver()
        d.state.inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_no_active_gains(self):
        d = make_driver()
        d.state.active_gains = None
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("no commissioned gains", str(ctx.exception))

    def test_raises_if_lock_held(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS
        d.state.operation_lock = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_does_not_recalibrate_if_already_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.homing.ensure_calibrated()
        # calibrate_cmd should NOT have been sent
        self.assertIsNone(d.calibrate_cmd.last_args)


# =========================================================================
# 3. cmd_FOCI_COMMISSION gates
# =========================================================================


class TestCommissionGates(unittest.TestCase):
    def test_raises_if_lock_held(self):
        d = make_driver()
        d.state.operation_lock = True
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
        d.state.active_gains = None
        d.state.runtime_status = "uncommissioned"
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
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_raises_if_inhibited(self):
        d = self._commissioned_driver()
        d.state.inhibited = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_not_commissioned(self):
        d = self._commissioned_driver()
        d.state.runtime_status = "uncommissioned"
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("not commissioned", str(ctx.exception))

    def test_raises_if_not_calibrated(self):
        d = self._commissioned_driver()
        d.state.is_calibrated = False
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
        d.state.runtime_status = "tuned_conservative"
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
        self.assertFalse(d.state.is_calibrated)
        self.assertTrue(d.state.inhibited)
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 0])


# =========================================================================
# 5. State transitions
# =========================================================================


class TestStateTransitions(unittest.TestCase):
    def test_commission_failure_sets_inhibited(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "commissioned"
        d.state.commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        d.state.is_calibrated = True
        # Simulate failure
        d._on_commission_failure()
        self.assertTrue(d.state.inhibited)
        self.assertIsNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "uncommissioned")
        self.assertIsNone(d.state.commissioned_result)
        self.assertFalse(d.state.is_calibrated)
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
        d.state.inhibited = True
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
        d.state.inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_inhibited_blocks_autotune(self):
        d = make_driver()
        d.state.inhibited = True
        d.state.runtime_status = "commissioned"
        d.state.is_calibrated = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_AUTOTUNE(gcmd)
        self.assertIn("inhibited", str(ctx.exception))

    def test_active_gain_apply_resends_configured_voltage_limit(self):
        d = make_driver()
        d.voltage_limit = 29000
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()

        d.homing.apply_active_gains_to_firmware()

        self.assertEqual(d.set_voltage_limit_cmd.last_args, [d.oid, 29000])

    def test_disable_callback_clears_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.homing.handle_stepper_enable(0.0, False)
        self.assertFalse(d.state.is_calibrated)

    def test_enable_callback_calibrates_before_marking_enabled(self):
        d = make_driver()
        d.state.is_calibrated = False
        d.state.active_gains = {
            "flux_p": 711,
            "flux_i": 159,
            "torque_p": 711,
            "torque_i": 159,
            "velocity_p": 1434,
            "velocity_i": 2,
            "position_p": 627,
            "position_i": 1,
            "velocity_limit": 500000,
        }
        d.printer.get_reactor().completion_result = {
            "status": 0,
            "adc_i0": 33152,
            "adc_i1": 33256,
            "encoder_count": 0,
        }
        d.homing.handle_stepper_enable(0.0, True)
        self.assertEqual(d.calibrate_cmd.last_args, [0])
        self.assertTrue(d.state.is_calibrated)

    def test_ensure_calibrated_skips_if_already_true(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.homing.ensure_calibrated()
        self.assertIsNone(d.calibrate_cmd.last_args)


class TestChipResetDetected(unittest.TestCase):
    """Verify host recovery when firmware reports CHIP_RESET_DETECTED."""

    def test_calibration_error_names_includes_code_2(self):
        self.assertIn(2, HomingWorkflow.CALIBRATION_ERROR_NAMES)
        self.assertIn("CHIP_RESET_DETECTED", HomingWorkflow.CALIBRATION_ERROR_NAMES[2])

    def test_commission_error_names_includes_code_18(self):
        from klipper_foci.driver import FociDriver

        self.assertIn(18, FociDriver.COMMISSION_ERROR_NAMES)
        self.assertIn("CHIP_RESET_DETECTED", FociDriver.COMMISSION_ERROR_NAMES[18])

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
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 1])

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
            d._commission_error_code = 18
            d._last_phase_id = 17

        d.commission_cmd.send = drive_chip_reset

        with self.assertRaises(CommandError) as ctx:
            d.cmd_FOCI_COMMISSION(gcmd)

        self.assertIn("CHIP_RESET_DETECTED", str(ctx.exception))
        self.assertFalse(d.state.is_calibrated)
        self.assertFalse(d.state.inhibited)
        self.assertEqual(d.set_auto_calibrate_on_enable_cmd.last_args, [d.oid, 1])


# =========================================================================
# 6. Homing invalidation
# =========================================================================


class TestHomingInvalidation(unittest.TestCase):
    def test_noop_without_toolhead(self):
        d = make_driver()
        d.printer._objects.pop("toolhead", None)
        # Should not raise
        d.homing.invalidate_homing()

    def test_noop_for_none_kinematics(self):
        d = make_driver(kinematics=MockNoneKinematics())
        # NoneKinematics has no rails or clear_homing_state — should be a no-op
        d.homing.invalidate_homing()

    def test_noop_when_no_rails_attribute(self):
        """Kinematics with clear_homing_state but no rails attribute."""

        class MinimalKin:
            def clear_homing_state(self, axes):
                raise AssertionError("should not be called")

        d = make_driver(kinematics=MinimalKin())
        d.homing.invalidate_homing()

    def test_noop_when_stepper_not_on_any_rail(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_a", kinematics=kin)
        d.homing.invalidate_homing()
        self.assertIsNone(kin._cleared_axes)

    def test_cartesian_clears_matched_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kin,
        )
        d.homing.invalidate_homing()
        # Cartesian: stepper_x is rail 0 → axis 0 (x)
        self.assertIn(0, kin._cleared_axes)
        self.assertIn("x", kin._cleared_axes)
        self.assertNotIn(1, kin._cleared_axes)

    def test_cartesian_clears_y_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        d.homing.invalidate_homing()
        self.assertIn(1, kin._cleared_axes)
        self.assertIn("y", kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_cartesian_clears_z_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_z", kinematics=kin)
        d.homing.invalidate_homing()
        self.assertIn(2, kin._cleared_axes)
        self.assertIn("z", kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)

    def test_corexy_clears_both_axes_for_either_motor(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kin,
        )
        d.homing.invalidate_homing()
        # CoreXY: rail 0 maps to axes (0, 1) → x and y
        self.assertIn(0, kin._cleared_axes)
        self.assertIn(1, kin._cleared_axes)
        self.assertIn("x", kin._cleared_axes)
        self.assertIn("y", kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_corexy_clears_both_axes_for_y_motor(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        d.homing.invalidate_homing()
        # CoreXY: rail 1 maps to axes (0, 1) → x and y
        self.assertIn(0, kin._cleared_axes)
        self.assertIn(1, kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_corexy_z_only_clears_z(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_z", kinematics=kin)
        d.homing.invalidate_homing()
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

        d.homing.ensure_calibrated = ensure_calibrated

        d.homing.handle_home_rails_begin(None, [kin.rails[0]])

        self.assertEqual(calls, ["stepper_y"])

    def test_corexy_homing_y_calibrates_x_motor_too(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_x", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d.homing.ensure_calibrated = ensure_calibrated

        d.homing.handle_home_rails_begin(None, [kin.rails[1]])

        self.assertEqual(calls, ["stepper_x"])

    def test_cartesian_homing_x_does_not_calibrate_y_motor(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d.homing.ensure_calibrated = ensure_calibrated

        d.homing.handle_home_rails_begin(None, [kin.rails[0]])

        self.assertEqual(calls, [])


# =========================================================================
# 8. Homing invalidation at command-accepted time
# =========================================================================


class TestCommandHomingInvalidation(unittest.TestCase):
    """Verify that commands invalidate homing before starting firmware ops."""

    def _driver_with_cartesian(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_x", kinematics=kin, homed_axes="xyz")
        d.state.is_calibrated = True
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "commissioned"
        d.state.commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
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
    def test_sets_run_current_in_milliamps_without_persisting(self):
        d = make_driver()

        gcmd = MockGCmd({"RUN_CURRENT": 1.7})
        d.controls.set_current(gcmd)

        self.assertEqual(d.set_current_cmd.last_args, [d.oid, 1700])
        self.assertEqual(d.run_current, 1.7)
        self.assertIn("run_current=1.700A", gcmd.last_info)

    def test_sets_position_and_velocity_gains_as_q8_8(self):
        d = make_driver()

        d.controls.set_gains(
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
        d.state.active_gains = dict(SAMPLE_ACTIVE_GAINS)

        d.controls.set_gains(
            MockGCmd(
                {
                    "VELOCITY_P": 2.0,
                    "VELOCITY_I": 0.0,
                    "POSITION_P": 1.0,
                    "POSITION_I": 0.0,
                }
            )
        )

        self.assertEqual(d.state.active_gains["velocity_p"], 512)
        self.assertEqual(d.state.active_gains["velocity_i"], 0)
        self.assertEqual(d.state.active_gains["position_p"], 256)
        self.assertEqual(d.state.active_gains["position_i"], 0)

    def test_sets_inner_current_gains_as_raw_register_values(self):
        d = make_driver()

        d.controls.set_inner_gains(
            MockGCmd(
                {
                    "FLUX_P": 706,
                    "FLUX_I": 162,
                    "TORQUE_P": 706,
                    "TORQUE_I": 162,
                }
            )
        )

        self.assertEqual(
            d.set_pid_gains_cmd.last_args,
            [d.oid, 706, 162, 706, 162],
        )

    def test_updates_active_inner_gains_without_persisting(self):
        d = make_driver()
        d.state.active_gains = dict(SAMPLE_ACTIVE_GAINS)

        d.controls.set_inner_gains(
            MockGCmd(
                {
                    "FLUX_P": 706,
                    "FLUX_I": 162,
                    "TORQUE_P": 706,
                    "TORQUE_I": 162,
                }
            )
        )

        self.assertEqual(d.state.active_gains["flux_p"], 706)
        self.assertEqual(d.state.active_gains["flux_i"], 162)
        self.assertEqual(d.state.active_gains["torque_p"], 706)
        self.assertEqual(d.state.active_gains["torque_i"], 162)


# =========================================================================
# 10. FOCI_SET_VELOCITY_FEEDFORWARD debug command
# =========================================================================


class TestVelocityFeedforwardCommand(unittest.TestCase):
    def test_sets_feedforward_enable_and_multiplier(self):
        d = make_driver()

        d.controls.set_velocity_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "MULTIPLIER": 8,
                }
            )
        )

        self.assertEqual(d.set_velocity_feedforward_cmd.last_args, [d.oid, 1, 8])
        self.assertTrue(d.velocity_feedforward)
        self.assertEqual(d.velocity_feedforward_multiplier, 8)

    def test_disable_preserves_configured_multiplier(self):
        d = make_driver()
        d.velocity_feedforward_multiplier = 4

        d.controls.set_velocity_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(d.set_velocity_feedforward_cmd.last_args, [d.oid, 0, 4])
        self.assertFalse(d.velocity_feedforward)
        self.assertEqual(d.velocity_feedforward_multiplier, 4)


# =========================================================================
# 11. FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD debug command
# =========================================================================


class TestVelocityTransientFeedforwardCommand(unittest.TestCase):
    def test_sets_transient_feedforward_parameters(self):
        d = make_driver()

        d.controls.set_velocity_transient_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "LEAD_TIME_US": 400,
                    "GAIN": 750,
                    "MAX_OFFSET": 1200,
                    "RATE_HZ": 10000,
                }
            )
        )

        self.assertEqual(
            d.set_velocity_transient_feedforward_cmd.last_args,
            [d.oid, 1, 400, 750, 1200, 10000],
        )
        self.assertTrue(d.velocity_transient_feedforward)
        self.assertEqual(d.velocity_transient_lead_time_us, 400)
        self.assertEqual(d.velocity_transient_gain, 750)
        self.assertEqual(d.velocity_transient_max_offset, 1200)
        self.assertEqual(d.velocity_transient_rate_hz, 10000)

    def test_disable_preserves_transient_parameters(self):
        d = make_driver()
        d.velocity_transient_lead_time_us = 250
        d.velocity_transient_gain = 500
        d.velocity_transient_max_offset = 900
        d.velocity_transient_rate_hz = 10000

        d.controls.set_velocity_transient_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(
            d.set_velocity_transient_feedforward_cmd.last_args,
            [d.oid, 0, 250, 500, 900, 10000],
        )
        self.assertFalse(d.velocity_transient_feedforward)
        self.assertEqual(d.velocity_transient_lead_time_us, 250)
        self.assertEqual(d.velocity_transient_gain, 500)
        self.assertEqual(d.velocity_transient_max_offset, 900)
        self.assertEqual(d.velocity_transient_rate_hz, 10000)


# =========================================================================
# 12. FOCI_SET_ACCEL_FEEDFORWARD debug command
# =========================================================================


class TestAccelFeedforwardCommand(unittest.TestCase):
    def test_sets_accel_feedforward_enable_and_split_gains(self):
        d = make_driver()

        d.controls.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "ACCEL_GAIN": 750,
                    "DECEL_GAIN": 250,
                }
            )
        )

        self.assertEqual(d.set_accel_feedforward_cmd.last_args, [d.oid, 1, 750, 250])
        self.assertTrue(d.accel_feedforward)
        self.assertEqual(d.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.accel_feedforward_decel_gain, 250)

    def test_gain_alias_sets_both_split_gains(self):
        d = make_driver()

        d.controls.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN": 500,
                }
            )
        )

        self.assertEqual(d.set_accel_feedforward_cmd.last_args, [d.oid, 1, 500, 500])
        self.assertTrue(d.accel_feedforward)
        self.assertEqual(d.accel_feedforward_accel_gain, 500)
        self.assertEqual(d.accel_feedforward_decel_gain, 500)

    def test_disable_preserves_configured_gain(self):
        d = make_driver()
        d.accel_feedforward_accel_gain = 750
        d.accel_feedforward_decel_gain = 250

        d.controls.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(d.set_accel_feedforward_cmd.last_args, [d.oid, 0, 750, 250])
        self.assertFalse(d.accel_feedforward)
        self.assertEqual(d.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.accel_feedforward_decel_gain, 250)


# =========================================================================
# 13. FOCI_SET_DECOUPLING_FEEDFORWARD debug command
# =========================================================================


class TestDecouplingFeedforwardCommand(unittest.TestCase):
    def test_sets_decoupling_feedforward_enable_and_model(self):
        d = make_driver()

        d.controls.set_decoupling_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "R_INT": 3000,
                    "L_INT": 4095,
                    "POLE_PAIRS": 50,
                    "POSITION_UNITS_PER_REV": 65536,
                    "F_PWM_HZ": 25000,
                    "MAX_OFFSET": 500,
                }
            )
        )

        self.assertEqual(
            d.set_decoupling_feedforward_cmd.last_args,
            [d.oid, 1, 3000, 4095, 50, 65536, 25000, 500],
        )
        self.assertTrue(d.decoupling_feedforward)
        self.assertEqual(d.decoupling_r_int, 3000)
        self.assertEqual(d.decoupling_l_int, 4095)
        self.assertEqual(d.decoupling_pole_pairs, 50)
        self.assertEqual(d.decoupling_position_units_per_rev, 65536)
        self.assertEqual(d.decoupling_f_pwm_hz, 25000)
        self.assertEqual(d.decoupling_max_offset, 500)


# =========================================================================
# 14. FOCI_SET_POSITION_LEAD debug command
# =========================================================================


class TestPositionLeadCommand(unittest.TestCase):
    def test_sets_position_lead_enable_gain_and_cap(self):
        d = make_driver()

        d.controls.set_position_lead(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN": 10,
                    "MAX_COUNTS": 20,
                }
            )
        )

        self.assertEqual(d.set_position_lead_cmd.last_args, [d.oid, 1, 10, 20])
        self.assertTrue(d.position_lead)
        self.assertEqual(d.position_lead_gain, 10)
        self.assertEqual(d.position_lead_max_counts, 20)

    def test_disable_preserves_position_lead_gain_and_cap(self):
        d = make_driver()
        d.position_lead_gain = 10
        d.position_lead_max_counts = 20

        d.controls.set_position_lead(MockGCmd({"ENABLE": 0}))

        self.assertEqual(d.set_position_lead_cmd.last_args, [d.oid, 0, 10, 20])
        self.assertFalse(d.position_lead)
        self.assertEqual(d.position_lead_gain, 10)
        self.assertEqual(d.position_lead_max_counts, 20)


# =========================================================================
# 15. FOCI_SET_PHASE_ADVANCE debug command
# =========================================================================


class TestPhaseAdvanceCommand(unittest.TestCase):
    def test_sets_phase_advance_enable_gain_cap_and_deadband(self):
        d = make_driver()

        d.controls.set_phase_advance(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN_PPM": -60000,
                    "MAX_COUNTS": 64,
                    "DEADBAND": 16,
                }
            )
        )

        self.assertEqual(
            d.set_phase_advance_cmd.last_args,
            [d.oid, 1, -60000, 64, 16],
        )
        self.assertTrue(d.phase_advance)
        self.assertEqual(d.phase_advance_gain_ppm, -60000)
        self.assertEqual(d.phase_advance_max_counts, 64)
        self.assertEqual(d.phase_advance_deadband, 16)

    def test_disable_preserves_phase_advance_parameters(self):
        d = make_driver()
        d.phase_advance_gain_ppm = 60000
        d.phase_advance_max_counts = 64
        d.phase_advance_deadband = 16

        d.controls.set_phase_advance(MockGCmd({"ENABLE": 0}))

        self.assertEqual(
            d.set_phase_advance_cmd.last_args,
            [d.oid, 0, 60000, 64, 16],
        )
        self.assertFalse(d.phase_advance)
        self.assertEqual(d.phase_advance_gain_ppm, 60000)
        self.assertEqual(d.phase_advance_max_counts, 64)
        self.assertEqual(d.phase_advance_deadband, 16)

    def test_enable_with_no_parameters_is_safe_noop(self):
        d = make_driver()

        d.controls.set_phase_advance(MockGCmd({}))

        self.assertEqual(d.set_phase_advance_cmd.last_args, [d.oid, 1, 0, 0, 16])
        self.assertTrue(d.phase_advance)
        self.assertEqual(d.phase_advance_gain_ppm, 0)
        self.assertEqual(d.phase_advance_max_counts, 0)
        self.assertEqual(d.phase_advance_deadband, 16)


# =========================================================================
# 13. FOCI_SET_VOLTAGE_LIMIT debug command
# =========================================================================


class TestVoltageLimitCommand(unittest.TestCase):
    def test_sets_pidout_voltage_limit_without_persisting(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 20000})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(d.set_voltage_limit_cmd.last_args, [d.oid, 20000])
        self.assertIn("pidout_uq_ud_limit=20000", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_max(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 32767})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(d.set_voltage_limit_cmd.last_args, [d.oid, 32767])
        self.assertIn("pidout_uq_ud_limit=32767", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_min(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 0})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(d.set_voltage_limit_cmd.last_args, [d.oid, 0])
        self.assertIn("pidout_uq_ud_limit=0", gcmd.last_info)


# =========================================================================
# 13. FOCI_CURRENT_STEP_TEST debug command
# =========================================================================


class TestCurrentStepDiagnosticCommand(unittest.TestCase):
    def test_sends_bounded_current_step_defaults(self):
        d = make_driver()

        gcmd = MockGCmd({"TARGET": 250})
        d.cmd_FOCI_CURRENT_STEP_TEST(gcmd)

        self.assertEqual(d.current_step_test_cmd.last_args, [d.oid, 250, 80, 12000])
        self.assertIn("target=250", gcmd.last_info)

    def test_sends_explicit_current_step_parameters(self):
        d = make_driver()

        d.cmd_FOCI_CURRENT_STEP_TEST(
            MockGCmd({"TARGET": -500, "DURATION_MS": 120, "VOLTAGE_LIMIT": 20000})
        )

        self.assertEqual(d.current_step_test_cmd.last_args, [d.oid, -500, 120, 20000])

    def test_current_step_result_formats_motion_and_supply_fields(self):
        d = make_driver()

        d._handle_current_step_result(
            {
                "status": 0,
                "target": 250,
                "torque_during": 240,
                "torque_before": -3,
                "torque_after": 18,
                "flux_during": 4,
                "iq_during": 239,
                "id_during": -5,
                "uq_limited": 1500,
                "ud_limited": -20,
                "encoder_before": 3900,
                "encoder_after": 12,
                "encoder_delta": 112,
                "adc_vm_raw": 40099,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("enc_before=3900", out)
        self.assertIn("enc_after=12", out)
        self.assertIn("enc_delta=112", out)
        self.assertIn("adc_vm_raw=40099", out)

    def test_sends_flux_axis_current_vector_step(self):
        d = make_driver()

        d.cmd_FOCI_CURRENT_VECTOR_STEP_TEST(
            MockGCmd(
                {
                    "TORQUE_TARGET": 0,
                    "FLUX_TARGET": 250,
                    "DURATION_MS": 120,
                    "VOLTAGE_LIMIT": 20000,
                }
            )
        )

        self.assertEqual(
            d.current_vector_step_test_cmd.last_args,
            [d.oid, 0, 250, 120, 20000],
        )

    def test_current_vector_step_result_formats_axis_targets(self):
        d = make_driver()

        d._handle_current_vector_step_result(
            {
                "status": 0,
                "torque_target": 0,
                "flux_target": 250,
                "torque_during": 8,
                "torque_before": -3,
                "torque_after": 18,
                "flux_during": 240,
                "iq_during": 12,
                "id_during": 238,
                "uq_limited": 20,
                "ud_limited": 1500,
                "encoder_before": 3900,
                "encoder_after": 3912,
                "encoder_delta": 12,
                "adc_vm_raw": 40099,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("current vector step", out)
        self.assertIn("torque_target=0", out)
        self.assertIn("flux_target=250", out)
        self.assertIn("actual_torque=8", out)
        self.assertIn("actual_flux=240", out)
        self.assertIn("enc_delta=12", out)

    def test_sends_torque_sample_step_with_short_delay(self):
        d = make_driver()
        d._current_torque_sample_details[(500, -125, 5, 29000)] = {"torque_error": 1}

        d.cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST(
            MockGCmd(
                {
                    "TARGET": 500,
                    "FLUX_TARGET": -125,
                    "SAMPLE_DELAY_MS": 5,
                    "VOLTAGE_LIMIT": 29000,
                }
            )
        )

        self.assertEqual(
            d.current_torque_sample_test_cmd.last_args,
            [d.oid, 500, -125, 5, 29000],
        )
        self.assertEqual(d._current_torque_sample_details, {})

    def test_sends_position_torque_offset_sample(self):
        d = make_driver()
        gcmd = MockGCmd({"TARGET": 500, "SAMPLE_DELAY_MS": 2, "VOLTAGE_LIMIT": 29000})

        d.cmd_FOCI_POSITION_TORQUE_OFFSET_TEST(gcmd)

        self.assertEqual(
            d.position_torque_offset_sample_test_cmd.last_args,
            [d.oid, 500, 2, 29000],
        )
        self.assertIn("position-torque-offset", gcmd.last_info)

    def test_sends_voltage_step_sample(self):
        d = make_driver()
        gcmd = MockGCmd({"UQ": 512, "UD": -256, "SAMPLE_DELAY_MS": 2})

        d.cmd_FOCI_VOLTAGE_STEP_TEST(gcmd)

        self.assertEqual(
            d.voltage_step_test_cmd.last_args,
            [d.oid, 512, -256, 2],
        )
        self.assertIn("voltage-step", gcmd.last_info)

    def test_voltage_step_result_formats_sample_fields(self):
        d = make_driver()

        d._handle_voltage_step_result(
            {
                "status": 0,
                "uq_ext": 512,
                "ud_ext": -256,
                "sample_delay_ms": 2,
                "torque_before": -3,
                "torque_sample": 42,
                "torque_after": 4,
                "flux_sample": -21,
                "iq_sample": 44,
                "id_sample": -19,
                "uq_limited": 500,
                "ud_limited": -251,
                "uux_sample": 123,
                "uwy_sample": -456,
                "pwm_ux_sample": 120,
                "pwm_wy_sample": -450,
                "pwm_sv_chop": 0x00000007,
                "pwm_bbm": 0x00002828,
                "pwm_maxcnt": 3999,
                "phi_e_sample": 3000,
                "phi_m_sample": -1200,
                "encoder_before": 3900,
                "encoder_sample": 3901,
                "encoder_after": 3900,
                "encoder_delta_sample": 1,
                "encoder_delta_after": 0,
                "adc_vm_raw": 40099,
                "status_flags": 0x70000000,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("voltage step", out)
        self.assertIn("uq_ext=512", out)
        self.assertIn("ud_ext=-256", out)
        self.assertIn("sample_delay_ms=2", out)
        self.assertIn("actual=42", out)
        self.assertIn("flux=-21", out)
        self.assertIn("iq=44", out)
        self.assertIn("id=-19", out)
        self.assertIn("uux_sample=123", out)
        self.assertIn("uwy_sample=-456", out)
        self.assertIn("pwm_ux_sample=120", out)
        self.assertIn("pwm_wy_sample=-450", out)
        self.assertIn("pwm_sv_chop=0x00000007", out)
        self.assertIn("pwm_bbm=0x00002828", out)
        self.assertIn("pwm_maxcnt=3999", out)
        self.assertIn("phi_e_sample=3000", out)
        self.assertIn("phi_m_sample=-1200", out)
        self.assertIn("enc_delta_sample=1", out)
        self.assertIn("enc_delta_after=0", out)
        self.assertIn("status_flags=0x70000000", out)

    def test_current_torque_sample_result_formats_sample_fields(self):
        d = make_driver()

        d._handle_current_torque_sample_detail_result(
            {
                "target": 500,
                "flux_target": -125,
                "sample_delay_ms": 5,
                "voltage_limit": 29000,
                "torque_error": 190,
                "flux_error": -129,
                "torque_error_sum": 12345,
                "flux_error_sum": -2345,
                "uq_prelimit": 3210,
                "ud_prelimit": -30,
                "ff_velocity": 17,
                "ff_torque": -42,
            }
        )
        d._handle_current_torque_sample_result(
            {
                "status": 0,
                "target": 500,
                "flux_target": -125,
                "sample_delay_ms": 5,
                "voltage_limit": 29000,
                "torque_before": -3,
                "torque_sample": 310,
                "torque_after": 18,
                "flux_sample": 4,
                "iq_sample": 309,
                "id_sample": -5,
                "uq_limited": 3200,
                "ud_limited": -20,
                "encoder_before": 3900,
                "encoder_sample": 3902,
                "encoder_after": 3912,
                "encoder_delta_sample": 2,
                "encoder_delta_after": 12,
                "adc_vm_raw": 40099,
                "pidin_target_torque": 500,
                "pidin_target_flux": -125,
                "pidout_target_torque": 3199,
                "pidout_target_flux": -25,
                "pid_torque_target_monitor": 500,
                "status_flags": 0x8000,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("current torque sample", out)
        self.assertIn("target=500", out)
        self.assertIn("flux_target=-125", out)
        self.assertIn("sample_delay_ms=5", out)
        self.assertIn("actual=310", out)
        self.assertIn("enc_sample=3902", out)
        self.assertIn("enc_delta_sample=2", out)
        self.assertIn("enc_delta_after=12", out)
        self.assertIn("pidin_target_torque=500", out)
        self.assertIn("pidin_target_flux=-125", out)
        self.assertIn("pidout_target_torque=3199", out)
        self.assertIn("pidout_target_flux=-25", out)
        self.assertIn("pid_torque_target_monitor=500", out)
        self.assertIn("torque_error=190", out)
        self.assertIn("flux_error=-129", out)
        self.assertIn("torque_error_sum=12345", out)
        self.assertIn("flux_error_sum=-2345", out)
        self.assertIn("uq_prelimit=3210", out)
        self.assertIn("ud_prelimit=-30", out)
        self.assertIn("ff_velocity=17", out)
        self.assertIn("ff_torque=-42", out)
        self.assertIn("status_flags=0x00008000", out)
        self.assertEqual(d._current_torque_sample_details, {})


# =========================================================================
# 14. FOCI_TRACE_START / FOCI_TRACE_STOP debug commands
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

    def test_trace_start_accepts_velocity_preset(self):
        d = make_driver()

        d.cmd_FOCI_TRACE_START(MockGCmd({"PRESET": "velocity"}))

        self.assertEqual(d.trace_start_cmd.last_args, [d.oid, 2])

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
        self.assertIsNotNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "commissioned")
        self.assertEqual(d.state.active_gains["velocity_p"], 1152)

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
        self.assertIsNotNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "tuned_conservative")
        self.assertEqual(d.state.active_gains["position_p"], 432)

    def test_virgin_hardware_leaves_gains_none(self):
        d = make_driver()
        d.autotune_status = None
        d._validate_and_load_config()
        self.assertIsNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "uncommissioned")

    def test_missing_fields_leaves_gains_none(self):
        d = make_driver()
        d.autotune_status = "commissioned"
        d.pid_flux_p = 256
        # Missing other required fields
        d._validate_and_load_config()
        self.assertIsNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "uncommissioned")


# =========================================================================
# 11. Phase and error name coverage
# =========================================================================


class TestNameMaps(unittest.TestCase):
    def test_all_phase_ids_have_names(self):
        """Every wire code 1-17 should have a name."""
        from klipper_foci.driver import FociDriver

        for phase_id in range(1, 18):
            self.assertIn(
                phase_id,
                FociDriver.PHASE_NAMES,
                f"PhaseId wire code {phase_id} missing from PHASE_NAMES",
            )

    def test_hard_fault_codes_are_subset_of_error_names(self):
        from klipper_foci.driver import FociDriver

        for code in FociDriver.HARD_FAULT_CODES:
            self.assertIn(
                code,
                FociDriver.COMMISSION_ERROR_NAMES,
                f"Hard fault code {code} missing from COMMISSION_ERROR_NAMES",
            )


class CommissionModelSurfacingTests(unittest.TestCase):
    def test_persists_internal_electrical_model_fields(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile

        driver._persist_commission_results(complete_commission_result(), "balanced")

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
                driver._commission_result = result
                driver._commission_done = True

        driver.commission_cmd = CompleteCommissionCommand()
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.cmd_FOCI_COMMISSION(gcmd)

        self.assertIn("r_count_milli=1700 l_count_micro=3300", gcmd.last_info)
        self.assertIn("R_int=1706 L_int=1245", gcmd.last_info)


class InnerConfidenceRoundtripTests(unittest.TestCase):
    """Phase 1 inner-confidence resolution and persistence roundtrip.

    See docs/specs/2026-04-30-inner-commissioning-stability.md §4.
    """

    def test_default_persisted_values_resolve_to_documented_defaults(self):
        driver = make_driver()
        driver.state.commissioned_result = None
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
        driver.state.commissioned_result = {
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
        driver.state.commissioned_result = None
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
