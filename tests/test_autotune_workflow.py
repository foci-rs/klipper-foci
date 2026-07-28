"""Tests for FOCI autotune workflow behavior."""

import unittest

from klipper_foci.commissioning import format_inner_warning_flags
from klipper_foci.registers import REGISTERS
from klipper_foci.velocity_integral import VelocityIntegralAssembler

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    MockNoneKinematics,
    MockPrintStats,
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    make_driver,
)


class MockConfigFile:
    def __init__(self):
        self.values = {}

    def set(self, section, key, value):
        self.values[(section, key)] = value


def install_live_dump(driver, dump_values=None):
    values = {
        REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
        REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 416,
    }
    if dump_values is not None:
        values.update(dump_values)

    def dump_registers():
        for addr, value in values.items():
            driver.dump.handle_dump_value({"addr": addr, "value": value})
        driver.dump.handle_dump_done({})

    driver.protocol.dump_registers = dump_registers


def feed_no_transition_terminal(workflow, run_sequence):
    common = {
        "run_sequence": run_sequence,
        "evidence_sequence": 0,
    }
    workflow.handle_velocity_integral_terminal_core(
        {
            **common,
            "fragment": 0,
            "outcome": 5,
            "cause": 11,
            "recovery_flags": 0b1000,
            "rest_boundary_rung_plus_one": 0,
            "rest_boundary_slot_plus_one": 0,
            "expected_observations": 0,
            "emitted_observations": 0,
            "expected_rungs": 0,
            "emitted_rungs": 0,
        }
    )
    workflow.handle_velocity_integral_terminal_identity(
        {
            **common,
            "fragment": 1,
            "plan_digest_low": 0x89AB_CDEF,
            "plan_digest_high": 0x0123_4567,
            "digest_low": 0,
            "digest_high": 0,
        }
    )
    workflow.handle_velocity_integral_terminal_timing(
        {
            **common,
            "fragment": 2,
            "started_low": 0,
            "started_high": 0,
            "completed_low": 0,
            "completed_high": 0,
        }
    )


class TestAutotuneGates(unittest.TestCase):
    def _commissioned_driver(self, kinematics=None, homed_axes="xyz"):
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kinematics
            or MockCartesianKinematics([["stepper_x"], ["stepper_y"]]),
            homed_axes=homed_axes,
        )
        d.state.is_calibrated = True
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "commissioned"
        d.state.commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        d.state.commissioned_result.update(
            {
                "tau_e_us": 730,
                "inner_warning_flags": 0,
                "bandwidth_hz": 1600,
                "current_gains_source": 1,
                "current_gains_tier": 1,
                "current_retry_budget_exhausted": 0,
                "current_failure_reason": 0,
                "inductance_source": 1,
                "inductance_reactance_count_ratio_milli": 8600,
                "inductance_saliency_status": 1,
                "resistance_selected_count_slope_milli": 1042,
            }
        )
        install_live_dump(d)
        return d

    def test_raises_if_lock_held(self):
        d = self._commissioned_driver()
        d.state.operation_lock = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_terminal_disarm_synchronizes_host_enable_state(self):
        d = self._commissioned_driver()
        toolhead = d.printer.lookup_object("toolhead")
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(
            d.stepper_name
        )
        enable_line.motor_enable(toolhead.get_last_move_time())

        d.autotune._synchronize_disarmed_workflow_terminal(toolhead)

        self.assertFalse(d.state.is_calibrated)
        self.assertFalse(enable_line.is_motor_enabled())

    def test_stage_b_candidate_retains_and_reissues_exact_request_fields(self):
        d = self._commissioned_driver()
        request = {"profile_code": 1, "requested_velocity_mrev_s": 2929}
        d.autotune.velocity_sweep.outcome = "complete_candidate"
        d.autotune.velocity_sweep.terminal = {"cause": 0}

        d.autotune._retain_stage_b_request_from_terminal(request)
        reissued = d.autotune._request_for_stage_b_dispatch(dict(request))

        self.assertEqual(reissued, request)
        self.assertIsNot(reissued, request)

    def test_stage_b_changed_request_is_not_normalized_to_retained_plan(self):
        d = self._commissioned_driver()
        retained = {"profile_code": 1, "requested_velocity_mrev_s": 2929}
        changed = {"profile_code": 1, "requested_velocity_mrev_s": 3000}
        d.autotune._stage_b_candidate_request = dict(retained)

        dispatched = d.autotune._request_for_stage_b_dispatch(changed)

        self.assertEqual(dispatched, changed)

    def test_stage_b_plan_mismatch_preserves_original_reissue_fields(self):
        d = self._commissioned_driver()
        retained = {"profile_code": 1, "requested_velocity_mrev_s": 2929}
        d.autotune._stage_b_candidate_request = dict(retained)
        d.autotune.velocity_sweep.outcome = "rejected_plan_mismatch"
        d.autotune.velocity_sweep.terminal = {"cause": 6}

        d.autotune._retain_stage_b_request_from_terminal(
            {"profile_code": 1, "requested_velocity_mrev_s": 3000}
        )

        self.assertEqual(d.autotune._stage_b_candidate_request, retained)

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
        self.assertIn("not homed for X/Y", str(ctx.exception))

    def test_refuses_none_kinematics_for_production_autotune(self):
        d = self._commissioned_driver(kinematics=MockNoneKinematics(), homed_axes="")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("unsupported kinematics", str(ctx.exception))

    def test_refuses_autotune_when_printer_is_not_idle(self):
        d = self._commissioned_driver()
        d.printer._objects["print_stats"] = MockPrintStats("printing")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("printer is not idle", str(ctx.exception))
        self.assertEqual(d.printer.lookup_object("gcode")._scripts, [])
        self.assertIsNone(d.protocol.commands.tune.last_args)

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

    def test_missing_velocity_sweep_plan_uses_short_setup_timeout(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("timed out waiting for plan", str(ctx.exception))

    def test_firmware_workflow_replaces_short_timeout_with_reported_maximum(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_with_plan(deadline):
            reactor._time = deadline
            if d.autotune.velocity_integral.workflow_plan is None:
                params = {
                    "run_sequence": 7,
                    "shape": 0,
                    "nominal_workflow_ms": 8_000,
                    "maximum_workflow_ms": 10_000,
                }
                low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
                d.autotune.handle_commissioning_workflow_plan(
                    {**params, "digest_low": low, "digest_high": high}
                )
            if reactor._time >= 6.0:
                d.autotune.handle_tune_result({"status": 2})
            return reactor._time

        reactor.pause = pause_with_plan

        d.autotune.autotune(gcmd)

        self.assertGreaterEqual(reactor._time, 6.0)

    def test_composite_workflow_waits_for_integral_terminal(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        pauses = 0

        d.autotune._format_velocity_sweep_result = lambda: "proportional response"
        d.autotune._format_velocity_integral_result = lambda: "integral response"

        def pause_with_composite_results(deadline):
            nonlocal pauses
            pauses += 1
            reactor._time = deadline
            if d.autotune.velocity_integral.workflow_plan is None:
                params = {
                    "run_sequence": 9,
                    "shape": 1,
                    "nominal_workflow_ms": 250_000,
                    "maximum_workflow_ms": 300_000,
                }
                low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
                d.autotune.handle_commissioning_workflow_plan(
                    {**params, "digest_low": low, "digest_high": high}
                )
                d.autotune.velocity_sweep.outcome = "complete"
                d.autotune.velocity_sweep.terminal = {"cause": 0}
                d.autotune.velocity_sweep.done = True
            elif pauses == 2:
                d.autotune.velocity_integral.outcome = "complete_candidate"
                d.autotune.velocity_integral.terminal = {"cause": 0}
                d.autotune.velocity_integral.done = True
            return reactor._time

        reactor.pause = pause_with_composite_results

        d.autotune.autotune(gcmd)

        self.assertGreaterEqual(pauses, 2)
        self.assertTrue(
            any("proportional response" in message for message in gcmd._responses)
        )
        self.assertTrue(
            any("integral response" in message for message in gcmd._responses)
        )

    def test_no_transition_direct_resume_finishes_without_plan_timeout(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(
            d.stepper_name
        )
        enable_line.motor_enable(0.0)
        pauses = 0

        def pause_with_failed_resume(deadline):
            nonlocal pauses
            pauses += 1
            reactor._time = deadline
            params = {
                "run_sequence": 17,
                "shape": 2,
                "nominal_workflow_ms": 182_512,
                "maximum_workflow_ms": 182_512,
            }
            low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
            d.autotune.handle_commissioning_workflow_plan(
                {**params, "digest_low": low, "digest_high": high}
            )
            feed_no_transition_terminal(d.autotune, 17)
            return reactor._time

        reactor.pause = pause_with_failed_resume

        d.autotune.autotune(gcmd)

        self.assertEqual(pauses, 1)
        self.assertIsNone(d.autotune.velocity_integral.plan)
        self.assertEqual(d.autotune.velocity_integral.outcome, "failed")
        self.assertTrue(
            any("response failed" in message for message in gcmd._responses)
        )
        self.assertFalse(d.state.is_calibrated)
        self.assertFalse(enable_line.is_motor_enabled())

    def test_no_transition_continuation_relays_both_ordered_terminals(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        d.autotune._format_velocity_sweep_result = lambda: "proportional complete"

        def pause_with_failed_continuation(deadline):
            reactor._time = deadline
            params = {
                "run_sequence": 18,
                "shape": 1,
                "nominal_workflow_ms": 400_000,
                "maximum_workflow_ms": 400_000,
            }
            low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
            d.autotune.handle_commissioning_workflow_plan(
                {**params, "digest_low": low, "digest_high": high}
            )
            d.autotune.velocity_sweep.outcome = "complete"
            d.autotune.velocity_sweep.terminal = {"cause": 0}
            d.autotune.velocity_sweep.done = True
            feed_no_transition_terminal(d.autotune, 18)
            return reactor._time

        reactor.pause = pause_with_failed_continuation

        d.autotune.autotune(gcmd)

        self.assertIsNone(d.autotune.velocity_integral.plan)
        self.assertEqual(d.autotune.velocity_integral.outcome, "failed")
        self.assertTrue(
            any("proportional complete" in message for message in gcmd._responses)
        )
        self.assertTrue(
            any("response failed" in message for message in gcmd._responses)
        )

    def test_composite_workflow_finishes_when_recovery_suppresses_continuation(self):
        d = self._commissioned_driver()
        d.autotune.velocity_integral.workflow_plan = {"shape": 1}
        d.autotune.velocity_sweep.outcome = "complete"
        d.autotune.velocity_sweep.terminal = {
            "cause": 0,
            "recovery_unavailable": 1,
        }
        d.autotune.velocity_sweep.done = True

        self.assertTrue(d.autotune._workflow_finished())
        self.assertFalse(d.autotune.velocity_integral.done)

    def test_suppressed_composite_continuation_returns_stage_b_result(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        d.autotune._format_velocity_sweep_result = lambda: "proportional response"

        def pause_with_suppressed_continuation(deadline):
            reactor._time = deadline
            params = {
                "run_sequence": 10,
                "shape": 1,
                "nominal_workflow_ms": 300_000,
                "maximum_workflow_ms": 390_000,
            }
            low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
            d.autotune.handle_commissioning_workflow_plan(
                {**params, "digest_low": low, "digest_high": high}
            )
            d.autotune.velocity_sweep.outcome = "complete"
            d.autotune.velocity_sweep.terminal = {
                "cause": 0,
                "recovery_unavailable": 1,
            }
            d.autotune.velocity_sweep.done = True
            return reactor._time

        reactor.pause = pause_with_suppressed_continuation

        d.autotune.autotune(gcmd)

        self.assertTrue(
            any("proportional response" in message for message in gcmd._responses)
        )
        self.assertFalse(d.autotune.velocity_integral.done)

    def test_composite_rejects_integral_plan_before_proportional_handoff(self):
        d = self._commissioned_driver()
        params = {
            "run_sequence": 13,
            "shape": 1,
            "nominal_workflow_ms": 250_000,
            "maximum_workflow_ms": 300_000,
        }
        low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
        d.autotune.handle_commissioning_workflow_plan(
            {**params, "digest_low": low, "digest_high": high}
        )

        d.autotune.handle_velocity_integral_plan_core(
            {
                "run_sequence": 13,
                "evidence_sequence": 0,
                "fragment": 0,
                "plan_digest_low": 1,
                "plan_digest_high": 0,
                "stage_b_digest_low": 2,
                "stage_b_digest_high": 0,
                "build_revision": 1,
                "schema_revision": 2,
                "channel": 0,
                "final_p": 1448,
            }
        )

        self.assertIn(
            "before proportional handoff",
            str(d.autotune.velocity_integral_error),
        )

    def test_combined_workflow_rejects_integral_plan_before_selected_response(self):
        d = self._commissioned_driver()
        params = {
            "run_sequence": 14,
            "shape": 3,
            "nominal_workflow_ms": 449_173,
            "maximum_workflow_ms": 494_128,
        }
        low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
        d.autotune.handle_commissioning_workflow_plan(
            {**params, "digest_low": low, "digest_high": high}
        )

        d.autotune.handle_velocity_integral_plan_core(
            {
                "run_sequence": 14,
                "evidence_sequence": 0,
                "fragment": 0,
                "plan_digest_low": 1,
                "plan_digest_high": 0,
                "stage_b_digest_low": 2,
                "stage_b_digest_high": 0,
                "build_revision": 1,
                "schema_revision": 8,
                "channel": 0,
                "final_p": 1024,
            }
        )

        self.assertIn(
            "before proportional handoff",
            str(d.autotune.velocity_integral_error),
        )

    def test_combined_stage_c_binds_the_selected_recovery_stage_b_plan(self):
        d = self._commissioned_driver()
        params = {
            "run_sequence": 14,
            "shape": 3,
            "nominal_workflow_ms": 452_073,
            "maximum_workflow_ms": 496_528,
        }
        low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
        d.autotune.handle_commissioning_workflow_plan(
            {**params, "digest_low": low, "digest_high": high}
        )
        d.autotune.velocity_sweep._combined_stage_b_schema = 11
        d.autotune.velocity_sweep.done = True
        d.autotune.velocity_sweep.outcome = "complete"

        d.autotune.handle_velocity_integral_plan_core(
            {
                "run_sequence": 14,
                "evidence_sequence": 0,
                "fragment": 0,
                "plan_digest_low": 1,
                "plan_digest_high": 0,
                "stage_b_digest_low": 2,
                "stage_b_digest_high": 0,
                "build_revision": 1,
                "schema_revision": 10,
                "channel": 0,
                "final_p": 1024,
            }
        )

        self.assertEqual(d.autotune.velocity_integral.combined_stage_b_schema, 11)

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

    def test_safety_fault_reports_outer_envelope_detail(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_safety_fault(deadline):
            reactor._time = deadline
            d.autotune.handle_outer_safety_fault(
                {
                    "reason": 4,
                    "max_travel_mrev": 750,
                    "max_velocity_mrev_s": 6000,
                    "max_duration_ms": 3000,
                    "direction_mask": 3,
                    "delta_counts": -125,
                    "dt_us": 4000,
                    "velocity_counts_per_ms": -31,
                    "velocity_cap_counts_per_ms": 24,
                    "position_counts": -373,
                    "position_window_counts": 3000,
                    "elapsed_us": 120000,
                    "duration_cap_us": 3000000,
                }
            )
            d.autotune.handle_tune_result({"status": 17})
            return reactor._time

        reactor.pause = pause_and_report_safety_fault

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        message = str(ctx.exception)
        self.assertIn("safety fault: safety envelope violation", message)
        self.assertIn("outer safety velocity", message)
        self.assertIn("delta_counts=-125", message)
        self.assertIn("dt_us=4000", message)
        self.assertIn("velocity_counts_per_ms=-31", message)
        self.assertIn("cap_counts_per_ms=24", message)
        self.assertIn("position_counts=-373/3000", message)
        self.assertIn("elapsed_us=120000/3000000", message)
        self.assertIn("budget=750mrev/6000mrev_s/3000ms dir=0x03", message)

    def test_velocity_sweep_fault_reports_outer_envelope_detail(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_sweep_fault(deadline):
            reactor._time = deadline
            params = {
                "run_sequence": 11,
                "shape": 0,
                "nominal_workflow_ms": 45_000,
                "maximum_workflow_ms": 49_728,
            }
            low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
            d.autotune.handle_commissioning_workflow_plan(
                {**params, "digest_low": low, "digest_high": high}
            )
            d.autotune.handle_outer_safety_fault(
                {
                    "reason": 7,
                    "dt_us": 2_137,
                    "max_travel_mrev": 750,
                    "max_velocity_mrev_s": 6000,
                    "max_duration_ms": 3000,
                    "direction_mask": 3,
                }
            )
            d.autotune.velocity_sweep.plan = {"maximum_workflow_ms": 49_728}
            d.autotune.velocity_sweep.integrity = {"cause": 17}
            d.autotune.velocity_sweep.outcome = "fault"
            d.autotune.velocity_sweep.done = True
            return reactor._time

        reactor.pause = pause_and_report_sweep_fault

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        message = str(ctx.exception)
        self.assertIn("velocity sweep fault (cause=17)", message)
        self.assertIn("outer safety observation_gap", message)
        self.assertIn("dt_us=2137", message)


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


class InnerWarningFlagFormattingTests(unittest.TestCase):
    """Phase 1 inner-warning flag formatting."""

    def test_format_inner_warning_flags_lists_active_bits(self):
        text = format_inner_warning_flags((1 << 0) | (1 << 5))
        self.assertIn("coil R mismatch", text)
        self.assertIn("current gains fell back to defaults", text)

    def test_format_inner_warning_flags_empty_when_clean(self):
        self.assertEqual(format_inner_warning_flags(0), "none")

    def test_format_inner_warning_flags_ignores_tau_residual_telemetry(self):
        self.assertEqual(format_inner_warning_flags(1 << 2), "none")

    def test_format_inner_warning_flags_ignores_deprecated_bit4(self):
        self.assertEqual(format_inner_warning_flags(1 << 4), "none")


class TestAutotuneReadinessAdmission(unittest.TestCase):
    def _ready_driver(self):
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=MockCartesianKinematics([["stepper_x"], ["stepper_y"]]),
            homed_axes="xyz",
        )
        d.state.is_calibrated = True
        d.state.runtime_status = "commissioned"
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.config.identified_lambda_us = 700
        d.config.identified_tau_e_us = 730
        d.config.identified_theta_e_us = 160
        d.config.identified_ringing_count = 7
        d.config.identified_bandwidth_hz = 1600
        d.config.identified_inner_warning_flags = 0
        d.config.identified_current_gains_source = 1
        d.config.identified_current_gains_tier = 1
        d.config.identified_current_retry_budget_exhausted = 0
        d.config.identified_current_failure_reason = 0
        d.config.identified_l_source = 1
        d.config.identified_l_reactance_count_ratio_milli = 8600
        d.config.identified_l_saliency_status = 1
        d.config.identified_r_count_slope_milli = 1042
        install_live_dump(d)
        return d

    def _finish_tune_on_next_pause(self, driver, result_fields=None):
        reactor = driver.printer.get_reactor()
        result = {
            "status": 0,
            "warning_code": 0,
            "velocity_p": 1152,
            "velocity_i": 0,
            "position_p": 640,
            "position_i": 0,
            "velocity_limit": 500000,
            "velocity_filter_hz": 0,
            "torque_filter_hz": 0,
            "position_filter_hz": 0,
            "flux_filter_hz": 0,
            "j_eff": 42,
            "b_eff": 11,
        }
        result.update(result_fields or {})

        def finish_tune(deadline):
            reactor._time = deadline
            driver.autotune.handle_tune_result(result)
            return reactor._time

        reactor.pause = finish_tune

    def _install_live_dump(self, driver, dump_values):
        calls = []

        def dump_registers():
            calls.append("dump_registers")
            for addr, value in dump_values.items():
                driver.dump.handle_dump_value({"addr": addr, "value": value})
            driver.dump.handle_dump_done({})

        driver.protocol.dump_registers = dump_registers
        return calls

    def test_blocks_before_tune_when_current_loop_failed(self):
        d = self._ready_driver()
        d.config.identified_current_failure_reason = 6
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        calls = []
        d.homing.invalidate_homing = lambda: calls.append("invalidate_homing")

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("FOCI_AUTOTUNE blocked", str(ctx.exception))
        self.assertIn("current-loop failure reason=6", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(calls, [])

    def test_resolver_preserves_host_default_confidence_bit6(self):
        d = self._ready_driver()
        d.config.identified_inner_warning_flags = None
        d.printer._objects["configfile"] = MockConfigFile()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        self._finish_tune_on_next_pause(d)

        d.autotune.autotune(gcmd)

        args = d.protocol.commands.tune.last_args
        self.assertIsNotNone(args)
        self.assertEqual(args[8], 0x40)
        self.assertIn("inner confidence", gcmd.last_info)

    def test_autotune_moves_to_safe_pose_and_sends_budget(self):
        d = self._ready_driver()
        toolhead = d.printer.lookup_object("toolhead")
        toolhead._kinematics = MockCartesianKinematics([["stepper_x"], ["stepper_y"]])
        toolhead._kinematics.rails[0].get_steppers()[0]._step_dist = 0.01
        toolhead._homed_axes = "xy"
        toolhead.set_bounds(x_min=0.0, x_max=120.0, y_min=0.0, y_max=120.0)
        toolhead.set_position(x=10.0, y=20.0)
        d.printer._objects["configfile"] = MockConfigFile()
        self._finish_tune_on_next_pause(
            d,
            {
                "outer_evidence_flags": 0,
                "stiffness_timebase_ms": 50,
                "velocity_search_stop_reason": 1,
                "motion_budget_mrev": 750,
            },
        )

        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        d.autotune.autotune(gcmd)

        gcode = d.printer.lookup_object("gcode")
        self.assertEqual(gcode._scripts, ["G0 X60.000 Y60.000"])
        self.assertEqual(
            d.protocol.commands.tune.last_args[-8:],
            [5000, 7500, 1, 1000, 250, 1250, 1250, 3000],
        )
        self.assertIn(
            "FOCI foci stepper_x autotune evidence: budget=750mrev "
            "stiffness_timebase=50ms search_stop=1 flags=0x00",
            gcmd._responses,
        )

    def test_autotune_refuses_unsupported_kinematics_before_tune(self):
        d = self._ready_driver()
        toolhead = d.printer.lookup_object("toolhead")
        toolhead._kinematics = MockNoneKinematics()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("unsupported kinematics", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)

    def test_blocks_before_tune_when_live_current_gains_mismatch(self):
        d = self._ready_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        invalidate_calls = []
        d.homing.invalidate_homing = lambda: invalidate_calls.append(
            "invalidate_homing"
        )
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (257 << 16) | 416,
                REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 416,
            },
        )

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("live current-loop gain flux_p mismatch", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(invalidate_calls, [])

    def test_blocks_before_tune_when_live_current_gain_readback_is_missing(self):
        d = self._ready_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        invalidate_calls = []
        d.homing.invalidate_homing = lambda: invalidate_calls.append(
            "invalidate_homing"
        )
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
            },
        )

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("live current-loop gain torque_p unavailable", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(invalidate_calls, [])

    def test_unavailable_stage2_inputs_refuse_before_homing_invalidation_and_tune(self):
        d = self._ready_driver()
        d.config.identified_l_source = 0
        d.config.identified_l_reactance_count_ratio_milli = None
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        invalidate_calls = []
        d.homing.invalidate_homing = lambda: invalidate_calls.append(
            "invalidate_homing"
        )
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
                REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 416,
            },
        )

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn(
            "stage 2 unavailable inputs: average_inductance", str(ctx.exception)
        )
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(invalidate_calls, [])

    def test_default_current_gain_evidence_sets_inner_warning_bit5_for_tune(self):
        d = self._ready_driver()
        d.config.identified_current_gains_source = 2
        d.config.identified_current_gains_tier = 3
        d.printer._objects["configfile"] = MockConfigFile()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
                REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 416,
            },
        )

        def finish_tune(deadline):
            reactor._time = deadline
            d.autotune.handle_tune_result(
                {
                    "status": 0,
                    "warning_code": 0,
                    "velocity_p": 1152,
                    "velocity_i": 0,
                    "position_p": 640,
                    "position_i": 0,
                    "velocity_limit": 500000,
                    "velocity_filter_hz": 0,
                    "torque_filter_hz": 0,
                    "position_filter_hz": 0,
                    "flux_filter_hz": 0,
                    "j_eff": 42,
                    "b_eff": 11,
                }
            )
            return reactor._time

        reactor.pause = finish_tune

        d.autotune.autotune(gcmd)

        args = d.protocol.commands.tune.last_args
        self.assertIsNotNone(args)
        self.assertEqual(args[8], 1 << 5)
