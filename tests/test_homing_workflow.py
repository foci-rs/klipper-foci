"""Tests for FOCI homing and calibration workflow behavior."""

import unittest

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockCoreXYKinematics,
    MockGCmd,
    MockNoneKinematics,
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    make_driver,
)


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
        # Calibration should not have been requested.
        self.assertIsNone(d.protocol.commands.calibrate.last_args)


class TestHomingStateTransitions(unittest.TestCase):
    def test_connect_delegates_initial_homing_state(self):
        d = make_driver()
        calls = []

        class FakeHoming:
            def apply_initial_state(self):
                calls.append("apply_initial_state")

            def __getattr__(self, name):
                raise AssertionError("unexpected homing method %s" % name)

        d.homing = FakeHoming()
        d._handle_connect()

        self.assertEqual(calls, ["apply_initial_state"])

    def test_initial_homing_state_applies_active_gains_when_enabled(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        calls = []

        d.homing.apply_active_gains_to_firmware = lambda: calls.append("apply")
        d.homing.set_auto_calibrate_on_enable_allowed = lambda allowed: calls.append(
            ("auto", allowed)
        )
        d.homing.install_enable_hooks = lambda: calls.append("hooks")

        d.homing.apply_initial_state()

        self.assertEqual(calls, ["apply", ("auto", True), "hooks"])

    def test_initial_homing_state_keeps_auto_calibrate_closed_when_inhibited(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.inhibited = True
        calls = []

        d.homing.apply_active_gains_to_firmware = lambda: calls.append("apply")
        d.homing.set_auto_calibrate_on_enable_allowed = lambda allowed: calls.append(
            ("auto", allowed)
        )
        d.homing.install_enable_hooks = lambda: calls.append("hooks")

        d.homing.apply_initial_state()

        self.assertEqual(calls, [("auto", False), "hooks"])

    def test_connect_allows_auto_calibrate_only_with_valid_config(self):
        d = make_driver()
        d._handle_connect()
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0]
        )

        d = make_driver()
        d.config.autotune_status = "commissioned"
        d.config.pid_flux_p = 100
        d.config.pid_flux_i = 200
        d.config.pid_torque_p = 300
        d.config.pid_torque_i = 400
        d.config.identified_lambda_us = 1200
        d.config.identified_theta_e_us = 100
        d.config.identified_ringing_count = 0
        d.config.identified_bandwidth_hz = 500
        d.config.commissioned_velocity_p = 1100
        d.config.commissioned_velocity_i = 0
        d.config.commissioned_position_p = 700
        d.config.commissioned_position_i = 0
        d.config.commissioned_velocity_limit = 50_000
        d._handle_connect()
        self.assertEqual(
            d.protocol.commands.set_pid_gains.last_args, [d.oid, 100, 200, 300, 400]
        )
        self.assertEqual(
            d.protocol.commands.set_position_gains.last_args,
            [d.oid, 700, 0, 1100, 0],
        )
        self.assertEqual(
            d.protocol.commands.set_velocity_limit.last_args, [d.oid, 50_000]
        )
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 1]
        )

    def test_connect_keeps_auto_calibrate_closed_while_inhibited(self):
        d = make_driver()
        d.state.inhibited = True
        d.config.autotune_status = "commissioned"
        d.config.pid_flux_p = 100
        d.config.pid_flux_i = 200
        d.config.pid_torque_p = 300
        d.config.pid_torque_i = 400
        d.config.identified_lambda_us = 1200
        d.config.identified_theta_e_us = 100
        d.config.identified_ringing_count = 0
        d.config.identified_bandwidth_hz = 500
        d.config.commissioned_velocity_p = 1100
        d.config.commissioned_velocity_i = 0
        d.config.commissioned_position_p = 700
        d.config.commissioned_position_i = 0
        d.config.commissioned_velocity_limit = 50_000
        d._handle_connect()
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0]
        )

    def test_inhibited_blocks_ensure_calibrated(self):
        d = make_driver()
        d.state.inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_active_gain_apply_resends_configured_voltage_limit(self):
        d = make_driver()
        d.settings.voltage_limit = 29000
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()

        d.homing.apply_active_gains_to_firmware()

        self.assertEqual(
            d.protocol.commands.set_voltage_limit.last_args, [d.oid, 29000]
        )

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
        self.assertEqual(d.protocol.commands.calibrate.last_args, [0])
        self.assertTrue(d.state.is_calibrated)

    def test_calibration_failure_labels_legacy_commission_error_code(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.printer.get_reactor().completion_result = {"status": 3}

        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()

        msg = str(ctx.exception)
        self.assertIn("commissioning status 3", msg)
        self.assertIn("SPI communication error", msg)
        self.assertNotIn("UNKNOWN(3)", msg)

    def test_ensure_calibrated_skips_if_already_true(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.homing.ensure_calibrated()
        self.assertIsNone(d.protocol.commands.calibrate.last_args)


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
        d.commissioning.done = True
        d.commissioning.result = SAMPLE_COMMISSION_RESULT
        try:
            d.commissioning.commission(gcmd)
        except (CommandError, AttributeError, TypeError):
            pass
        # Homing should have been invalidated
        self.assertIsNotNone(kin._cleared_axes)

    def test_autotune_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        try:
            d.autotune.autotune(gcmd)
        except (CommandError, AttributeError, TypeError):
            pass
        self.assertIsNotNone(kin._cleared_axes)

    def test_selftest_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        try:
            d.selftest.selftest(MockGCmd())
        except (CommandError, AttributeError, TypeError):
            pass
        self.assertIsNotNone(kin._cleared_axes)
