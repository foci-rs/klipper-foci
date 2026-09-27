"""Tests for FOCI rare fine-tuning workflow behavior."""

import unittest

from mocks import SAMPLE_ACTIVE_GAINS, MockGCmd, make_driver

from klipper_foci_tuning.workflow import TuningWorkflow


class TestVelocityTransientFeedforwardCommand(unittest.TestCase):
    def test_sets_transient_feedforward_parameters(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        tuning.set_velocity_transient_feedforward(
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
        tuning = TuningWorkflow(d)
        d.settings.velocity_transient_lead_time_us = 250
        d.settings.velocity_transient_gain = 500
        d.settings.velocity_transient_max_offset = 900
        d.settings.velocity_transient_rate_hz = 10000

        tuning.set_velocity_transient_feedforward(
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


class TestAccelFeedforwardCommand(unittest.TestCase):
    def test_sets_accel_feedforward_enable_and_split_gains(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        tuning.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "ACCEL_GAIN": 750,
                    "DECEL_GAIN": 250,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 1, 750, 250])
        self.assertTrue(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 250)

    def test_gain_alias_sets_both_split_gains(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        tuning.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN": 500,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 1, 500, 500])
        self.assertTrue(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 500)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 500)

    def test_disable_preserves_configured_gain(self):
        d = make_driver()
        tuning = TuningWorkflow(d)
        d.settings.accel_feedforward_accel_gain = 750
        d.settings.accel_feedforward_decel_gain = 250

        tuning.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 0, 750, 250])
        self.assertFalse(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 250)


class TestDecouplingFeedforwardCommand(unittest.TestCase):
    def test_sets_decoupling_feedforward_enable_and_model(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        tuning.set_decoupling_feedforward(
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


class TestPositionLeadCommand(unittest.TestCase):
    def test_sets_position_lead_enable_gain_and_cap(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        tuning.set_position_lead(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN": 10,
                    "MAX_COUNTS": 20,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_position_lead.last_args, [d.oid, 1, 10, 20])
        self.assertTrue(d.settings.position_lead)
        self.assertEqual(d.settings.position_lead_gain, 10)
        self.assertEqual(d.settings.position_lead_max_counts, 20)

    def test_disable_preserves_position_lead_gain_and_cap(self):
        d = make_driver()
        tuning = TuningWorkflow(d)
        d.settings.position_lead_gain = 10
        d.settings.position_lead_max_counts = 20

        tuning.set_position_lead(MockGCmd({"ENABLE": 0}))

        self.assertEqual(d.protocol.commands.set_position_lead.last_args, [d.oid, 0, 10, 20])
        self.assertFalse(d.settings.position_lead)
        self.assertEqual(d.settings.position_lead_gain, 10)
        self.assertEqual(d.settings.position_lead_max_counts, 20)


class TestPhaseAdvanceCommand(unittest.TestCase):
    def test_sets_phase_advance_enable_gain_cap_and_deadband(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        tuning.set_phase_advance(
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
        tuning = TuningWorkflow(d)
        d.settings.phase_advance_gain_ppm = 60000
        d.settings.phase_advance_max_counts = 64
        d.settings.phase_advance_deadband = 16

        tuning.set_phase_advance(MockGCmd({"ENABLE": 0}))

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
        tuning = TuningWorkflow(d)

        tuning.set_phase_advance(MockGCmd({}))

        self.assertEqual(d.protocol.commands.set_phase_advance.last_args, [d.oid, 1, 0, 0, 16])
        self.assertTrue(d.settings.phase_advance)
        self.assertEqual(d.settings.phase_advance_gain_ppm, 0)
        self.assertEqual(d.settings.phase_advance_max_counts, 0)
        self.assertEqual(d.settings.phase_advance_deadband, 16)


class TestVoltageLimitCommand(unittest.TestCase):
    def test_sets_pidout_voltage_limit_without_persisting(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 20000})
        tuning.set_voltage_limit(gcmd)

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 20000])
        self.assertIn("pidout_uq_ud_limit=20000", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_max(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 32767})
        tuning.set_voltage_limit(gcmd)

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 32767])
        self.assertIn("pidout_uq_ud_limit=32767", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_min(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 0})
        tuning.set_voltage_limit(gcmd)

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 0])
        self.assertIn("pidout_uq_ud_limit=0", gcmd.last_info)

    def test_voltage_limit_change_is_used_by_homing_preload(self):
        d = make_driver()
        tuning = TuningWorkflow(d)
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()

        tuning.set_voltage_limit(MockGCmd({"VOLTAGE_LIMIT": 20000}))
        d.homing.apply_active_gains_to_firmware()

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 20000])
