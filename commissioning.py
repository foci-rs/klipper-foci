"""Commissioning workflow for FOCI host commands."""

from __future__ import annotations

from collections.abc import Sequence

PHASE_NAMES: dict[int, str] = {
    1: "ADC calibration",
    2: "Coil check",
    3: "Phase wiring",
    4: "Encoder check",
    5: "Electrical ID",
    6: "Current tune",
    7: "Current validation",
    8: "Inner done",
    9: "Mechanical ID",
    10: "Velocity tune",
    11: "Velocity validation",
    12: "Position tune",
    13: "Filter selection",
    14: "Commit",
    15: "Outer done",
    16: "Encoder alignment",
    17: "Closed-loop entry",
}

COMMISSION_ERROR_NAMES: dict[int, str] = {
    1: "motor already enabled",
    2: "no current detected",
    3: "SPI communication error",
    4: "ADC calibration fault",
    5: "coil connectivity fault",
    6: "phase wiring fault",
    7: "encoder fault",
    8: "electrical identification failed",
    9: "current validation failed",
    10: "mechanical identification failed",
    11: "velocity validation failed",
    12: "position tune failed",
    13: "encoder not aligned",
    14: "shutdown requested",
    15: "commissioning already running",
    16: "command queue full",
    17: "safety envelope violation",
    18: "CHIP_RESET_DETECTED (TMC4671 lost state, re-commission required)",
    19: "resistance identification failed",
    20: "resistance ADC not ready",
    21: "resistance diagnostic not armed",
    22: "resistance wrong power stage",
    23: "resistance insufficient linear points",
    24: "resistance thermal drift",
    25: "resistance electrical axis mismatch",
    26: "resistance high fit residual",
    27: "resistance invalid motor type",
    28: "resistance peak current exceeded",
    29: "resistance unsupported profile",
    30: "resistance parameter out of bounds",
    31: "resistance measurement envelope unsupported",
    32: "inductance open-loop velocity timeout",
    33: "inductance AC capture rejected",
    34: "inductance encoder motion during AC capture",
    35: "inductance capture window incomplete",
    36: "inductance realized frequency out of range",
    37: "inductance quadrature current too low",
    38: "inductance missing resistance evidence",
    39: "inductance reactance calculation invalid",
    40: "inductance drift calculation invalid",
    41: "inductance saliency calculation invalid",
    42: "sustained hold validation failed",
}

# Error codes for which the failure message should point at a dedicated
# troubleshooting doc instead of just the bare error name.
TROUBLESHOOTING_DOC_LINKS: dict[int, str] = {
    code: "docs/troubleshooting/resistance-identification.md" for code in range(19, 32)
}

# Resistance-identification failures that are not operator-remediable by
# changing a printer setting. The firmware could not find a safe resistance
# measurement envelope, or a safety backstop rejected the envelope it tried.
RESISTANCE_MEASUREMENT_UNSUPPORTED_CODES: frozenset[int] = frozenset({23, 28, 31})

# Error codes that indicate a hard-disable fault: firmware has disabled the
# motor and cleared its state. The host must sync its enable line and clear
# is_calibrated.
HARD_FAULT_CODES: frozenset[int] = frozenset({3, 9, 14, 17, 42})

# Bit-to-name mapping for the firmware-side `inner_warning_flags` bitfield.
INNER_WARNING_FLAG_NAMES: list[tuple[int, str]] = [
    (1 << 0, "coil R mismatch"),
    (1 << 1, "coil control-model tau mismatch"),
    (1 << 3, "theta/tau ratio"),
    (1 << 5, "current gains fell back to defaults"),
    (1 << 6, "host-default confidence (no fresh measurement)"),
]

PROFILE_MAP: dict[str, int] = {
    "conservative": 0,
    "balanced": 1,
    "stiff": 2,
}

ELECTRICAL_ID_DETAIL_NAMES: dict[int, str] = {
    1: "excitation",
    2: "coil A resistance",
    3: "coil B resistance",
    20: "no usable per-coil samples",
    21: "only one coil produced non-zero control-model tau",
    22: "model scale rounded to zero",
    23: "resistance below short threshold",
    24: "resistance above open threshold",
    25: "coil resistance mismatch",
    26: "coil control-model tau mismatch",
    28: "legacy inductance fit rejected",
    29: "transport delay too large",
    30: "legacy inductance fit point",
    31: "legacy inductance fit correction",
    32: "inductance frequency out of range",
    33: "inductance AC capture rejected",
}

INDUCTANCE_CAPTURE_REJECT_REASON_NAMES: dict[int, str] = {
    1: "phi interval invalid",
    2: "zero phi delta",
    3: "frame accumulator",
    4: "saliency accumulator",
    5: "first-half accumulator",
    6: "second-half accumulator",
    7: "elapsed interpolation",
    8: "saliency bracket invariant",
}


def _decode_coil_point(packed: int) -> tuple[str, int]:
    coil = "A" if ((packed >> 4) & 0xF) == 0 else "B"
    point = packed & 0xF
    return coil, point


def _signed_u32(value: int) -> int:
    return value if value < 0x8000_0000 else value - 0x1_0000_0000


def _signed_u16(value: int) -> int:
    value &= 0xFFFF
    return value if value < 0x8000 else value - 0x1_0000


def _decode_u16_pair(packed: int) -> tuple[int, int]:
    return (packed >> 16) & 0xFFFF, packed & 0xFFFF


def _decode_i16_pair(packed: int) -> tuple[int, int]:
    high, low = _decode_u16_pair(packed)
    return _signed_u16(high), _signed_u16(low)


def format_commission_detail(detail: dict) -> str:
    """Format one structured commissioning diagnostic detail."""
    phase_name = PHASE_NAMES.get(detail["phase"], "Phase %d" % detail["phase"])
    code = detail["code"]
    name = ELECTRICAL_ID_DETAIL_NAMES.get(code, "diagnostic %d" % code)
    value0 = detail["value0"]
    value1 = detail["value1"]
    value2 = detail["value2"]
    if detail["phase"] == 2 and code in (1, 2):
        coil = "A" if code == 1 else "B"
        expected = value0 if value0 < 0x8000 else value0 - 0x10000
        other = value1 if value1 < 0x8000 else value1 - 0x10000
        status = "FAIL" if detail["status"] else "PASS"
        return (
            "%s: coil %s sample %s "
            "(expected=%d counts, other=%d counts, raw=0x%08x)"
            % (phase_name, coil, status, expected, other, value2)
        )
    if code == 1:
        return (
            "%s: %s (voltage_count=%d, legacy_didt_cycles=%d, sample_period=%dus)"
            % (
                phase_name,
                name,
                value0,
                value1,
                value2,
            )
        )
    if code in (2, 3):
        return "%s: %s (avg_current=%d counts, r_count_milli=%d, samples=%d)" % (
            phase_name,
            name,
            value0,
            value1,
            value2,
        )
    if code in (25, 26):
        return "%s: %s (%d permille, limit=%d)" % (
            phase_name,
            name,
            value0,
            value1,
        )
    if code == 28:
        coil = "A" if value0 == 0 else "B"
        return "%s: %s (coil=%s, usable_points=%d, selected_mask=0x%04x)" % (
            phase_name,
            name,
            coil,
            value1,
            value2,
        )
    if code == 30:
        coil, point = _decode_coil_point(value0)
        return "%s: %s (coil=%s point=%d, ud=%d, avg_delta=%d counts)" % (
            phase_name,
            name,
            coil,
            point,
            value1,
            value2,
        )
    if code == 31:
        coil, point = _decode_coil_point(value0)
        return "%s: %s (coil=%s point=%d, samples=%d, effective_ud=%d)" % (
            phase_name,
            name,
            coil,
            point,
            value1,
            _signed_u32(value2),
        )
    if code == 32:
        return "%s: %s (realized_frequency_millihz=%d, elapsed_us=%d, samples=%d)" % (
            phase_name,
            name,
            value0,
            value1,
            value2,
        )
    if code == 33:
        reason = INDUCTANCE_CAPTURE_REJECT_REASON_NAMES.get(
            value0, "reason %d" % value0
        )
        if value0 in (1, 2):
            previous_phi, current_phi = _decode_u16_pair(value2)
            return "%s: %s (reason=%s, samples=%d, previous_phi=%d, current_phi=%d)" % (
                phase_name,
                name,
                reason,
                value1,
                previous_phi,
                current_phi,
            )
        if value0 in (3, 4, 5, 6):
            id_count, iq_count = _decode_i16_pair(value2)
            return "%s: %s (reason=%s, samples=%d, id=%d, iq=%d)" % (
                phase_name,
                name,
                reason,
                value1,
                id_count,
                iq_count,
            )
        if value0 == 7:
            previous_elapsed_us, current_elapsed_us = _decode_u16_pair(value2)
            return (
                "%s: %s (reason=%s, samples=%d, "
                "previous_elapsed_us=%d, current_elapsed_us=%d)"
                % (
                    phase_name,
                    name,
                    reason,
                    value1,
                    previous_elapsed_us,
                    current_elapsed_us,
                )
            )
        if value0 == 8:
            x_d, x_q = _decode_u16_pair(value2)
            return "%s: %s (reason=%s, samples=%d, x_d=%d, x_q=%d)" % (
                phase_name,
                name,
                reason,
                value1,
                x_d,
                x_q,
            )
        return "%s: %s (reason=%s, samples=%d, aux=%d)" % (
            phase_name,
            name,
            reason,
            value1,
            value2,
        )
    if code in (23, 24):
        return "%s: %s (r_count_milli=%d, limit=%d)" % (
            phase_name,
            name,
            value0,
            value1,
        )
    if code == 22:
        return "%s: %s (l_int=%d, control_l_count_micro=%d)" % (
            phase_name,
            name,
            value0,
            value1,
        )
    if code == 29:
        return "%s: %s (theta_us=%d, tau_us=%d)" % (
            phase_name,
            name,
            value0,
            value1,
        )
    if value0 or value1 or value2:
        return "%s: %s (value0=%d, value1=%d, value2=%d)" % (
            phase_name,
            name,
            value0,
            value1,
            value2,
        )
    return "%s: %s" % (phase_name, name)


def format_inner_warning_flags(flags: int) -> str:
    """Decode an inner_warning_flags bitfield into warning names."""
    names = [name for bit, name in INNER_WARNING_FLAG_NAMES if flags & bit]
    return ", ".join(names) if names else "none"


def format_commission_error_name(code: int) -> str:
    """Render a commission status code's name, with a doc link if one exists."""
    detail_name = format_commission_error_detail_name(code)
    if code in RESISTANCE_MEASUREMENT_UNSUPPORTED_CODES:
        error_name = (
            "resistance measurement unsupported by current firmware"
            " (detail: %s)" % detail_name
        )
    else:
        error_name = detail_name
    doc_link = TROUBLESHOOTING_DOC_LINKS.get(code)
    if doc_link is not None:
        return "%s (see %s)" % (error_name, doc_link)
    return error_name


def format_commission_error_detail_name(code: int) -> str:
    """Render the precise firmware status code name without operator grouping."""
    return COMMISSION_ERROR_NAMES.get(code, "UNKNOWN(%d)" % code)


class CommissioningWorkflow:
    """Run Stage 1 commissioning and track commissioning responses."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.last_phase_id: int | None = None
        self.result: dict | None = None
        self.done = False
        self.error_code = 0
        self.details: list[dict] = []

    def clear_details(self) -> None:
        """Clear structured commissioning diagnostic details."""
        self.details = []

    def handle_commission_phase(self, params: dict) -> None:
        """Handle foci_commission_phase messages from firmware."""
        phase_id = params.get("phase", 0)
        status = params.get("status", 0)
        if phase_id > 0 and status == 0:
            self.last_phase_id = phase_id
            phase_name = PHASE_NAMES.get(phase_id, "Phase %d" % phase_id)
            gcode = self.driver.printer.lookup_object("gcode")
            gcode.respond_info(
                "FOCI %s autotune: %s" % (self.driver.stepper_name, phase_name)
            )
        elif phase_id == 0 and status != 0:
            self.error_code = status

    def handle_commission_result(self, params: dict) -> None:
        """Handle foci_commission_result from firmware."""
        self.result = params
        self.done = True

    def handle_commission_detail(self, params: dict) -> None:
        """Collect structured commissioning diagnostic detail."""
        self.details.append(
            {
                "phase": params["phase"],
                "code": params["code"],
                "status": params["status"],
                "value0": params["value0"],
                "value1": params["value1"],
                "value2": params["value2"],
            }
        )

    def commission(self, gcmd) -> None:
        """Stage 1: commission motor for safe printer motion."""
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        if profile_name not in PROFILE_MAP:
            raise gcmd.error(
                "Unknown profile '%s'. Options: %s"
                % (profile_name, ", ".join(PROFILE_MAP.keys()))
            )
        profile_code = PROFILE_MAP[profile_name]

        if not self.driver.state.try_acquire():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.driver.name
            )
        try:
            toolhead = self.driver.printer.lookup_object("toolhead")
            toolhead.wait_moves()

            stepper_enable = self.driver.printer.lookup_object("stepper_enable")
            enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
            if enable_line.is_motor_enabled():
                enable_line.motor_disable(toolhead.get_last_move_time())

            self.driver.state.is_calibrated = False
            self.driver.homing.invalidate_homing()

            self.done = False
            self.result = None
            self.error_code = 0
            self.last_phase_id = None
            self.clear_details()

            # Clear any resistance-reply cache left over from a standalone
            # FOCI_RESISTANCE_TEST run before this commission's firmware
            # stream can emit its own foci_resistance_run/axis replies.
            # The cache is otherwise only cleared at commission exit
            # (success via pop_resistance_cache, failure/timeout via
            # clear_resistance_cache below), so without this start-of-run
            # clear a full standalone run+axis0+axis1 entry could survive
            # to pre-populate this commission's cache. If this commission
            # then delivered only a partial set of replies (e.g. run+axis0,
            # axis1 dropped), handle_resistance_axis would overwrite only
            # the received axis, leaving the stale axis1 in place; the
            # all-or-nothing pop_resistance_cache would see run+axis0+
            # axis1 all "present" (axis1 stale) and fold/persist a result
            # blending data from two unrelated runs.
            self.driver.diagnostics.clear_resistance_cache(self.driver.oid)
            self.driver.diagnostics.active.clear_inductance_cache(self.driver.oid)
            self.driver.diagnostics.active.clear_current_loop_cache(self.driver.oid)
            self.driver.diagnostics.active.clear_last_encoder_alignment_evidence(
                self.driver.oid
            )

            self.driver.protocol.run_commission(profile_code)

            reactor = self.driver.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + 30.0
            while not self.done:
                eventtime = reactor.pause(eventtime + 0.1)
                if eventtime > timeout:
                    self.on_commission_failure()
                    self.driver.diagnostics.clear_resistance_cache(self.driver.oid)
                    self.driver.diagnostics.active.clear_inductance_cache(
                        self.driver.oid
                    )
                    self.driver.diagnostics.active.clear_current_loop_cache(
                        self.driver.oid
                    )
                    raise gcmd.error(
                        "FOCI %s: FOCI_COMMISSION timed out" % self.driver.name
                    )
                if self.error_code != 0:
                    error_name = format_commission_error_name(self.error_code)
                    if self.error_code == 18:
                        self.handle_chip_reset_detected()
                    else:
                        self.on_commission_failure()
                    self.driver.diagnostics.clear_resistance_cache(self.driver.oid)
                    self.driver.diagnostics.active.clear_inductance_cache(
                        self.driver.oid
                    )
                    self.driver.diagnostics.active.clear_current_loop_cache(
                        self.driver.oid
                    )
                    phase_name = PHASE_NAMES.get(self.last_phase_id or 0, "unknown")
                    if self.details:
                        detail_lines = [
                            "FOCI %s commissioning diagnostics:"
                            % self.driver.stepper_name
                        ]
                        detail_lines.extend(
                            "  %s" % format_commission_detail(detail)
                            for detail in self.details
                        )
                        gcmd.respond_info("\n".join(detail_lines))
                    raise gcmd.error(
                        "FOCI %s: FOCI_COMMISSION failed at %s: %s"
                        % (self.driver.name, phase_name, error_name)
                    )

            result = self.result
            # W1 firmware emits foci_resistance_run + two
            # foci_resistance_axis replies during FOCI_COMMISSION, just
            # before foci_commission_result. The diagnostics handlers
            # cache those reply values (keyed by oid); fold them into the
            # result dict now so persist_commission_results' presence-gated
            # resistance block sees them below. pop_resistance_cache always
            # clears the per-oid cache entry here, and is all-or-nothing:
            # it only returns folded values when run + axis0 + axis1 are
            # all cached, so a commission that completed before every
            # resistance reply arrived folds in nothing rather than a
            # partial set. The two early-exit failure paths above
            # (timeout, mid-phase error) clear the cache directly via
            # clear_resistance_cache since they return before reaching
            # here; together these guarantee no stale or partial
            # resistance cache entry ever survives past this method.
            result.update(self.driver.diagnostics.pop_resistance_cache(self.driver.oid))
            result.update(
                self.driver.diagnostics.active.pop_inductance_cache(self.driver.oid)
            )
            result.update(
                self.driver.diagnostics.active.pop_current_loop_cache(self.driver.oid)
            )
            status = result.get("status", 255)
            if status > 1:
                error_name = format_commission_error_name(status)
                if status == 18:
                    self.handle_chip_reset_detected()
                else:
                    self.on_commission_failure()
                raise gcmd.error(
                    "FOCI %s: FOCI_COMMISSION failed: %s"
                    % (self.driver.name, error_name)
                )

            self.driver.state.is_calibrated = True
            self.driver.state.inhibited = False
            self.driver.homing.set_auto_calibrate_on_enable_allowed(True)
            self.driver.state.commissioned_result = result
            self.driver.state.active_gains = {
                "flux_p": result["flux_p"],
                "flux_i": result["flux_i"],
                "torque_p": result["torque_p"],
                "torque_i": result["torque_i"],
                "velocity_p": result["fallback_velocity_p"],
                "velocity_i": result["fallback_velocity_i"],
                "position_p": result["fallback_position_p"],
                "position_i": result["fallback_position_i"],
                "velocity_limit": result["fallback_velocity_limit"],
                "velocity_filter_hz": self.driver.settings.velocity_filter_hz,
                "torque_filter_hz": self.driver.settings.torque_filter_hz,
                "position_filter_hz": self.driver.settings.position_filter_hz,
                "flux_filter_hz": self.driver.settings.flux_filter_hz,
            }
            self.driver.state.runtime_status = "commissioned"
            enable_line.motor_enable(toolhead.get_last_move_time())

            self.persist_commission_results(result, profile_name)

            status_str = "accepted" if status == 0 else "accepted with warnings"
            gcmd.respond_info(
                "FOCI %s commissioned (%s): "
                "r_count_milli=%d control_l_count_micro=%d R_int=%d L_int=%d"
                % (
                    self.driver.name,
                    status_str,
                    result["r_mohm"],
                    result["l_uh"],
                    result.get("r_int", 0),
                    result.get("l_int", 0),
                )
            )
            flags = result.get("inner_warning_flags", 0)
            if flags:
                gcmd.respond_info(
                    "FOCI %s inner confidence: %s"
                    % (self.driver.name, format_inner_warning_flags(flags))
                )
        finally:
            self.driver.state.release()

    def on_commission_failure(self) -> None:
        """Handle Stage 1 failure state transitions."""
        self.driver.state.is_calibrated = False
        self.driver.state.commissioned_result = None
        self.driver.state.active_gains = None
        self.driver.state.runtime_status = "uncommissioned"
        self.driver.state.inhibited = True
        self.driver.homing.set_auto_calibrate_on_enable_allowed(False)

    def handle_chip_reset_detected(self) -> None:
        """Clear calibration after firmware reports chip reset without inhibiting."""
        self.driver.state.is_calibrated = False
        self.driver.state.inhibited = False
        self.driver.homing.set_auto_calibrate_on_enable_allowed(True)

    def maybe_clear_calibration_for_chip_reset(self, status: int) -> None:
        """Apply chip-reset recovery for CommissionError status 18."""
        if status == 18:
            self.handle_chip_reset_detected()

    def persist_commission_results(self, result: dict, profile_name: str) -> None:
        """Persist Stage 1 results to printer.cfg pending SAVE_CONFIG."""
        configfile = self.driver.printer.lookup_object("configfile")
        configfile.set(self.driver.name, "pid_flux_p", "%d" % result["flux_p"])
        configfile.set(self.driver.name, "pid_flux_i", "%d" % result["flux_i"])
        configfile.set(self.driver.name, "pid_torque_p", "%d" % result["torque_p"])
        configfile.set(self.driver.name, "pid_torque_i", "%d" % result["torque_i"])
        configfile.set(
            self.driver.name,
            "commissioned_velocity_p",
            "%d" % result["fallback_velocity_p"],
        )
        configfile.set(
            self.driver.name,
            "commissioned_velocity_i",
            "%d" % result["fallback_velocity_i"],
        )
        configfile.set(
            self.driver.name,
            "commissioned_position_p",
            "%d" % result["fallback_position_p"],
        )
        configfile.set(
            self.driver.name,
            "commissioned_position_i",
            "%d" % result["fallback_position_i"],
        )
        configfile.set(
            self.driver.name,
            "commissioned_velocity_limit",
            "%d" % result["fallback_velocity_limit"],
        )
        configfile.set(
            self.driver.name,
            "identified_r_count_milli",
            "%d" % result["r_mohm"],
        )
        configfile.set(
            self.driver.name,
            "identified_l_count_micro",
            "%d" % result["l_uh"],
        )
        configfile.set(
            self.driver.name,
            "identified_r_int",
            "%d" % result.get("r_int", 0),
        )
        configfile.set(
            self.driver.name,
            "identified_l_int",
            "%d" % result.get("l_int", 0),
        )
        configfile.set(
            self.driver.name, "identified_lambda_us", "%d" % result["lambda_us"]
        )
        configfile.set(
            self.driver.name,
            "identified_theta_e_us",
            "%d" % result["theta_e_us"],
        )
        configfile.set(
            self.driver.name,
            "identified_ringing_count",
            "%d" % result["ringing_count"],
        )
        configfile.set(
            self.driver.name,
            "identified_bandwidth_hz",
            "%d" % result["bandwidth_hz"],
        )
        configfile.set(
            self.driver.name,
            "identified_tau_e_us",
            "%d" % result.get("tau_e_us", 0),
        )
        configfile.set(
            self.driver.name,
            "identified_inner_warning_flags",
            "%d" % result.get("inner_warning_flags", 0),
        )
        self._persist_resistance_identification(configfile, result)
        self._persist_inductance_identification(configfile, result)
        self._persist_current_loop_identification(configfile, result)
        configfile.set(self.driver.name, "autotune_profile", profile_name)
        configfile.set(self.driver.name, "autotune_status", "commissioned")

    # Maps each firmware-reported resistance-identification result key to
    # the persisted config key. All values are firmware-owned: the host
    # neither fits, selects points, nor evaluates quality gates here, it
    # only stores what firmware already decided. The
    # `foci_commission_result` wire reply does not carry these fields yet
    # (tracked separately); `persist_commission_results` skips this group
    # entirely when firmware has not reported it, rather than persist
    # fabricated zeros.
    RESISTANCE_RESULT_KEYS: tuple[tuple[str, str], ...] = (
        ("resistance_selected_count_slope_milli", "identified_r_count_slope_milli"),
        (
            "resistance_gain_path_count_slope_milli",
            "identified_r_gain_path_count_slope_milli",
        ),
        (
            "resistance_axis0_count_slope_milli",
            "identified_r_axis0_count_slope_milli",
        ),
        (
            "resistance_axis1_count_slope_milli",
            "identified_r_axis1_count_slope_milli",
        ),
        (
            "resistance_axis0_intercept_count",
            "identified_r_axis0_intercept_count",
        ),
        (
            "resistance_axis1_intercept_count",
            "identified_r_axis1_intercept_count",
        ),
        ("resistance_axis0_rmse_permille", "identified_r_axis0_rmse_permille"),
        ("resistance_axis1_rmse_permille", "identified_r_axis1_rmse_permille"),
        (
            "resistance_selected_mask_axis0",
            "identified_r_selected_mask_axis0",
        ),
        (
            "resistance_selected_mask_axis1",
            "identified_r_selected_mask_axis1",
        ),
        (
            "resistance_axis0_signed_count_slope_milli",
            "identified_r_axis0_signed_count_slope_milli",
        ),
        (
            "resistance_axis1_signed_count_slope_milli",
            "identified_r_axis1_signed_count_slope_milli",
        ),
        (
            "resistance_axis0_signed_asymmetry_permille",
            "identified_r_axis0_signed_asymmetry_permille",
        ),
        (
            "resistance_axis1_signed_asymmetry_permille",
            "identified_r_axis1_signed_asymmetry_permille",
        ),
        ("resistance_axis0_drift_permille", "identified_r_axis0_drift_permille"),
        ("resistance_axis1_drift_permille", "identified_r_axis1_drift_permille"),
        ("resistance_status_flags_or", "identified_r_status_flags_or"),
        ("resistance_warning_flags", "identified_r_warning_flags"),
    )

    def _persist_resistance_identification(self, configfile, result: dict) -> None:
        """Persist firmware-owned resistance-identification evidence.

        Every value here is reported by firmware as-is: the selected
        count-space slope, the slope actually consumed by the gain path,
        per-axis fit evidence, point-selection masks, signed-anchor
        evidence, thermal-drift evidence, and warning/status flags. The
        host performs no fitting, point selection, or quality-gate
        evaluation; it only stores what firmware already decided.

        Skips this group entirely when ``result`` does not contain these
        keys, so commissioning against older firmware that has not yet
        added these fields to its reply still persists cleanly.
        """
        if "resistance_selected_count_slope_milli" not in result:
            return
        for result_key, config_key in self.RESISTANCE_RESULT_KEYS:
            configfile.set(self.driver.name, config_key, "%d" % result[result_key])

    INDUCTANCE_RESULT_KEYS: Sequence[tuple[str, str]] = (
        ("inductance_source", "identified_l_source"),
        ("inductance_warning_flags", "identified_l_warning_flags"),
        ("inductance_frequency_millihz", "identified_l_frequency_millihz"),
        (
            "inductance_reactance_count_ratio_milli",
            "identified_l_reactance_count_ratio_milli",
        ),
        (
            "inductance_d_reactance_count_ratio_milli",
            "identified_l_d_reactance_count_ratio_milli",
        ),
        (
            "inductance_q_reactance_count_ratio_milli",
            "identified_l_q_reactance_count_ratio_milli",
        ),
        ("inductance_saliency_status", "identified_l_saliency_status"),
        ("inductance_saliency_permille", "identified_l_saliency_permille"),
        ("inductance_iq_mean_milli_count", "identified_l_iq_mean_milli_count"),
        ("inductance_drift_permille", "identified_l_drift_permille"),
        (
            "inductance_r_shift_minus_permille",
            "identified_l_r_shift_minus_permille",
        ),
        (
            "inductance_r_shift_plus_permille",
            "identified_l_r_shift_plus_permille",
        ),
        (
            "inductance_x_mag_vs_quad_permille",
            "identified_l_x_mag_vs_quad_permille",
        ),
    )

    def _persist_inductance_identification(self, configfile, result: dict) -> None:
        """Persist firmware-owned production inductance evidence."""
        if "inductance_reactance_count_ratio_milli" not in result:
            return
        for result_key, config_key in self.INDUCTANCE_RESULT_KEYS:
            configfile.set(self.driver.name, config_key, "%d" % result[result_key])

    CURRENT_LOOP_RESULT_KEYS: tuple[tuple[str, str], ...] = (
        ("current_gains_source", "identified_current_gains_source"),
        (
            "current_candidate_gains_source",
            "identified_current_candidate_gains_source",
        ),
        ("current_axis_split_source", "identified_axis_split_source"),
        (
            "current_candidate_axis_split_source",
            "identified_current_candidate_axis_split_source",
        ),
        ("current_gains_tier", "identified_current_gains_tier"),
        (
            "current_candidate_gains_tier",
            "identified_current_candidate_gains_tier",
        ),
        (
            "current_measured_axis_split_permille",
            "identified_current_measured_axis_split_permille",
        ),
        (
            "current_candidate_measured_axis_split_permille",
            "identified_current_candidate_measured_axis_split_permille",
        ),
        (
            "current_applied_axis_split_permille",
            "identified_current_applied_axis_split_permille",
        ),
        (
            "current_candidate_applied_axis_split_permille",
            "identified_current_candidate_applied_axis_split_permille",
        ),
        ("current_axis_split_clamped", "identified_current_axis_split_clamped"),
        (
            "current_candidate_axis_split_clamped",
            "identified_current_candidate_axis_split_clamped",
        ),
        ("current_candidate_flux_p", "identified_current_candidate_flux_p"),
        ("current_candidate_flux_i", "identified_current_candidate_flux_i"),
        ("current_candidate_torque_p", "identified_current_candidate_torque_p"),
        ("current_candidate_torque_i", "identified_current_candidate_torque_i"),
        ("current_candidate_attempt", "identified_current_candidate_attempt"),
        ("current_validation_axes", "identified_current_validation_axes"),
        (
            "current_flux_validation_sample_count",
            "identified_current_flux_validation_sample_count",
        ),
        (
            "current_torque_validation_sample_count",
            "identified_current_torque_validation_sample_count",
        ),
        (
            "current_retry_budget_exhausted",
            "identified_current_retry_budget_exhausted",
        ),
        ("current_failure_reason", "identified_current_failure_reason"),
        (
            "current_flux_response_min_permille",
            "identified_current_flux_response_min_permille",
        ),
        (
            "current_torque_response_min_permille",
            "identified_current_torque_response_min_permille",
        ),
        (
            "current_flux_encoder_delta_counts",
            "identified_current_flux_encoder_delta_counts",
        ),
        (
            "current_torque_encoder_delta_counts",
            "identified_current_torque_encoder_delta_counts",
        ),
    )

    def _persist_current_loop_identification(self, configfile, result: dict) -> None:
        """Persist firmware-owned current-loop commissioning evidence."""
        if "current_gains_source" not in result:
            return
        for result_key, config_key in self.CURRENT_LOOP_RESULT_KEYS:
            configfile.set(self.driver.name, config_key, "%d" % result[result_key])
