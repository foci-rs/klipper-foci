"""Stage 2 autotune workflow for FOCI host commands."""

from __future__ import annotations

from .commissioning import (
    COMMISSION_ERROR_NAMES,
    HARD_FAULT_CODES,
    PROFILE_MAP,
    format_inner_warning_flags,
)

MODE_MAP: dict[str, int] = {
    "unloaded": 0,
    "nominal": 1,
    "high_inertia": 2,
}


class AutotuneWorkflow:
    """Run installed Stage 2 tuning after commissioning and homing."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.result: dict | None = None
        self.done = False

    def handle_tune_result(self, params: dict) -> None:
        """Handle foci_tune_result from firmware."""
        self.result = params
        self.done = True

    def resolve_inner_confidence(self) -> tuple[int, int, int, int]:
        """Resolve the four Phase 1 inner-confidence fields for Stage 2."""
        if self.driver.state.commissioned_result is not None:
            r = self.driver.state.commissioned_result
            return (
                r.get("tau_e_us", 0),
                r.get("tau_e_crosscheck_us", 0),
                r.get("tau_residual_permille", 1000),
                r.get("inner_warning_flags", 0),
            )

        config = self.driver.config

        tau_e_us = config.identified_tau_e_us
        if tau_e_us is None:
            if config.identified_lambda_us is None:
                tau_e_us = 1000
            else:
                tau_e_us = max(config.identified_lambda_us, 1000)

        tau_e_crosscheck_us = config.identified_tau_e_crosscheck_us
        if tau_e_crosscheck_us is None:
            tau_e_crosscheck_us = 0

        tau_residual_permille = config.identified_tau_residual_permille
        if tau_residual_permille is None:
            tau_residual_permille = 1000

        inner_warning_flags = config.identified_inner_warning_flags
        if inner_warning_flags is None:
            # Bit 6: host-defaulted confidence data (no fresh measurement).
            inner_warning_flags = 0x40

        return (
            tau_e_us,
            tau_e_crosscheck_us,
            tau_residual_permille,
            inner_warning_flags,
        )

    def autotune(self, gcmd) -> None:
        """Stage 2: installed tuning after commissioning and homing."""
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        mode_name = gcmd.get("MODE", "nominal").lower()
        if profile_name not in PROFILE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown profile '%s' (expected: %s)"
                % (self.driver.name, profile_name, ", ".join(sorted(PROFILE_MAP)))
            )
        if mode_name not in MODE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown mode '%s' (expected: %s)"
                % (self.driver.name, mode_name, ", ".join(sorted(MODE_MAP)))
            )

        if not self.driver.state.try_acquire():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.driver.name
            )

        try:
            if self.driver.state.inhibited:
                raise gcmd.error(
                    "FOCI %s: inhibited after failed FOCI_COMMISSION" % self.driver.name
                )
            if self.driver.state.runtime_status == "uncommissioned":
                raise gcmd.error(
                    "FOCI %s: not commissioned. Run FOCI_COMMISSION first."
                    % self.driver.name
                )
            if not self.driver.state.is_calibrated:
                raise gcmd.error(
                    "FOCI %s: not calibrated. Enable motor, re-home, then retry."
                    % self.driver.name
                )

            toolhead = self.driver.printer.lookup_object("toolhead")
            kinematics = toolhead.get_kinematics()
            if hasattr(kinematics, "rails"):
                kin_status = toolhead.get_status(toolhead.get_last_move_time())
                homed = set(kin_status.get("homed_axes", ""))
                expected = set("xyz")
                if not expected.issubset(homed):
                    missing = expected - homed
                    raise gcmd.error(
                        "FOCI %s: printer not fully homed (missing: %s). "
                        "Home first." % (self.driver.name, "".join(sorted(missing)))
                    )

            toolhead.wait_moves()

            if not self.driver.state.is_calibrated:
                raise gcmd.error(
                    "FOCI %s: calibration lost during wait" % self.driver.name
                )
            if hasattr(kinematics, "rails"):
                kin_status = toolhead.get_status(toolhead.get_last_move_time())
                if not expected.issubset(set(kin_status.get("homed_axes", ""))):
                    raise gcmd.error(
                        "FOCI %s: homing lost during wait" % self.driver.name
                    )

            self.driver.homing.invalidate_homing()

            if self.driver.state.commissioned_result is not None:
                inner_lambda = self.driver.state.commissioned_result["lambda_us"]
                theta_e = self.driver.state.commissioned_result["theta_e_us"]
                ringing = self.driver.state.commissioned_result["ringing_count"]
                bandwidth = self.driver.state.commissioned_result["bandwidth_hz"]
            else:
                config = self.driver.config
                inner_lambda = config.identified_lambda_us
                theta_e = config.identified_theta_e_us
                ringing = config.identified_ringing_count
                bandwidth = config.identified_bandwidth_hz

            (
                tau_e_us,
                tau_e_crosscheck_us,
                tau_residual_permille,
                inner_warning_flags,
            ) = self.resolve_inner_confidence()

            self.done = False
            self.result = None
            self.driver.commissioning.error_code = 0

            self.driver.protocol.run_tune(
                profile_code=PROFILE_MAP[profile_name],
                mode_code=MODE_MAP[mode_name],
                inner_lambda=inner_lambda,
                theta_e=theta_e,
                current_ringing=ringing,
                current_bw=bandwidth,
                tau_e_us=tau_e_us,
                tau_e_crosscheck_us=tau_e_crosscheck_us,
                tau_residual_permille=tau_residual_permille,
                inner_warning_flags=inner_warning_flags,
            )

            reactor = self.driver.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + 30.0
            while not self.done:
                eventtime = reactor.pause(eventtime + 0.1)
                if eventtime > timeout:
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE timed out" % self.driver.name
                    )
                if self.driver.commissioning.error_code != 0:
                    error_name = COMMISSION_ERROR_NAMES.get(
                        self.driver.commissioning.error_code,
                        "UNKNOWN(%d)" % self.driver.commissioning.error_code,
                    )
                    self.driver.commissioning.maybe_clear_calibration_for_chip_reset(
                        self.driver.commissioning.error_code
                    )
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE failed: %s"
                        % (self.driver.name, error_name)
                    )

            result = self.result
            status = result.get("status", 255)
            if status > 1:
                error_name = COMMISSION_ERROR_NAMES.get(status, "UNKNOWN(%d)" % status)
                if status == 18:
                    self.driver.commissioning.handle_chip_reset_detected()
                    stepper_enable = self.driver.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE chip reset: %s "
                        "(motor disabled by firmware)" % (self.driver.name, error_name)
                    )
                if status in HARD_FAULT_CODES:
                    self.driver.commissioning.on_commission_failure()
                    stepper_enable = self.driver.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE safety fault: %s "
                        "(motor disabled by firmware)" % (self.driver.name, error_name)
                    )
                gcmd.respond_info(
                    "FOCI %s: FOCI_AUTOTUNE failed: %s "
                    "(motor holding with entry gains)" % (self.driver.name, error_name)
                )
                return

            warning_code = result.get("warning_code", 0)
            if status == 1 or warning_code != 0:
                tune_status = "tuned_conservative"
            else:
                tune_status = "tuned"

            active_gains = self.driver.state.active_gains
            self.driver.state.active_gains = {
                "flux_p": active_gains["flux_p"],
                "flux_i": active_gains["flux_i"],
                "torque_p": active_gains["torque_p"],
                "torque_i": active_gains["torque_i"],
                "velocity_p": result["velocity_p"],
                "velocity_i": result["velocity_i"],
                "position_p": result["position_p"],
                "position_i": result["position_i"],
                "velocity_limit": result["velocity_limit"],
                "velocity_filter_hz": result["velocity_filter_hz"],
                "torque_filter_hz": result["torque_filter_hz"],
                "position_filter_hz": result["position_filter_hz"],
                "flux_filter_hz": result["flux_filter_hz"],
            }
            self.driver.state.runtime_status = tune_status

            self.persist_tune_results(result, mode_name, tune_status)

            gcmd.respond_info(
                "FOCI %s tuned (%s): vel_p=%d pos_p=%d"
                % (
                    self.driver.name,
                    tune_status,
                    result["velocity_p"],
                    result["position_p"],
                )
            )
            if inner_warning_flags:
                gcmd.respond_info(
                    "FOCI %s inner confidence: %s"
                    % (
                        self.driver.name,
                        format_inner_warning_flags(inner_warning_flags),
                    )
                )
        finally:
            self.driver.state.release()

    def persist_tune_results(self, result: dict, mode_name: str, status: str) -> None:
        """Persist Stage 2 results to printer.cfg (pending SAVE_CONFIG)."""
        configfile = self.driver.printer.lookup_object("configfile")
        configfile.set(self.driver.name, "pid_velocity_p", "%d" % result["velocity_p"])
        configfile.set(self.driver.name, "pid_velocity_i", "%d" % result["velocity_i"])
        configfile.set(
            self.driver.name,
            "pid_velocity_limit",
            "%d" % result["velocity_limit"],
        )
        configfile.set(self.driver.name, "pid_position_p", "%d" % result["position_p"])
        configfile.set(self.driver.name, "pid_position_i", "%d" % result["position_i"])
        configfile.set(
            self.driver.name,
            "velocity_filter_hz",
            "%d" % result["velocity_filter_hz"],
        )
        configfile.set(
            self.driver.name,
            "position_filter_hz",
            "%d" % result["position_filter_hz"],
        )
        configfile.set(
            self.driver.name,
            "flux_filter_hz",
            "%d" % result["flux_filter_hz"],
        )
        configfile.set(
            self.driver.name,
            "torque_filter_hz",
            "%d" % result["torque_filter_hz"],
        )
        configfile.set(self.driver.name, "identified_j_eff", "%d" % result["j_eff"])
        configfile.set(self.driver.name, "identified_b_eff", "%d" % result["b_eff"])
        configfile.set(self.driver.name, "autotune_mode", mode_name)
        configfile.set(self.driver.name, "autotune_status", status)
