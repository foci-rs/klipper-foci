"""Tests for FOCI rare fine-tuning workflow behavior."""

import unittest

from mocks import MockGCmd, make_driver

from klipper_foci_tuning.workflow import TuningWorkflow


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
