"""Tests for FOCI autotune workflow behavior."""

import unittest

from klipper_foci.acceptance_matrix import ACTION_CODES
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
    MockCoreXYKinematics,
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


SAMPLE_STAGE_C_RESUME_RESULT = {
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
}

# Production breakaway path: the only path FOCI_AUTOTUNE ships, always
# carrying real provenance -- mirrors `robustness_pass_outer_result` in
# firmware.
SAMPLE_TUNE_RESULT = {
    "status": 0,
    "warning_code": 0,
    "velocity_p": 863,
    "velocity_i": 12,
    "position_p": 480,
    "position_i": 4,
    "velocity_limit": 400000,
    "velocity_filter_hz": 120,
    "torque_filter_hz": 200,
    "position_filter_hz": 60,
    "flux_filter_hz": 200,
    "probed_velocity_mrev_s": 5366,
    "d_eq_q": 1234,
    "confidence_q": 5000,
    "band_lower_percent": 70,
    "band_upper_percent": 80,
    "band_position_q": 3000,
}


def _feed_dispatch_terminal(workflow, terminal, tune_result=None):
    """Inject the terminal named by ``terminal`` into one dispatch's assemblers.

    "tune_result" delivers a full firmware TuneResult (``handle_tune_result``),
    defaulting to ``SAMPLE_STAGE_C_RESUME_RESULT`` unless ``tune_result`` names a
    different payload. Any other name is treated as a velocity-integral outcome
    and is stamped directly onto the assembler -- the same lightweight pattern
    already used by ``test_workflow_finishes_for_a_refusal_that_declared_no_envelope``
    -- since these orchestration tests only care that ``autotune()`` reacts to
    the right outcome name, not that the underlying evidence is wire-valid.
    """
    if terminal == "tune_result":
        workflow.handle_tune_result(dict(tune_result or SAMPLE_STAGE_C_RESUME_RESULT))
        return
    if terminal == "breakaway_accepted_complete_candidate":
        # Real firmware behavior: an accepted breakaway_seeded run reaches
        # its velocity-integral terminal in the SAME dispatch as the
        # breakaway campaign's own acceptance terminal -- both terminals
        # land together, not one after the other.
        workflow.breakaway_campaign.done = True
        workflow.breakaway_campaign.accepted = True
        workflow.velocity_integral.outcome = "complete_candidate"
        workflow.velocity_integral.terminal = {"cause": 0}
        workflow.velocity_integral.done = True
        return
    outcome = "inconclusive" if terminal == "velocity_integral_inconclusive" else terminal
    workflow.velocity_integral.outcome = outcome
    workflow.velocity_integral.terminal = {"cause": 0}
    workflow.velocity_integral.done = True


def drive_two_dispatch_scenario(d, *, first_terminal, second_terminal, tune_result=None):
    """Feed a two-dispatch FOCI_AUTOTUNE scenario through the mocked reactor.

    Each firmware dispatch gets exactly one simulated ``reactor.pause``: the
    first delivers ``first_terminal``, the second (issued only when the first
    was "complete_candidate") delivers ``second_terminal``. This wraps whatever
    ``run_tune`` is already installed (tests may replace it beforehand to
    observe the dispatched actions) purely to count dispatches. ``tune_result``
    is forwarded to ``_feed_dispatch_terminal`` when either terminal is
    "tune_result", letting callers assert on distinguishable field values.
    """
    reactor = d.printer.get_reactor()
    previous_run_tune = d.protocol.run_tune
    dispatch_count = {"n": 0}

    def counting_run_tune(**kwargs):
        dispatch_count["n"] += 1
        return previous_run_tune(**kwargs)

    d.protocol.run_tune = counting_run_tune

    def pause(deadline):
        reactor._time = deadline
        terminal = first_terminal if dispatch_count["n"] == 1 else second_terminal
        _feed_dispatch_terminal(d.autotune, terminal, tune_result)
        return reactor._time

    reactor.pause = pause


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

    def test_stage_b_changed_request_is_not_normalized_to_retained_plan(self):
        d = self._commissioned_driver()
        retained = {"profile_code": 1, "requested_velocity_mrev_s": 2929}
        changed = {"profile_code": 1, "requested_velocity_mrev_s": 3000}
        d.autotune._stage_b_candidate_request = dict(retained)

        dispatched = d.autotune._request_for_stage_b_dispatch(changed)

        self.assertEqual(dispatched, changed)

    def test_complete_candidate_auto_issues_stage_c_resume(self):
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        gcmd = MockGCmd({})  # default ACTION -> breakaway_seeded
        issued = []
        d.protocol.run_tune = lambda **kw: issued.append(kw["action"])
        drive_two_dispatch_scenario(
            d,
            first_terminal="breakaway_accepted_complete_candidate",
            second_terminal="tune_result",
        )

        d.autotune.autotune(gcmd)

        self.assertEqual(
            issued,
            [ACTION_CODES["breakaway_seeded"], ACTION_CODES["stage_c_resume"]],
        )

    def test_cold_start_self_homes_without_up_front_calibration(self):
        """A commissioned driver that lost calibration+homing (e.g. after a
        klipper restart) must self-home through the dispatch instead of
        rejecting up front. The motion plan is config-derived, and
        ``_rehome_and_center`` arms the motor before the tune runs."""
        d = self._commissioned_driver(homed_axes="")
        d.state.is_calibrated = False
        d.printer._objects["configfile"] = MockConfigFile()
        gcmd = MockGCmd({})
        issued = []
        d.protocol.run_tune = lambda **kw: issued.append(kw["action"])
        drive_two_dispatch_scenario(
            d,
            first_terminal="tune_result",
            second_terminal="tune_result",
        )

        d.autotune.autotune(gcmd)

        self.assertEqual(issued, [ACTION_CODES["breakaway_seeded"]])

    def test_run_one_dispatch_rehomes_and_recenters_before_run_tune(self):
        """The breakaway terminal unhomes the axes and re-zeroes the encoder,
        so every firmware stage dispatch must re-home (G28, which also re-runs
        calibrate-on-enable) and re-center before it issues run_tune."""
        d = self._commissioned_driver()
        toolhead = d.printer.lookup_object("toolhead")
        gcode = d.printer.lookup_object("gcode")
        gcmd = MockGCmd({})
        events = []
        gcode.run_script_from_command = lambda command: events.append(("script", command))
        d.protocol.run_tune = lambda **kw: events.append(("run_tune", kw["action"]))

        reactor = d.printer.get_reactor()

        def pause(deadline):
            reactor._time = deadline
            _feed_dispatch_terminal(d.autotune, "tune_result")
            return reactor._time

        reactor.pause = pause
        d.state.operation_lock = True  # autotune() holds the lock across dispatches

        request_fields = {"profile_code": 1, "requested_velocity_mrev_s": 2929}
        d.autotune._run_one_dispatch(
            gcmd,
            ACTION_CODES["breakaway_seeded"],
            request_fields,
            toolhead,
            "G0 X100.000 Y100.000",
        )

        self.assertEqual(events[0], ("script", "G28 X Y"))
        self.assertEqual(events[1], ("script", "G0 X100.000 Y100.000"))
        self.assertEqual(events[2], ("run_tune", ACTION_CODES["breakaway_seeded"]))

    def test_homing_failure_aborts_before_run_tune(self):
        """A homing failure during the per-dispatch re-home must abort autotune,
        never fall through to run_tune against unhomed/unaligned axes."""
        d = self._commissioned_driver()
        toolhead = d.printer.lookup_object("toolhead")
        gcode = d.printer.lookup_object("gcode")
        gcmd = MockGCmd({})
        issued = []

        def failing_script(command):
            if command == "G28 X Y":
                raise CommandError("No trigger on stepper_y after full movement")

        gcode.run_script_from_command = failing_script
        d.protocol.run_tune = lambda **kw: issued.append(kw["action"])
        d.state.operation_lock = True

        with self.assertRaises(CommandError) as ctx:
            d.autotune._run_one_dispatch(
                gcmd,
                ACTION_CODES["breakaway_seeded"],
                {"profile_code": 1, "requested_velocity_mrev_s": 2929},
                toolhead,
                "G0 X100.000 Y100.000",
            )

        self.assertIn("homing", str(ctx.exception).lower())
        self.assertEqual(issued, [])

    def test_dispatch_timeout_disables_motor_to_cancel_firmware_run(self):
        """A host timeout must enqueue the firmware cancel/disarm path."""
        d = self._commissioned_driver()
        toolhead = d.printer.lookup_object("toolhead")
        gcmd = MockGCmd({})
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
        enable_line.motor_enable(toolhead.get_last_move_time())
        d.protocol.run_tune = lambda **kw: None

        reactor = d.printer.get_reactor()

        def pause(deadline):
            reactor._time = deadline
            return reactor._time

        reactor.pause = pause
        d.state.operation_lock = True

        with self.assertRaises(CommandError) as ctx:
            d.autotune._run_one_dispatch(
                gcmd,
                ACTION_CODES["breakaway_seeded"],
                {"profile_code": 1, "requested_velocity_mrev_s": 2929},
                toolhead,
                "G0 X100.000 Y100.000",
            )

        self.assertIn("timed out", str(ctx.exception))
        self.assertFalse(enable_line.is_motor_enabled())

    def test_each_stage_dispatch_is_preceded_by_a_rehome(self):
        """Both the breakaway_seeded dispatch and the auto-issued stage_c_resume
        dispatch must be preceded by their own G28 re-home -- the chained
        resume otherwise runs against the encoder the first dispatch re-zeroed."""
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        gcmd = MockGCmd({})
        gcode = d.printer.lookup_object("gcode")
        events = []
        gcode.run_script_from_command = lambda command: events.append(("script", command))
        d.protocol.run_tune = lambda **kw: events.append(("run_tune", kw["action"]))
        drive_two_dispatch_scenario(
            d,
            first_terminal="breakaway_accepted_complete_candidate",
            second_terminal="tune_result",
        )

        d.autotune.autotune(gcmd)

        rehomed_since_dispatch = False
        dispatches = 0
        for kind, value in events:
            if kind == "script" and value == "G28 X Y":
                rehomed_since_dispatch = True
            elif kind == "run_tune":
                self.assertTrue(
                    rehomed_since_dispatch,
                    "stage dispatch was not preceded by a re-home",
                )
                dispatches += 1
                rehomed_since_dispatch = False
        self.assertEqual(dispatches, 2)

    def test_resume_inconclusive_errors_and_skips_persistence(self):
        d = self._commissioned_driver()
        persisted = []
        d.autotune.persist_tune_results = lambda *a, **k: persisted.append((a, k))
        drive_two_dispatch_scenario(
            d,
            first_terminal="breakaway_accepted_complete_candidate",
            second_terminal="velocity_integral_inconclusive",
        )

        with self.assertRaises(CommandError):
            d.autotune.autotune(MockGCmd({}))

        self.assertEqual(persisted, [])

    def test_production_tune_result_deploys_and_persists(self):
        """The promoted resume dispatch emits no host-terminal velocity-integral
        or robustness reply (Tasks 3-4); the wait loop must exit on
        ``self.done`` (set by ``handle_tune_result``) and fall through to the
        same deploy + persist tail a standalone accepted run already uses."""
        d = self._commissioned_driver()
        cfg = MockConfigFile()
        d.printer._objects["configfile"] = cfg
        drive_two_dispatch_scenario(
            d,
            first_terminal="breakaway_accepted_complete_candidate",
            second_terminal="tune_result",
            tune_result=SAMPLE_TUNE_RESULT,
        )

        d.autotune.autotune(MockGCmd({}))

        self.assertEqual(d.state.active_gains["velocity_p"], 863)
        self.assertEqual(cfg.values[(d.name, "pid_velocity_p")], "863")
        self.assertEqual(cfg.values[(d.name, "pid_position_p")], "480")
        self.assertEqual(cfg.values[(d.name, "autotune_status")], "tuned")
        self.assertNotIn((d.name, "identified_j_eff"), cfg.values)
        self.assertNotIn((d.name, "identified_b_eff"), cfg.values)
        self.assertEqual(cfg.values[(d.name, "autotune_probed_velocity_mrev_s")], "5366")

    def test_successful_corexy_autotune_disables_kinematic_pair(self):
        """A successful tune must not leave one CoreXY motor holding while the
        tuned motor has returned to a conservative firmware voltage limit."""
        d = self._commissioned_driver(
            kinematics=MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        )
        d.printer._objects["configfile"] = MockConfigFile()
        toolhead = d.printer.lookup_object("toolhead")
        stepper_enable = d.printer.lookup_object("stepper_enable")
        x_enable = stepper_enable.lookup_enable("stepper_x")
        y_enable = stepper_enable.lookup_enable("stepper_y")
        x_enable.motor_enable(toolhead.get_last_move_time())
        y_enable.motor_enable(toolhead.get_last_move_time())
        drive_two_dispatch_scenario(
            d,
            first_terminal="breakaway_accepted_complete_candidate",
            second_terminal="tune_result",
            tune_result=SAMPLE_TUNE_RESULT,
        )

        d.autotune.autotune(MockGCmd({}))

        self.assertFalse(x_enable.is_motor_enabled())
        self.assertFalse(y_enable.is_motor_enabled())

    def test_persist_writes_provenance_block(self):
        d = self._commissioned_driver()
        cfg = MockConfigFile()
        d.printer._objects["configfile"] = cfg
        d.autotune.persist_tune_results(SAMPLE_TUNE_RESULT, "nominal", "tuned")
        self.assertEqual(cfg.values[(d.name, "autotune_probed_velocity_mrev_s")], "5366")
        self.assertEqual(cfg.values[(d.name, "autotune_d_eq_q")], "1234")
        self.assertEqual(cfg.values[(d.name, "autotune_confidence_q")], "5000")
        self.assertEqual(cfg.values[(d.name, "autotune_band_lower_percent")], "70")
        self.assertEqual(cfg.values[(d.name, "autotune_band_upper_percent")], "80")
        self.assertEqual(cfg.values[(d.name, "autotune_band_position_q")], "3000")

    def test_persist_never_writes_removed_mechanical_id_fields(self):
        """identified_j_eff/identified_b_eff persistence is removed entirely --
        no tune result, real or synthetic, may re-introduce them into
        SAVE_CONFIG output."""
        d = self._commissioned_driver()
        cfg = MockConfigFile()
        d.printer._objects["configfile"] = cfg
        d.autotune.persist_tune_results(SAMPLE_TUNE_RESULT, "nominal", "tuned")
        self.assertNotIn((d.name, "identified_j_eff"), cfg.values)
        self.assertNotIn((d.name, "identified_b_eff"), cfg.values)

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

    def test_missing_workflow_plan_uses_short_setup_timeout(self):
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

    def test_robustness_workflow_arms_extended_timeout_past_setup_window(self):
        from tests.test_robustness_reversal import build_terminal_payload

        d = self._commissioned_driver()
        gcmd = MockGCmd({"ACTION": "robustness_reversal"})
        reactor = d.printer.get_reactor()

        def pause_with_robustness_plan(deadline):
            reactor._time = deadline
            if d.autotune.robustness_workflow_plan is None:
                # The firmware discloses the run duration before any motion.
                d.autotune.handle_commissioning_workflow_plan(
                    {
                        "run_sequence": 7,
                        "shape": 7,
                        "nominal_workflow_ms": 15_000,
                        "maximum_workflow_ms": 32_000,
                        "digest_low": 0,
                        "digest_high": 0,
                    }
                )
            # The terminal only arrives well past the 5 s initial plan window;
            # without the extended arming this run would already have timed out.
            if reactor._time >= 6.0:
                d.autotune.handle_robustness_reversal_terminal(
                    {"payload": build_terminal_payload(outcome=0, cause=0)}
                )
            return reactor._time

        reactor.pause = pause_with_robustness_plan

        d.autotune.autotune(gcmd)

        self.assertGreaterEqual(reactor._time, 6.0)
        self.assertIsNotNone(d.autotune.robustness_reversal_terminal)
        self.assertIsNone(d.autotune.robustness_reversal_error)
        # The robustness plan alone armed the extended timeout, not the
        # acceptance-matrix or velocity-integral paths.
        self.assertIsNotNone(d.autotune.robustness_workflow_plan)
        self.assertIsNone(d.autotune.acceptance_matrix.workflow_plan)
        self.assertIsNone(d.autotune.velocity_integral.workflow_plan)

    def test_robustness_reject_preserves_prior_gains_and_skips_persistence(self):
        """A rejected robustness-reversal terminal validates an already-accepted
        candidate from an earlier tune; it must never write gains itself, so a
        reject leaves whatever gains were active (and the config) untouched."""
        from tests.test_robustness_reversal import build_terminal_payload

        d = self._commissioned_driver()
        gcmd = MockGCmd({"ACTION": "robustness_reversal"})
        reactor = d.printer.get_reactor()
        persisted = []
        d.autotune.persist_tune_results = lambda *args, **kwargs: persisted.append((args, kwargs))

        def pause_with_rejected_robustness(deadline):
            reactor._time = deadline
            if d.autotune.robustness_workflow_plan is None:
                d.autotune.handle_commissioning_workflow_plan(
                    {
                        "run_sequence": 7,
                        "shape": 7,
                        "nominal_workflow_ms": 15_000,
                        "maximum_workflow_ms": 32_000,
                        "digest_low": 0,
                        "digest_high": 0,
                    }
                )
            elif d.autotune.robustness_reversal_terminal is None:
                d.autotune.handle_robustness_reversal_terminal(
                    {"payload": build_terminal_payload(outcome=1, cause=3)}
                )
            return reactor._time

        reactor.pause = pause_with_rejected_robustness

        d.autotune.autotune(gcmd)

        self.assertIsNotNone(d.autotune.robustness_reversal_terminal)
        self.assertEqual(d.autotune.robustness_reversal_terminal["outcome_name"], "rejected")
        self.assertIsNone(d.autotune.robustness_reversal_error)
        self.assertEqual(d.state.active_gains, SAMPLE_ACTIVE_GAINS)
        self.assertEqual(persisted, [])
        self.assertTrue(
            any("robustness reversal: rejected" in message for message in gcmd._responses)
        )

    def test_standalone_robustness_still_reports_only(self):
        """ACTION=robustness_reversal is the standalone diagnostic: a reject
        must keep formatting the report-only result, exactly as before the
        production-path disambiguation was added, and must not persist."""
        from tests.test_robustness_reversal import build_terminal_payload

        d = self._commissioned_driver()
        gcmd = MockGCmd({"ACTION": "robustness_reversal"})
        reactor = d.printer.get_reactor()
        persisted = []
        d.autotune.persist_tune_results = lambda *args, **kwargs: persisted.append((args, kwargs))

        def pause_with_rejected_robustness(deadline):
            reactor._time = deadline
            if d.autotune.robustness_workflow_plan is None:
                d.autotune.handle_commissioning_workflow_plan(
                    {
                        "run_sequence": 7,
                        "shape": 7,
                        "nominal_workflow_ms": 15_000,
                        "maximum_workflow_ms": 32_000,
                        "digest_low": 0,
                        "digest_high": 0,
                    }
                )
            elif d.autotune.robustness_reversal_terminal is None:
                d.autotune.handle_robustness_reversal_terminal(
                    {"payload": build_terminal_payload(outcome=1, cause=3)}
                )
            return reactor._time

        reactor.pause = pause_with_rejected_robustness

        d.autotune.autotune(gcmd)

        self.assertEqual(persisted, [])
        self.assertTrue(
            any("robustness reversal: rejected" in message for message in gcmd._responses)
        )

    def test_production_path_robustness_terminal_raises(self):
        """The inline production dispatch (default ACTION=breakaway_seeded)
        promotes straight to a TuneResult on a robustness pass, so a
        RobustnessReversalTerminal reaching this dispatch at all is a fault.
        It must raise instead of taking the standalone report-only path."""
        from tests.test_robustness_reversal import build_terminal_payload

        d = self._commissioned_driver()
        gcmd = MockGCmd({})  # default ACTION -> breakaway_seeded
        reactor = d.printer.get_reactor()

        def pause_with_rejected_robustness(deadline):
            reactor._time = deadline
            if d.autotune.robustness_workflow_plan is None:
                d.autotune.handle_commissioning_workflow_plan(
                    {
                        "run_sequence": 7,
                        "shape": 7,
                        "nominal_workflow_ms": 15_000,
                        "maximum_workflow_ms": 32_000,
                        "digest_low": 0,
                        "digest_high": 0,
                    }
                )
            elif d.autotune.robustness_reversal_terminal is None:
                d.autotune.handle_robustness_reversal_terminal(
                    {"payload": build_terminal_payload(outcome=1, cause=3)}
                )
            return reactor._time

        reactor.pause = pause_with_rejected_robustness

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("no robust gain", str(ctx.exception).lower())

    def test_production_iae_reject_reports_no_robust_gain(self):
        from tests.test_robustness_reversal import (
            build_cycle_evidence_payload,
            build_terminal_payload,
        )

        d = self._commissioned_driver()
        gcmd = MockGCmd({})
        reactor = d.printer.get_reactor()

        def pause_with_rejected_robustness(deadline):
            reactor._time = deadline
            if d.autotune.robustness_workflow_plan is None:
                d.autotune.handle_commissioning_workflow_plan(
                    {
                        "run_sequence": 7,
                        "shape": 7,
                        "nominal_workflow_ms": 15_000,
                        "maximum_workflow_ms": 32_000,
                        "digest_low": 0,
                        "digest_high": 0,
                    }
                )
            elif d.autotune.robustness_reversal_terminal is None:
                d.autotune.handle_robustness_cycle_evidence(
                    {"payload": build_cycle_evidence_payload(direction=0, iae_median_qs=1_530_000)}
                )
                d.autotune.handle_robustness_cycle_evidence(
                    {"payload": build_cycle_evidence_payload(direction=1, iae_median_qs=1_490_000)}
                )
                d.autotune.handle_robustness_reversal_terminal(
                    {
                        "payload": build_terminal_payload(
                            outcome=1,
                            cause=3,
                            selected_p=460,
                            selected_i=900,
                            iae_max_q_qs=1_181_812,
                        )
                    }
                )
            return reactor._time

        reactor.pause = pause_with_rejected_robustness

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        message = str(ctx.exception)
        self.assertIn("no robust gain", message.lower())
        self.assertIn("response band", message.lower())
        self.assertIn("460", message)
        self.assertIn("900", message)
        self.assertIn("1530000", message)
        self.assertIn("1181812", message)

    def test_production_path_safety_fault_inhibits_enable(self):
        """A safety-fault robustness terminal (outcome=3, cause=6) on the inline
        production dispatch must still inhibit motor enable, exactly as the
        standalone diagnostic does -- chip state is unknown after a mid-run
        safety fault regardless of which ACTION triggered the run, and no
        terminal-owned motor_disable follows this path (unlike status>1 hard
        faults), so the inhibit is the only thing blocking a re-energize."""
        from tests.test_robustness_reversal import build_terminal_payload

        d = self._commissioned_driver()
        gcmd = MockGCmd({})  # default ACTION -> breakaway_seeded
        reactor = d.printer.get_reactor()

        def pause_with_safety_fault(deadline):
            reactor._time = deadline
            if d.autotune.robustness_workflow_plan is None:
                d.autotune.handle_commissioning_workflow_plan(
                    {
                        "run_sequence": 7,
                        "shape": 7,
                        "nominal_workflow_ms": 15_000,
                        "maximum_workflow_ms": 32_000,
                        "digest_low": 0,
                        "digest_high": 0,
                    }
                )
            elif d.autotune.robustness_reversal_terminal is None:
                d.autotune.handle_robustness_reversal_terminal(
                    {"payload": build_terminal_payload(outcome=3, cause=6)}
                )
            return reactor._time

        reactor.pause = pause_with_safety_fault

        with self.assertRaises(CommandError):
            d.autotune.autotune(gcmd)

        self.assertTrue(d.state.inhibited)

    def _tuned_snapshot(self, velocity_p=999):
        return {
            "active_gains": {**SAMPLE_ACTIVE_GAINS, "velocity_p": velocity_p},
            "runtime_status": "tuned",
            "autotune_mode": "balanced",
        }

    def _run_robustness(self, d, outcome, cause):
        from tests.test_robustness_reversal import build_terminal_payload

        gcmd = MockGCmd({"ACTION": "robustness_reversal"})
        reactor = d.printer.get_reactor()

        def pause(deadline):
            reactor._time = deadline
            if d.autotune.robustness_workflow_plan is None:
                d.autotune.handle_commissioning_workflow_plan(
                    {
                        "run_sequence": 7,
                        "shape": 7,
                        "nominal_workflow_ms": 15_000,
                        "maximum_workflow_ms": 32_000,
                        "digest_low": 0,
                        "digest_high": 0,
                    }
                )
            elif d.autotune.robustness_reversal_terminal is None:
                d.autotune.handle_robustness_reversal_terminal(
                    {"payload": build_terminal_payload(outcome=outcome, cause=cause)}
                )
            return reactor._time

        reactor.pause = pause
        d.autotune.autotune(gcmd)
        return gcmd

    def test_reject_retune_reverts_full_set(self):
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        d.state.pre_tune_snapshot = self._tuned_snapshot()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "tuned"
        cfg = d.printer.lookup_object("configfile")
        gcmd = self._run_robustness(d, outcome=1, cause=3)
        self.assertEqual(d.state.active_gains["velocity_p"], 999)
        self.assertEqual(cfg.values[(d.name, "pid_velocity_p")], "999")
        self.assertEqual(
            cfg.values[(d.name, "pid_velocity_limit")],
            f"{int(SAMPLE_ACTIVE_GAINS['velocity_limit'])}",
        )
        self.assertEqual(
            cfg.values[(d.name, "position_filter_hz")],
            f"{int(SAMPLE_ACTIVE_GAINS['position_filter_hz'])}",
        )
        self.assertEqual(cfg.values[(d.name, "autotune_status")], "tuned")
        self.assertEqual(cfg.values[(d.name, "autotune_mode")], "balanced")
        self.assertTrue(any("retained the pre-tune gain" in m for m in gcmd._responses))

    def test_reject_first_tune_errors_and_reverts_to_commissioned(self):
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        d.state.pre_tune_snapshot = {
            "active_gains": {**SAMPLE_ACTIVE_GAINS, "velocity_p": 555},
            "runtime_status": "commissioned",
            "autotune_mode": None,
        }
        d.state.runtime_status = "tuned"
        cfg = d.printer.lookup_object("configfile")
        with self.assertRaises(CommandError):
            self._run_robustness(d, outcome=1, cause=3)
        self.assertEqual(d.state.active_gains["velocity_p"], 555)
        self.assertEqual(cfg.values[(d.name, "autotune_status")], "commissioned")
        self.assertFalse(d.state.inhibited)

    def test_inconclusive_reverts_and_advises_rerun(self):
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        d.state.pre_tune_snapshot = self._tuned_snapshot()
        gcmd = self._run_robustness(d, outcome=2, cause=4)
        self.assertEqual(d.state.active_gains["velocity_p"], 999)
        self.assertTrue(any("inconclusive" in m for m in gcmd._responses))

    def test_evidence_integrity_failed_errors_on_retune(self):
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        d.state.pre_tune_snapshot = self._tuned_snapshot()
        with self.assertRaises(CommandError):
            self._run_robustness(d, outcome=3, cause=7)
        self.assertEqual(d.state.active_gains["velocity_p"], 999)

    def test_complete_clears_snapshot(self):
        d = self._commissioned_driver()
        d.state.pre_tune_snapshot = self._tuned_snapshot()
        self._run_robustness(d, outcome=0, cause=0)
        self.assertIsNone(d.state.pre_tune_snapshot)

    def test_snapshot_retained_across_reject(self):
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        d.state.pre_tune_snapshot = self._tuned_snapshot()
        self._run_robustness(d, outcome=1, cause=3)
        # Retained (not cleared) so a later re-run still has a revert target.
        self.assertIsNotNone(d.state.pre_tune_snapshot)
        self.assertEqual(d.state.pre_tune_snapshot["active_gains"]["velocity_p"], 999)

    def test_reject_without_snapshot_reports_only(self):
        d = self._commissioned_driver()
        d.state.pre_tune_snapshot = None
        before = d.state.active_gains.copy()
        gcmd = self._run_robustness(d, outcome=1, cause=3)
        self.assertEqual(d.state.active_gains, before)
        self.assertTrue(any("robustness reversal" in m for m in gcmd._responses))

    def test_safety_fault_inhibits_without_repush(self):
        d = self._commissioned_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        d.state.pre_tune_snapshot = self._tuned_snapshot()
        pushes = []
        d.homing.apply_active_gains_to_firmware = lambda: pushes.append(True)
        cfg = d.printer.lookup_object("configfile")
        with self.assertRaises(CommandError):
            self._run_robustness(d, outcome=3, cause=6)
        self.assertTrue(d.state.inhibited)
        self.assertEqual(pushes, [])
        self.assertIsNotNone(d.state.last_commission_failure)
        self.assertEqual(cfg.values[(d.name, "autotune_status")], "tuned")

    def test_safety_fault_inhibits_without_snapshot(self):
        d = self._commissioned_driver()
        d.state.pre_tune_snapshot = None
        with self.assertRaises(CommandError):
            self._run_robustness(d, outcome=3, cause=6)
        self.assertTrue(d.state.inhibited)

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

    def test_workflow_finishes_for_a_refusal_that_declared_no_envelope(self):
        """A Stage-C terminal is terminal whether or not an envelope preceded it.

        A request refused before planning declares no workflow, and without this
        the wait loop has nothing to complete on and times out waiting for a plan
        that firmware will never send.
        """
        d = self._commissioned_driver()
        d.autotune.velocity_integral.done = True

        self.assertIsNone(d.autotune.velocity_integral.workflow_plan)
        self.assertTrue(d.autotune._workflow_finished())

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
    KNOWN_FIRMWARE_CODES = frozenset(range(0, 12))

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

    def test_inhibit_message_names_robustness_fault(self):
        d = make_driver()
        d.state.inhibited = True
        d.state.last_commission_failure = "robustness safety fault"
        d.state.runtime_status = "tuned"
        d.state.is_calibrated = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("robustness safety fault", str(ctx.exception))


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

    def test_tune_captures_pre_tune_snapshot_before_overwrite(self):
        d = self._ready_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        d.config.autotune_mode = None
        prior_gains = d.state.active_gains.copy()
        self._finish_tune_on_next_pause(d)
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        d.autotune.autotune(gcmd)
        snap = d.state.pre_tune_snapshot
        self.assertIsNotNone(snap)
        self.assertEqual(snap["active_gains"], prior_gains)
        self.assertEqual(snap["runtime_status"], "commissioned")
        self.assertIsNone(snap["autotune_mode"])
        self.assertNotEqual(d.state.active_gains, prior_gains)

    def test_autotune_moves_to_safe_pose_and_sends_budget(self):
        d = self._ready_driver()
        toolhead = d.printer.lookup_object("toolhead")
        toolhead._kinematics = MockCartesianKinematics([["stepper_x"], ["stepper_y"]])
        toolhead._kinematics.rails[0].get_steppers()[0]._step_dist = 0.01
        toolhead._homed_axes = "xy"
        toolhead.set_bounds(x_min=0.0, x_max=120.0, y_min=0.0, y_max=120.0)
        toolhead.set_position(x=10.0, y=20.0)
        d.printer._objects["configfile"] = MockConfigFile()
        self._finish_tune_on_next_pause(d)

        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        d.autotune.autotune(gcmd)

        gcode = d.printer.lookup_object("gcode")
        # The dispatch's own re-home then re-center; no redundant up-front move.
        self.assertEqual(
            gcode._scripts,
            ["G28 X Y", "G0 X60.000 Y60.000"],
        )
        self.assertEqual(
            d.protocol.commands.tune.last_args[-8:],
            [5000, 7500, 1, 1500, 250, 1250, 1250, 3000],
        )

    def test_accepted_with_warnings_still_reports_tuned(self):
        """A firmware AcceptedWithWarnings/warning_code result is still 'tuned'.

        tuned_conservative is no longer emitted by FOCI_AUTOTUNE: a successful
        tune (status 0 or 1) always records "tuned", regardless of a nonzero
        warning_code. tuned_conservative remains a valid persisted status only
        for backward-compatible reads of existing configs.
        """
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

        self.assertEqual(d.state.runtime_status, "tuned")

    def test_autotune_refuses_unsupported_kinematics_before_tune(self):
        d = self._ready_driver()
        toolhead = d.printer.lookup_object("toolhead")
        toolhead._kinematics = MockNoneKinematics()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("unsupported kinematics", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)

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
                }
            )
            return reactor._time

        reactor.pause = finish_tune

        d.autotune.autotune(gcmd)

        args = d.protocol.commands.tune.last_args
        self.assertIsNotNone(args)
        self.assertEqual(args[8], 1 << 5)


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

    def test_accepted_breakaway_dual_terminal_returns_candidate_outcome(self):
        """Real firmware behavior: an accepted breakaway_seeded run reaches
        its velocity-integral terminal in the SAME dispatch as the
        breakaway campaign's own acceptance terminal, both done together.
        The dispatch must surface the velocity-integral outcome (so the
        orchestrator can auto-issue stage_c_resume) and retain the request
        identity, not fall back to the generic "breakaway_campaign" marker
        that only applies when no velocity-integral terminal arrived yet."""
        d = self._commissioned_driver()
        toolhead = d.printer.lookup_object("toolhead")
        gcmd = MockGCmd({})
        d.protocol.run_tune = lambda **kw: None

        d.autotune.breakaway_campaign.done = True
        d.autotune.breakaway_campaign.accepted = True
        d.autotune.velocity_integral.outcome = "complete_candidate"
        d.autotune.velocity_integral.terminal = {"cause": 0}
        d.autotune.velocity_integral.done = True

        request_fields = {"profile_code": 1, "requested_velocity_mrev_s": 2929}
        outcome = d.autotune._run_one_dispatch(
            gcmd,
            ACTION_CODES["breakaway_seeded"],
            request_fields,
            toolhead,
            "G0 X100.000 Y100.000",
        )

        self.assertEqual(outcome, "complete_candidate")
        self.assertEqual(d.autotune._stage_b_candidate_request, request_fields)

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


class _StubVelocityIntegralResponse:
    """Minimal stand-in exposing exactly what `_format_velocity_integral_result`
    reads (`plan`, `summary`, `terminal`, `outcome`, `reproduction`), so the
    message-formatting logic can be tested without driving the full
    terminal-assembly wire protocol -- that protocol is already covered
    directly in test_velocity_integral.py."""

    def __init__(self, *, plan=None, summary=None, terminal=None, outcome=None, reproduction=None):
        self.plan = plan
        self.summary = summary
        self.terminal = terminal
        self.outcome = outcome
        self.reproduction = reproduction


class FormatVelocityIntegralResultTest(unittest.TestCase):
    def _workflow(self, terminal):
        d = make_driver()
        d.autotune.velocity_integral = _StubVelocityIntegralResponse(
            plan={"final_p": 724, "planned_velocity_mrev_s": 2929, "positive_rung_count": 12},
            summary={
                "forward_eligible_mask": 0xFFF,
                "reverse_eligible_mask": 0xFFF,
                "bookend_available_mask": 0b11,
                "current_terminus_plus_one": 0,
            },
            terminal=terminal,
            outcome="inconclusive",
        )
        return d.autotune

    def test_names_the_owner_when_sufficiency_was_reached_before_rest_rejected(self):
        workflow = self._workflow(
            {
                "outcome_name": "inconclusive",
                "outcome_namespace": "stage_c",
                "cause": 53,
                "rest_rejection_after_sufficiency": True,
                "rest_rejection_owner": "stage_c_recovery",
            }
        )

        message = workflow._format_velocity_integral_result()

        self.assertIn("sufficiency reached before rest rejected (owner=stage_c_recovery)", message)

    def test_says_nothing_extra_for_an_ordinary_partial_acquisition(self):
        workflow = self._workflow(
            {
                "outcome_name": "InconclusiveRest",
                "outcome_namespace": "stage_c",
                "cause": 53,
                "rest_rejection_after_sufficiency": False,
                "rest_rejection_owner": None,
            }
        )

        message = workflow._format_velocity_integral_result()

        self.assertNotIn("sufficiency reached before rest rejected", message)

    def test_names_a_dispatch_cause_from_the_stage_c_table(self):
        workflow = self._workflow(
            {
                "outcome_name": "Fault",
                "outcome_namespace": "stage_c",
                "cause_namespace": 2,
                "cause": 4,
            }
        )

        message = workflow._format_velocity_integral_result()

        self.assertIn("namespace=dispatch cause=4 (evidence_integrity)", message)

    def test_does_not_apply_the_dispatch_table_to_an_engine_cause_with_the_same_number(self):
        workflow = self._workflow(
            {
                "outcome_name": "Fault",
                "outcome_namespace": "stage_c",
                "cause_namespace": 0,
                "cause": 4,
            }
        )

        message = workflow._format_velocity_integral_result()

        self.assertIn("namespace=engine cause=4", message)
        self.assertNotIn("evidence_integrity", message)

    def test_does_not_apply_the_dispatch_table_to_an_error_cause_with_the_same_number(self):
        workflow = self._workflow(
            {
                "outcome_name": "Fault",
                "outcome_namespace": "stage_c",
                "cause_namespace": 1,
                "cause": 4,
            }
        )

        message = workflow._format_velocity_integral_result()

        self.assertIn("namespace=error cause=4", message)
        self.assertNotIn("evidence_integrity", message)

    def test_only_offers_stage_c_remediation_for_a_dispatch_cause(self):
        workflow = self._workflow(
            {
                "outcome_name": "Fault",
                "outcome_namespace": "stage_c",
                "cause_namespace": 0,
                "cause": 12,
            }
        )

        message = workflow._format_velocity_integral_result()

        self.assertNotIn("run a campaign first", message)
