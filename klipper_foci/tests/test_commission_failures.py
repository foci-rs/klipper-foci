"""Tests for commissioning failure paths and cleanup."""

import unittest

import pytest

from klipper_foci._vocabulary_generated import HARD_FAULT_CODES
from klipper_foci.commissioning import (
    COMMISSION_REASON_NAMES,
    PHASE_NAMES,
)
from klipper_foci.homing import CALIBRATION_REASON_NAMES
from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    CommandError,
    MockGCmd,
    MockReactor,
    complete_commission_result,
    make_driver,
    timing_reply,
)


def seed_reply_caches(driver):
    driver.diagnostics.active.resistance_cache[driver.oid] = {"run": {"stale": 1}}
    driver.diagnostics.active.inductance_cache[driver.oid] = {"run": {"stale": 1}}
    driver.diagnostics.active.current_loop_cache[driver.oid] = {"stale": 1}


def assert_commission_cleaned_up(driver):
    assert driver.oid not in driver.diagnostics.active.resistance_cache
    assert driver.oid not in driver.diagnostics.active.inductance_cache
    assert driver.oid not in driver.diagnostics.active.current_loop_cache
    assert driver.commissioning.timing_by_method == {}
    assert not driver.state.operation_lock


def test_commission_timeout_clears_reply_caches():
    d = make_driver()
    d.printer._objects["reactor"] = MockReactor()

    def never_finish(_args):
        seed_reply_caches(d)
        d.commissioning.timing_by_method = {0: {"status": 1}}

    d.protocol.commands.commission.send = never_finish
    with pytest.raises(CommandError, match="timed out"):
        d.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert_commission_cleaned_up(d)
    assert d.state.inhibited


def test_commission_mid_phase_error_clears_reply_caches():
    d = make_driver()

    def drive_failure(_args):
        seed_reply_caches(d)
        d.commissioning.timing_by_method = {0: {"status": 1}}
        d.commissioning.error_code = 19
        d.commissioning.last_phase_id = 5

    d.protocol.commands.commission.send = drive_failure
    with pytest.raises(CommandError, match="FOCI_SETUP failed at"):
        d.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert_commission_cleaned_up(d)
    assert d.state.inhibited


def test_commission_chip_reset_clears_reply_caches():
    d = make_driver()

    def drive_chip_reset(_args):
        seed_reply_caches(d)
        d.commissioning.timing_by_method = {0: {"status": 1}}
        d.commissioning.error_code = 18
        d.commissioning.last_phase_id = 10

    d.protocol.commands.commission.send = drive_chip_reset
    with pytest.raises(CommandError, match="CHIP_RESET_DETECTED"):
        d.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert_commission_cleaned_up(d)
    assert not d.state.inhibited


def test_commission_terminal_status_failure_clears_reply_caches():
    d = make_driver()
    result = complete_commission_result()
    result["status"] = 7

    def drive_terminal_failure(_args):
        seed_reply_caches(d)
        d.commissioning.result = result
        d.commissioning.done = True

    d.protocol.commands.commission.send = drive_terminal_failure
    with pytest.raises(CommandError, match="encoder fault"):
        d.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert_commission_cleaned_up(d)
    assert d.state.inhibited
    assert d.state.active_gains is None


def test_commission_terminal_chip_reset_status_does_not_inhibit_retry():
    d = make_driver()
    result = complete_commission_result()
    result["status"] = 18

    def drive_terminal_chip_reset(_args):
        seed_reply_caches(d)
        d.commissioning.result = result
        d.commissioning.done = True

    d.protocol.commands.commission.send = drive_terminal_chip_reset
    with pytest.raises(CommandError, match="CHIP_RESET_DETECTED"):
        d.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert_commission_cleaned_up(d)
    assert not d.state.inhibited
    assert not d.state.is_calibrated


def test_commission_timing_evidence_rejected_disables_motor():
    d = make_driver()
    result = complete_commission_result()
    result["timing_summary"] = 2 << 4 | 1 << 6
    enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)

    def drive_rejected_timing(_args):
        seed_reply_caches(d)
        d.commissioning.handle_commission_timing(
            timing_reply(method=2, status=2, requested_period_us=160)
        )
        d.commissioning.result = result
        d.commissioning.done = True

    d.protocol.commands.commission.send = drive_rejected_timing
    with pytest.raises(CommandError, match="timing evidence rejected"):
        d.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert_commission_cleaned_up(d)
    assert not enable_line.is_motor_enabled()
    assert enable_line.real_disable_count == 1
    assert d.state.inhibited
    assert d.state.active_gains is None


class TestChipResetDetected(unittest.TestCase):
    """Verify host recovery when firmware reports CHIP_RESET_DETECTED."""

    def test_calibration_error_names_includes_code_2(self):
        self.assertIn(2, CALIBRATION_REASON_NAMES)
        self.assertIn("CHIP_RESET_DETECTED", CALIBRATION_REASON_NAMES[2])

    def test_calibration_error_names_includes_encoder_fault(self):
        self.assertIn(8, CALIBRATION_REASON_NAMES)
        self.assertIn("ENCODER_FAULT", CALIBRATION_REASON_NAMES[8])

    def test_commission_error_names_includes_code_18(self):
        self.assertIn(18, COMMISSION_REASON_NAMES)
        self.assertIn("CHIP_RESET_DETECTED", COMMISSION_REASON_NAMES[18])

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
            d.commissioning.last_phase_id = 10

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
        self.assertIn(19, COMMISSION_REASON_NAMES)
        self.assertNotEqual(COMMISSION_REASON_NAMES[19], "UNKNOWN(19)")

    def test_commission_error_names_includes_resistance_envelope_code(self):
        self.assertIn(31, COMMISSION_REASON_NAMES)
        self.assertNotEqual(COMMISSION_REASON_NAMES[31], "UNKNOWN(31)")

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
        self.assertIn(COMMISSION_REASON_NAMES[19], message)
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
        self.assertIn(COMMISSION_REASON_NAMES[73], message)
        self.assertIn("docs/troubleshooting/resistance-identification.md", message)
        self.assertTrue(d.state.inhibited)


class TestCommissioningStateTransitions(unittest.TestCase):
    def test_commission_failure_sets_inhibited(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "commissioned"
        d.state.is_calibrated = True
        d.commissioning.on_commission_failure()
        self.assertTrue(d.state.inhibited)
        self.assertIsNone(d.state.active_gains)
        self.assertEqual(d.state.runtime_status, "uncommissioned")
        self.assertFalse(d.state.is_calibrated)
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0])


class TestNameMaps(unittest.TestCase):
    def test_all_phase_ids_have_names(self):
        """Every live `CommissionPhase` wire code has a name and the codes have no gaps.

        Codes 1-11 are the whole vocabulary; code 0 is the host's miss sentinel and
        must not appear.
        """
        self.assertEqual(sorted(PHASE_NAMES), list(range(1, 12)))
        self.assertEqual(PHASE_NAMES[9], "Encoder alignment")
        self.assertEqual(PHASE_NAMES[10], "Closed-loop entry")
        self.assertEqual(PHASE_NAMES[11], "Gain floor measurement")

    def test_hard_fault_codes_are_subset_of_error_names(self):
        for code in HARD_FAULT_CODES:
            self.assertIn(
                code,
                COMMISSION_REASON_NAMES,
                f"Hard fault code {code} missing from COMMISSION_REASON_NAMES",
            )
