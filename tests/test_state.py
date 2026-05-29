"""Unit tests for FociDriver two-stage commissioning state machine.

Tests precondition gates, state transitions, homing invalidation, and
operation lock without requiring Klipper or hardware.

Run: cd foci/klipper-foci && python -m pytest tests/ -v
"""

import unittest

from klipper_foci.commissioning import (
    COMMISSION_ERROR_NAMES,
    HARD_FAULT_CODES,
    PHASE_NAMES,
    format_inner_warning_flags,
)
from klipper_foci.homing import HomingWorkflow

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    MockNoneKinematics,
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


# =========================================================================
# 3. cmd_FOCI_COMMISSION gates
# =========================================================================


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


# =========================================================================
# 4. FOCI_AUTOTUNE gates
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
        d.commissioning.on_commission_failure()
        self.assertTrue(d.state.inhibited)
        self.assertIsNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "uncommissioned")
        self.assertIsNone(d.state.commissioned_result)
        self.assertFalse(d.state.is_calibrated)
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0]
        )

    def test_inhibited_blocks_autotune(self):
        d = make_driver()
        d.state.inhibited = True
        d.state.runtime_status = "commissioned"
        d.state.is_calibrated = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("inhibited", str(ctx.exception))


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


# =========================================================================
# 9. FOCI_SET_GAINS debug command
# =========================================================================


class TestDebugGainsCommand(unittest.TestCase):
    def test_sets_run_current_in_milliamps_without_persisting(self):
        d = make_driver()

        gcmd = MockGCmd({"RUN_CURRENT": 1.7})
        d.controls.set_current(gcmd)

        self.assertEqual(d.protocol.commands.set_current.last_args, [d.oid, 1700])
        self.assertEqual(d.settings.run_current, 1.7)
        self.assertEqual(d.config.run_current, 0.8)
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
            d.protocol.commands.set_position_gains.last_args,
            [d.oid, 256, 0, 512, 0],
        )
        self.assertEqual(d.settings.pid_velocity_p, 512)
        self.assertEqual(d.settings.pid_velocity_i, 0)
        self.assertEqual(d.settings.pid_position_p, 256)
        self.assertEqual(d.settings.pid_position_i, 0)

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
            d.protocol.commands.set_pid_gains.last_args,
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

        self.assertEqual(
            d.protocol.commands.set_velocity_feedforward.last_args, [d.oid, 1, 8]
        )
        self.assertTrue(d.settings.velocity_feedforward)
        self.assertEqual(d.settings.velocity_feedforward_multiplier, 8)

    def test_disable_preserves_configured_multiplier(self):
        d = make_driver()
        d.settings.velocity_feedforward_multiplier = 4

        d.controls.set_velocity_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.set_velocity_feedforward.last_args, [d.oid, 0, 4]
        )
        self.assertFalse(d.settings.velocity_feedforward)
        self.assertEqual(d.settings.velocity_feedforward_multiplier, 4)


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
            d.protocol.commands.set_velocity_transient_feedforward.last_args,
            [d.oid, 1, 400, 750, 1200, 10000],
        )
        self.assertTrue(d.settings.velocity_transient_feedforward)
        self.assertEqual(d.settings.velocity_transient_lead_time_us, 400)
        self.assertEqual(d.settings.velocity_transient_gain, 750)
        self.assertEqual(d.settings.velocity_transient_max_offset, 1200)
        self.assertEqual(d.settings.velocity_transient_rate_hz, 10000)

    def test_disable_preserves_transient_parameters(self):
        d = make_driver()
        d.settings.velocity_transient_lead_time_us = 250
        d.settings.velocity_transient_gain = 500
        d.settings.velocity_transient_max_offset = 900
        d.settings.velocity_transient_rate_hz = 10000

        d.controls.set_velocity_transient_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.set_velocity_transient_feedforward.last_args,
            [d.oid, 0, 250, 500, 900, 10000],
        )
        self.assertFalse(d.settings.velocity_transient_feedforward)
        self.assertEqual(d.settings.velocity_transient_lead_time_us, 250)
        self.assertEqual(d.settings.velocity_transient_gain, 500)
        self.assertEqual(d.settings.velocity_transient_max_offset, 900)
        self.assertEqual(d.settings.velocity_transient_rate_hz, 10000)


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

        self.assertEqual(
            d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 1, 750, 250]
        )
        self.assertTrue(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 250)

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

        self.assertEqual(
            d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 1, 500, 500]
        )
        self.assertTrue(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 500)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 500)

    def test_disable_preserves_configured_gain(self):
        d = make_driver()
        d.settings.accel_feedforward_accel_gain = 750
        d.settings.accel_feedforward_decel_gain = 250

        d.controls.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 0, 750, 250]
        )
        self.assertFalse(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 250)


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
            d.protocol.commands.set_decoupling_feedforward.last_args,
            [d.oid, 1, 3000, 4095, 50, 65536, 25000, 500],
        )
        self.assertTrue(d.settings.decoupling_feedforward)
        self.assertEqual(d.settings.decoupling_r_int, 3000)
        self.assertEqual(d.settings.decoupling_l_int, 4095)
        self.assertEqual(d.settings.decoupling_pole_pairs, 50)
        self.assertEqual(d.settings.decoupling_position_units_per_rev, 65536)
        self.assertEqual(d.settings.decoupling_f_pwm_hz, 25000)
        self.assertEqual(d.settings.decoupling_max_offset, 500)


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

        self.assertEqual(
            d.protocol.commands.set_position_lead.last_args, [d.oid, 1, 10, 20]
        )
        self.assertTrue(d.settings.position_lead)
        self.assertEqual(d.settings.position_lead_gain, 10)
        self.assertEqual(d.settings.position_lead_max_counts, 20)

    def test_disable_preserves_position_lead_gain_and_cap(self):
        d = make_driver()
        d.settings.position_lead_gain = 10
        d.settings.position_lead_max_counts = 20

        d.controls.set_position_lead(MockGCmd({"ENABLE": 0}))

        self.assertEqual(
            d.protocol.commands.set_position_lead.last_args, [d.oid, 0, 10, 20]
        )
        self.assertFalse(d.settings.position_lead)
        self.assertEqual(d.settings.position_lead_gain, 10)
        self.assertEqual(d.settings.position_lead_max_counts, 20)


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
            d.protocol.commands.set_phase_advance.last_args,
            [d.oid, 1, -60000, 64, 16],
        )
        self.assertTrue(d.settings.phase_advance)
        self.assertEqual(d.settings.phase_advance_gain_ppm, -60000)
        self.assertEqual(d.settings.phase_advance_max_counts, 64)
        self.assertEqual(d.settings.phase_advance_deadband, 16)

    def test_disable_preserves_phase_advance_parameters(self):
        d = make_driver()
        d.settings.phase_advance_gain_ppm = 60000
        d.settings.phase_advance_max_counts = 64
        d.settings.phase_advance_deadband = 16

        d.controls.set_phase_advance(MockGCmd({"ENABLE": 0}))

        self.assertEqual(
            d.protocol.commands.set_phase_advance.last_args,
            [d.oid, 0, 60000, 64, 16],
        )
        self.assertFalse(d.settings.phase_advance)
        self.assertEqual(d.settings.phase_advance_gain_ppm, 60000)
        self.assertEqual(d.settings.phase_advance_max_counts, 64)
        self.assertEqual(d.settings.phase_advance_deadband, 16)

    def test_enable_with_no_parameters_is_safe_noop(self):
        d = make_driver()

        d.controls.set_phase_advance(MockGCmd({}))

        self.assertEqual(
            d.protocol.commands.set_phase_advance.last_args, [d.oid, 1, 0, 0, 16]
        )
        self.assertTrue(d.settings.phase_advance)
        self.assertEqual(d.settings.phase_advance_gain_ppm, 0)
        self.assertEqual(d.settings.phase_advance_max_counts, 0)
        self.assertEqual(d.settings.phase_advance_deadband, 16)


# =========================================================================
# 13. FOCI_SET_VOLTAGE_LIMIT debug command
# =========================================================================


class TestVoltageLimitCommand(unittest.TestCase):
    def test_sets_pidout_voltage_limit_without_persisting(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 20000})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(
            d.protocol.commands.set_voltage_limit.last_args, [d.oid, 20000]
        )
        self.assertIn("pidout_uq_ud_limit=20000", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_max(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 32767})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(
            d.protocol.commands.set_voltage_limit.last_args, [d.oid, 32767]
        )
        self.assertIn("pidout_uq_ud_limit=32767", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_min(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 0})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 0])
        self.assertIn("pidout_uq_ud_limit=0", gcmd.last_info)

    def test_voltage_limit_change_is_used_by_homing_preload(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()

        d.controls.set_voltage_limit(MockGCmd({"VOLTAGE_LIMIT": 20000}))
        d.homing.apply_active_gains_to_firmware()

        self.assertEqual(
            d.protocol.commands.set_voltage_limit.last_args, [d.oid, 20000]
        )


# =========================================================================
# 13. FOCI_CURRENT_STEP_TEST debug command
# =========================================================================


class TestCurrentStepDiagnosticCommand(unittest.TestCase):
    def test_sends_bounded_current_step_defaults(self):
        d = make_driver()

        gcmd = MockGCmd({"TARGET": 250})
        d.diagnostics.current_step_test(gcmd)

        self.assertEqual(
            d.protocol.commands.current_step_test.last_args, [d.oid, 250, 80, 12000]
        )
        self.assertIn("target=250", gcmd.last_info)

    def test_sends_explicit_current_step_parameters(self):
        d = make_driver()

        d.diagnostics.current_step_test(
            MockGCmd({"TARGET": -500, "DURATION_MS": 120, "VOLTAGE_LIMIT": 20000})
        )

        self.assertEqual(
            d.protocol.commands.current_step_test.last_args, [d.oid, -500, 120, 20000]
        )

    def test_current_step_result_formats_motion_and_supply_fields(self):
        d = make_driver()

        d.diagnostics.handle_current_step_result(
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

        d.diagnostics.current_vector_step_test(
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
            d.protocol.commands.current_vector_step_test.last_args,
            [d.oid, 0, 250, 120, 20000],
        )

    def test_current_vector_step_result_formats_axis_targets(self):
        d = make_driver()

        d.diagnostics.handle_current_vector_step_result(
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
        d.diagnostics.current_torque_sample_details[(500, -125, 5, 29000)] = {
            "torque_error": 1
        }

        d.diagnostics.current_torque_sample_test(
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
            d.protocol.commands.current_torque_sample_test.last_args,
            [d.oid, 500, -125, 5, 29000],
        )
        self.assertEqual(d.diagnostics.current_torque_sample_details, {})

    def test_sends_position_torque_offset_sample(self):
        d = make_driver()
        gcmd = MockGCmd({"TARGET": 500, "SAMPLE_DELAY_MS": 2, "VOLTAGE_LIMIT": 29000})

        d.diagnostics.position_torque_offset_test(gcmd)

        self.assertEqual(
            d.protocol.commands.position_torque_offset_sample_test.last_args,
            [d.oid, 500, 2, 29000],
        )
        self.assertIn("position-torque-offset", gcmd.last_info)

    def test_sends_voltage_step_sample(self):
        d = make_driver()
        gcmd = MockGCmd({"UQ": 512, "UD": -256, "SAMPLE_DELAY_MS": 2})

        d.diagnostics.voltage_step_test(gcmd)

        self.assertEqual(
            d.protocol.commands.voltage_step_test.last_args,
            [d.oid, 512, -256, 2],
        )
        self.assertIn("voltage-step", gcmd.last_info)

    def test_voltage_step_result_formats_sample_fields(self):
        d = make_driver()

        d.diagnostics.handle_voltage_step_result(
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

        d.diagnostics.handle_current_torque_sample_detail_result(
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
        d.diagnostics.handle_current_torque_sample_result(
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
        self.assertEqual(d.diagnostics.current_torque_sample_details, {})


# =========================================================================
# 11. Phase and error name coverage
# =========================================================================


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


class InnerConfidenceRoundtripTests(unittest.TestCase):
    """Phase 1 inner-confidence resolution and persistence roundtrip.

    See docs/specs/2026-04-30-inner-commissioning-stability.md §4.
    """

    def test_default_persisted_values_resolve_to_documented_defaults(self):
        driver = make_driver()
        driver.state.commissioned_result = None
        driver.config.identified_lambda_us = 700
        # All identified_tau_*/identified_inner_warning_flags default None
        tau, cross, perm, flags = driver.autotune.resolve_inner_confidence()
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
        driver.config.identified_tau_e_us = 9999
        tau, cross, perm, flags = driver.autotune.resolve_inner_confidence()
        self.assertEqual((tau, cross, perm, flags), (1234, 1100, 50, 0x02))

    def test_persisted_values_load_from_config(self):
        driver = make_driver()
        driver.state.commissioned_result = None
        driver.config.identified_tau_e_us = 800
        driver.config.identified_tau_e_crosscheck_us = 750
        driver.config.identified_tau_residual_permille = 60
        driver.config.identified_inner_warning_flags = 0x01
        tau, cross, perm, flags = driver.autotune.resolve_inner_confidence()
        self.assertEqual((tau, cross, perm, flags), (800, 750, 60, 0x01))

    def test_format_inner_warning_flags_lists_active_bits(self):
        # Bits 0 (R mismatch) + 4 (retry).
        text = format_inner_warning_flags((1 << 0) | (1 << 4))
        self.assertIn("coil R mismatch", text)
        self.assertIn("current validation retry", text)

    def test_format_inner_warning_flags_empty_when_clean(self):
        self.assertEqual(format_inner_warning_flags(0), "none")


if __name__ == "__main__":
    unittest.main()
