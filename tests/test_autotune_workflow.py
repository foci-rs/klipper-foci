"""Tests for FOCI autotune workflow behavior."""

import unittest

from klipper_foci.autotune import OUTER_SAFETY_FAULT_NAMES
from klipper_foci.commissioning import format_inner_warning_flags
from klipper_foci.registers import REGISTERS
from klipper_foci.velocity_integral import (
    BREAKAWAY_DISCOVERY_SCHEMA_REVISION,
    VelocityIntegralAssembler,
)

from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    MockNoneKinematics,
    MockPrintStats,
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
            kinematics=kinematics or MockCartesianKinematics([["stepper_x"], ["stepper_y"]]),
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
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
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

        # status 2 is a terminal failure here only to end the reactor.pause
        # loop after the timeout workflow runs; it now raises like any
        # other non-accepted terminal status.
        with self.assertRaises(CommandError):
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
        self.assertTrue(any("proportional response" in message for message in gcmd._responses))
        self.assertTrue(any("integral response" in message for message in gcmd._responses))

    def test_no_transition_direct_resume_finishes_without_plan_timeout(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
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
        self.assertTrue(any("response failed" in message for message in gcmd._responses))
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
        self.assertTrue(any("proportional complete" in message for message in gcmd._responses))
        self.assertTrue(any("response failed" in message for message in gcmd._responses))

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

        self.assertTrue(any("proportional response" in message for message in gcmd._responses))
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
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
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
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0])

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
        # The velocity check evaluates a sliding two-interval window and reports
        # that window's totals, so the labels must not read as one observation.
        self.assertIn("window_delta_counts=-125", message)
        self.assertIn("window_dt_us=4000", message)
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

    def test_recovery_wrong_way_fault_is_named_not_unknown(self):
        # Regression case: reason 10
        # (OUTER_SAFETY_FAULT_RECOVERY_WRONG_WAY) printed as "unknown_10",
        # costing real investigation time resolving the code by hand.
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_safety_fault(deadline):
            reactor._time = deadline
            d.autotune.handle_outer_safety_fault(
                {
                    "reason": 10,
                    "max_travel_mrev": 750,
                    "max_velocity_mrev_s": 6000,
                    "max_duration_ms": 3000,
                    "direction_mask": 3,
                    "delta_counts": 2,
                    "dt_us": 0,
                }
            )
            d.autotune.handle_tune_result({"status": 17})
            return reactor._time

        reactor.pause = pause_and_report_safety_fault

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        message = str(ctx.exception)
        self.assertNotIn("unknown_10", message)
        self.assertIn("outer safety recovery_wrong_way", message)

    def test_soft_failure_raises_command_error_instead_of_reporting_success(self):
        # Klipper's gcode dispatcher propagates any CommandError raised from
        # a command handler identically whether FOCI_AUTOTUNE was invoked
        # interactively or from a macro/script, so raising gcmd.error here
        # (like every other terminal-status branch already does) is what
        # makes a calling macro/script see failure instead of silently
        # continuing as if a tune had been accepted.
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_soft_failure(deadline):
            reactor._time = deadline
            d.autotune.handle_tune_result({"status": 43})
            return reactor._time

        reactor.pause = pause_and_report_soft_failure

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        message = str(ctx.exception)
        self.assertIn("FOCI_AUTOTUNE failed", message)
        self.assertIn("closed-loop entry stability failed", message)
        self.assertIn("motor holding with entry gains", message)
        # The disposition message moved entirely into the raised error
        # rather than being printed as an info message a script wouldn't
        # see as a failure.
        self.assertEqual(gcmd._responses, [])


class TestOuterSafetyFaultNames(unittest.TestCase):
    # Mirrors the OUTER_SAFETY_FAULT_* constants in
    # foci-firmware/src/commissioning/types.rs:1776-1796. Firmware and host
    # can drift independently -- there is no shared source of truth across
    # Rust and Python here -- so this list must be updated by hand whenever
    # the firmware adds, removes, or renumbers a constant. That is exactly
    # what this test exists to catch: a code present in the map above but
    # missing here (or vice versa) is a drift the loop below turns into a
    # loud test failure instead of a silent unknown_N at runtime.
    KNOWN_FIRMWARE_CODES = frozenset(range(0, 11))

    def test_every_known_firmware_code_has_a_name(self):
        for code in self.KNOWN_FIRMWARE_CODES:
            self.assertIn(code, OUTER_SAFETY_FAULT_NAMES, f"code {code} has no host-side name")

    def test_names_map_has_no_codes_outside_the_known_set(self):
        unexpected = set(OUTER_SAFETY_FAULT_NAMES) - self.KNOWN_FIRMWARE_CODES
        self.assertEqual(
            unexpected,
            set(),
            "OUTER_SAFETY_FAULT_NAMES has codes not in KNOWN_FIRMWARE_CODES -- "
            "update this test's known-code list to match types.rs",
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
            [5000, 7500, 1, 1500, 250, 1250, 1250, 3000],
        )
        self.assertIn(
            "FOCI foci stepper_x autotune evidence: budget=750mrev "
            "stiffness_timebase=50ms search_stop=1 flags=0x00",
            gcmd._responses,
        )

    def test_accepted_with_warnings_still_succeeds(self):
        d = self._ready_driver()
        toolhead = d.printer.lookup_object("toolhead")
        toolhead._kinematics = MockCartesianKinematics([["stepper_x"], ["stepper_y"]])
        toolhead._kinematics.rails[0].get_steppers()[0]._step_dist = 0.01
        toolhead._homed_axes = "xy"
        toolhead.set_bounds(x_min=0.0, x_max=120.0, y_min=0.0, y_max=120.0)
        toolhead.set_position(x=10.0, y=20.0)
        d.printer._objects["configfile"] = MockConfigFile()
        self._finish_tune_on_next_pause(d, {"status": 1, "warning_code": 1})

        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        d.autotune.autotune(gcmd)

        self.assertEqual(d.state.runtime_status, "tuned_conservative")

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
        d.homing.invalidate_homing = lambda: invalidate_calls.append("invalidate_homing")
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
        d.homing.invalidate_homing = lambda: invalidate_calls.append("invalidate_homing")
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
        d.homing.invalidate_homing = lambda: invalidate_calls.append("invalidate_homing")
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
                REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 416,
            },
        )

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("stage 2 unavailable inputs: average_inductance", str(ctx.exception))
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


class TestVelocitySweepFirmwareSchemaBinding(unittest.TestCase):
    """The sweep assembler must learn Stage-B revision from the connected MCU."""

    def test_sweep_assembler_binds_stage_b_schema_published_by_firmware(self):
        from tests.test_velocity_sweep import feed_firmware_combined_stage_b_plan

        d = make_driver()
        d.mcu.constants["STAGE_B_EVIDENCE_SCHEMA_REVISION"] = 13

        assembler = d.autotune._new_velocity_sweep_assembler()
        feed_firmware_combined_stage_b_plan(assembler)

        self.assertEqual(assembler.combined_stage_b_schema, 13)

    def test_sweep_assembler_falls_back_when_firmware_omits_revision(self):
        from tests.test_velocity_sweep import feed_firmware_combined_stage_b_plan

        d = make_driver()
        d.mcu.constants.pop("STAGE_B_EVIDENCE_SCHEMA_REVISION", None)

        assembler = d.autotune._new_velocity_sweep_assembler()
        feed_firmware_combined_stage_b_plan(assembler)

        self.assertEqual(assembler.combined_stage_b_schema, 12)


# ============================================================================
# Breakaway-seeded campaign: end-to-end host orchestration
# ============================================================================

BREAKAWAY_RUN_SEQUENCE = 21
BREAKAWAY_PROBE_DIGEST = (0x1111_1111, 0x2222_2222)
BREAKAWAY_DISCOVERY_DIGEST = (0x3333_3333, 0x4444_4444)
BREAKAWAY_CONFIRMATION_DIGEST = (0x5555_5555, 0x6666_6666)
BREAKAWAY_STAGE_C_DIGEST = (0x7777_7777, 0x8888_8888)


def feed_breakaway_workflow_plan(driver, run_sequence, maximum_workflow_ms):
    params = {
        "run_sequence": run_sequence,
        "shape": 6,
        "nominal_workflow_ms": maximum_workflow_ms,
        "maximum_workflow_ms": maximum_workflow_ms,
    }
    low, high = VelocityIntegralAssembler.workflow_digest_halves(params)
    driver.autotune.handle_commissioning_workflow_plan(
        {**params, "digest_low": low, "digest_high": high}
    )


def feed_breakaway_probe_and_discovery(driver, run_sequence=BREAKAWAY_RUN_SEQUENCE):
    """Feed a resolved probe and a 2-nomination discovery ladder."""
    probe_low, probe_high = BREAKAWAY_PROBE_DIGEST
    driver.autotune.handle_breakaway_probe_plan(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 0,
            "plan_digest_low": probe_low,
            "plan_digest_high": probe_high,
            "max_observations": 128,
            "search_count": 10,
            "p_start_raw": 100,
            "p_top_raw": 2000,
            "motion_threshold_counts": 63,
            "max_capture_interval_us": 2000,
        }
    )
    driver.autotune.handle_breakaway_probe_result(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 1,
            "plan_digest_low": probe_low,
            "plan_digest_high": probe_high,
            "rung_index": 5,
            "breakaway_p_raw": 320,
            "motion_threshold_counts": 63,
            "observation_count": 14,
        }
    )

    discovery_low, discovery_high = BREAKAWAY_DISCOVERY_DIGEST
    driver.autotune.handle_breakaway_discovery_plan_identity(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "plan_digest_low": discovery_low,
            "plan_digest_high": discovery_high,
            "prior_plan_digest_low": probe_low,
            "prior_plan_digest_high": probe_high,
            "family_size": 32,
        }
    )
    driver.autotune.handle_breakaway_discovery_plan_geometry(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "schema_revision": BREAKAWAY_DISCOVERY_SCHEMA_REVISION,
            "rung_count": 3,
            "observations_per_direction": 8,
            "floor_p_raw": 290,
            "floor_origin": 0,
            "breakaway_p_raw": 320,
            "ceiling_p_raw": 2000,
            "first_additive_step_raw": 40,
            "maximum_workflow_ms": 20_000,
        }
    )
    driver.autotune.handle_breakaway_discovery_ceiling_source(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "plan_digest_low": discovery_low,
            "plan_digest_high": discovery_high,
            "binding_source": 0,
        }
    )
    driver.autotune.handle_breakaway_discovery_rung_zero_diagnostic(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "plan_digest_low": discovery_low,
            "plan_digest_high": discovery_high,
            "forward_moved": 0,
            "reverse_moved": 1,
        }
    )
    driver.autotune.handle_breakaway_discovery_terminal(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "plan_digest_low": discovery_low,
            "plan_digest_high": discovery_high,
            "prior_plan_digest_low": probe_low,
            "prior_plan_digest_high": probe_high,
            "family_size": 32,
            "terminal_cause": 0,
            "collected_count": 2,
            "has_safety_fault": 0,
        }
    )


def feed_breakaway_confirmation(driver, run_sequence=BREAKAWAY_RUN_SEQUENCE, *, accepted):
    """Feed a full held-out 8-stroke confirmation block, then the campaign
    closure record -- accepted, or ending in a TargetBandConfirmationInconclusive
    ResponseLocation cause (wire code 15)."""
    discovery_low, discovery_high = BREAKAWAY_DISCOVERY_DIGEST
    confirm_low, confirm_high = BREAKAWAY_CONFIRMATION_DIGEST
    driver.autotune.handle_breakaway_confirmation_plan(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 3,
            "plan_digest_low": confirm_low,
            "plan_digest_high": confirm_high,
            "prior_plan_digest_low": discovery_low,
            "prior_plan_digest_high": discovery_high,
            "family_size": 8,
            "observations_per_direction": 4,
            "candidate_p_raw": 400,
            "band_lower_percent": 70,
            "band_upper_percent": 80,
            "capture_profile": 0,
            "acceptance_rule": 0,
            "nominated_margin_percent_milli": 2_000,
        }
    )
    driver.autotune.handle_breakaway_confirmation_terminal_identity(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 3,
            "plan_digest_low": confirm_low,
            "plan_digest_high": confirm_high,
            "prior_plan_digest_low": discovery_low,
            "prior_plan_digest_high": discovery_high,
            "family_size": 8,
            "terminal_cause": 21 if accepted else 15,
        }
    )
    driver.autotune.handle_breakaway_confirmation_terminal_masks(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 3,
            "forward_collected_mask": 0b1111,
            "forward_eligible_mask": 0b1111,
            "forward_included_mask": 0b1111,
            "reverse_collected_mask": 0b1111,
            "reverse_eligible_mask": 0b1111,
            "reverse_included_mask": 0b1111,
            "accepted": int(accepted),
            "confirmed_p_raw": 400 if accepted else 0,
            "max_relative_se_permille": 500 if accepted else 900,
            "required_relative_se_permille": 667,
            "has_safety_fault": 0,
        }
    )
    stage_c_low, stage_c_high = BREAKAWAY_STAGE_C_DIGEST if accepted else (0, 0)
    driver.autotune.handle_breakaway_campaign_terminal(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 4,
            "phase": 2,
            "terminal_cause": 21 if accepted else 15,
            "accepted": int(accepted),
            "stage_c_plan_digest_low": stage_c_low,
            "stage_c_plan_digest_high": stage_c_high,
        }
    )


class TestBreakawayCampaignWorkflow(unittest.TestCase):
    def _commissioned_driver(self):
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=MockCartesianKinematics([["stepper_x"], ["stepper_y"]]),
            homed_axes="xyz",
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

    def test_workflow_envelope_precedes_motion_and_extends_host_timeout(self):
        """Brief step 1: the command-level envelope arrives before any motion
        evidence, then the host's short 5s setup timeout is replaced by one
        derived from the firmware-declared `maximum_workflow_ms` -- simulated
        time is pushed well past 5s below and the run still completes instead
        of raising "timed out waiting for plan"."""
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        pauses = 0

        def pause_with_breakaway_campaign(deadline):
            nonlocal pauses
            pauses += 1
            reactor._time = deadline
            if d.autotune.velocity_integral.workflow_plan is None:
                feed_breakaway_workflow_plan(d, BREAKAWAY_RUN_SEQUENCE, 400_000)
            elif d.autotune.breakaway_campaign.discovery_terminal is None and reactor._time >= 5.5:
                feed_breakaway_probe_and_discovery(d)
            elif (
                d.autotune.breakaway_campaign.discovery_terminal is not None
                and not d.autotune.breakaway_campaign.done
                and reactor._time >= 5.6
            ):
                feed_breakaway_confirmation(d, accepted=True)
                d.autotune.velocity_integral.plan = {
                    "plan_digest": (
                        BREAKAWAY_STAGE_C_DIGEST[0] | (BREAKAWAY_STAGE_C_DIGEST[1] << 32)
                    )
                }
                d.autotune.velocity_integral.outcome = "complete"
                d.autotune.velocity_integral.terminal = {"cause": 0}
                d.autotune.velocity_integral.done = True
            return reactor._time

        reactor.pause = pause_with_breakaway_campaign

        d.autotune.autotune(gcmd)

        self.assertGreater(reactor._time, 5.0)
        self.assertIsNone(d.autotune.breakaway_campaign_error)
        self.assertIsNone(d.autotune.velocity_integral_error)
        self.assertTrue(d.autotune.breakaway_campaign.accepted)
        self.assertTrue(
            any("breakaway campaign accepted" in message for message in gcmd._responses)
        )
        self.assertTrue(any("integral response" in message for message in gcmd._responses))

    def test_operator_report_relays_geometry_margin_and_confirmation_bounds(self):
        """Brief step 3: the breakaway seed, additive geometry, nomination
        margin, confirmation bounds, and terminal remediation are all present
        in the operator-facing text, copied verbatim from firmware records."""
        d = self._commissioned_driver()
        feed_breakaway_workflow_plan(d, BREAKAWAY_RUN_SEQUENCE, 400_000)
        feed_breakaway_probe_and_discovery(d)
        feed_breakaway_confirmation(d, accepted=False)

        message = d.autotune._format_breakaway_campaign_result()

        self.assertIn("breakaway=320 rung=5 obs=14", message)
        self.assertIn("floor=290", message)
        self.assertIn("breakaway=320", message)
        self.assertIn("ceiling=2000", message)
        self.assertIn("step=40", message)
        self.assertIn("rungs=3", message)
        self.assertIn("nominated P=400 margin=2000pm", message)
        self.assertIn("confirmed P=0 measured_SE=900pm required_SE=667pm", message)
        self.assertIn("remediation:", message)

    def test_confirmation_inconclusive_preserves_prior_p_and_skips_persistence(self):
        """Brief step 4: on a non-accept terminal, the previously commissioned
        P is untouched and neither Stage-C completion nor the persistence
        callback ever runs."""
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        persisted = []
        d.autotune.persist_tune_results = lambda *args, **kwargs: persisted.append((args, kwargs))

        def pause_with_inconclusive_confirmation(deadline):
            reactor._time = deadline
            if d.autotune.velocity_integral.workflow_plan is None:
                feed_breakaway_workflow_plan(d, BREAKAWAY_RUN_SEQUENCE, 400_000)
            elif not d.autotune.breakaway_campaign.done:
                feed_breakaway_probe_and_discovery(d)
                feed_breakaway_confirmation(d, accepted=False)
            return reactor._time

        reactor.pause = pause_with_inconclusive_confirmation

        d.autotune.autotune(gcmd)

        self.assertFalse(d.autotune.breakaway_campaign.accepted)
        self.assertIsNone(d.autotune.velocity_integral.plan)
        self.assertFalse(d.autotune.velocity_integral.done)
        self.assertEqual(d.state.active_gains, SAMPLE_ACTIVE_GAINS)
        self.assertEqual(persisted, [])
        self.assertTrue(
            any("breakaway campaign not accepted" in message for message in gcmd._responses)
        )

    def test_dumb_host_never_reissues_a_second_confirmation_after_acceptance(self):
        """Brief step 2: the host cannot be coerced into "retrying" a
        candidate. Feeding a second confirmation plan after the campaign
        already closed is rejected as a protocol violation, not silently
        accepted as an alternate candidate -- there is no host-side retry
        path to exercise."""
        d = self._commissioned_driver()
        feed_breakaway_workflow_plan(d, BREAKAWAY_RUN_SEQUENCE, 400_000)
        feed_breakaway_probe_and_discovery(d)
        feed_breakaway_confirmation(d, accepted=False)

        self.assertTrue(d.autotune.breakaway_campaign.done)
        self.assertIsNone(d.autotune.breakaway_campaign_error)

        confirm_low, confirm_high = BREAKAWAY_CONFIRMATION_DIGEST
        discovery_low, discovery_high = BREAKAWAY_DISCOVERY_DIGEST
        d.autotune.handle_breakaway_confirmation_plan(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 5,
                "plan_digest_low": confirm_low,
                "plan_digest_high": confirm_high,
                "prior_plan_digest_low": discovery_low,
                "prior_plan_digest_high": discovery_high,
                "family_size": 8,
                "observations_per_direction": 4,
                "candidate_p_raw": 360,  # a different candidate: never chosen
                "band_lower_percent": 70,
                "band_upper_percent": 80,
                "capture_profile": 0,
                "acceptance_rule": 0,
                "nominated_margin_percent_milli": 2_000,
            }
        )

        self.assertIsNotNone(d.autotune.breakaway_campaign_error)
        self.assertIn("duplicate confirmation", str(d.autotune.breakaway_campaign_error))
