"""Active FOCI diagnostic commands and response handlers."""

from __future__ import annotations

from ..constants import MIN_OPERATIONAL_VOLTAGE_LIMIT


class ActiveDiagnostics:
    """Own FOCI diagnostics that deliberately excite hardware."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.current_torque_sample_details: dict[tuple[int, int, int, int], dict] = {}
        self.current_torque_sample_labels: dict[tuple[int, int, int, int], str] = {}
        # Transient per-driver cache of the commission-stream resistance
        # replies (foci_resistance_run + the two foci_resistance_axis
        # replies), keyed by oid. Populated by handle_resistance_run and
        # handle_resistance_axis below; folded into the commission result
        # dict on commission success by CommissioningWorkflow.commission()
        # via pop_resistance_cache(), which only returns a non-empty dict
        # when all three replies (run, axis0, axis1) are present — a
        # partial set folds in nothing, so persist_commission_results'
        # presence-gated resistance block either persists a complete set
        # of identified_r_* keys or none at all. The cache entry for an
        # oid is unconditionally cleared at every commission exit
        # (success via pop_resistance_cache, failure/timeout via
        # clear_resistance_cache), so a failed or partial run can never
        # leak stale values into a later commission's fold.
        # A standalone FOCI_RESISTANCE_TEST run populates this cache too,
        # but nothing ever folds it in unless a commission completes
        # afterward, so standalone runs leave no persisted trace; a
        # stale entry from a diagnostic run is simply overwritten by the
        # next run.
        self.resistance_cache: dict[int, dict] = {}

    def handle_current_step_result(self, params: dict) -> None:
        """Handle foci_current_step_result from firmware."""
        msg = (
            "FOCI %s current step: status=%d target=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.driver.name,
                params["status"],
                params["target"],
                params["torque_during"],
                params["torque_before"],
                params["torque_after"],
                params["flux_during"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_vector_step_result(self, params: dict) -> None:
        """Handle foci_current_vector_step_result from firmware."""
        msg = (
            "FOCI %s current vector step: status=%d"
            " torque_target=%d flux_target=%d"
            " actual_torque=%d actual_flux=%d"
            " before=%d after=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.driver.name,
                params["status"],
                params["torque_target"],
                params["flux_target"],
                params["torque_during"],
                params["flux_during"],
                params["torque_before"],
                params["torque_after"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_torque_sample_result(self, params: dict) -> None:
        """Handle foci_current_torque_sample_result from firmware."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        detail = self.current_torque_sample_details.pop(detail_key, {})
        label = self.current_torque_sample_labels.pop(
            detail_key, "current torque sample"
        )
        msg = (
            "FOCI %s %s: status=%d"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " pidin_target_torque=%d pidin_target_flux=%d"
            " pidout_target_torque=%d pidout_target_flux=%d"
            " pid_torque_target_monitor=%d"
            " torque_error=%d flux_error=%d"
            " torque_error_sum=%d flux_error_sum=%d"
            " uq_prelimit=%d ud_prelimit=%d"
            " ff_velocity=%d ff_torque=%d"
            " status_flags=0x%08x"
            % (
                self.driver.name,
                label,
                params["status"],
                params["target"],
                params.get("flux_target", 0),
                params["sample_delay_ms"],
                params["voltage_limit"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params.get("pidin_target_torque", 0),
                params.get("pidin_target_flux", 0),
                params.get("pidout_target_torque", 0),
                params.get("pidout_target_flux", 0),
                params.get("pid_torque_target_monitor", 0),
                detail.get("torque_error", 0),
                detail.get("flux_error", 0),
                detail.get("torque_error_sum", 0),
                detail.get("flux_error_sum", 0),
                detail.get("uq_prelimit", 0),
                detail.get("ud_prelimit", 0),
                detail.get("ff_velocity", 0),
                detail.get("ff_torque", 0),
                params.get("status_flags", 0),
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_torque_sample_detail_result(self, params: dict) -> None:
        """Cache split current torque sample details until the base reply arrives."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        self.current_torque_sample_details[detail_key] = params

    def handle_voltage_step_result(self, params: dict) -> None:
        """Handle foci_voltage_step_result from firmware."""
        msg = (
            "FOCI %s voltage step: status=%d"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " uux_sample=%d uwy_sample=%d"
            " pwm_ux_sample=%d pwm_wy_sample=%d"
            " pwm_sv_chop=0x%08x pwm_bbm=0x%08x pwm_maxcnt=%d"
            " phi_e_sample=%d phi_m_sample=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " status_flags=0x%08x"
            % (
                self.driver.name,
                params["status"],
                params["uq_ext"],
                params["ud_ext"],
                params["sample_delay_ms"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["uux_sample"],
                params["uwy_sample"],
                params["pwm_ux_sample"],
                params["pwm_wy_sample"],
                params["pwm_sv_chop"],
                params["pwm_bbm"],
                params["pwm_maxcnt"],
                params["phi_e_sample"],
                params["phi_m_sample"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params["status_flags"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def current_step_test(self, gcmd) -> None:
        """Run a bounded current-loop step diagnostic."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.driver.protocol.run_current_step_test(
            target=target,
            duration_ms=duration_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            "FOCI %s current-step requested: target=%d"
            " duration_ms=%d voltage_limit=%d"
            % (self.driver.name, target, duration_ms, voltage_limit)
        )

    def current_vector_step_test(self, gcmd) -> None:
        """Run a bounded current-vector step diagnostic."""
        torque_target = gcmd.get_int("TORQUE_TARGET", 0, minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.driver.protocol.run_current_vector_step_test(
            torque_target=torque_target,
            flux_target=flux_target,
            duration_ms=duration_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            "FOCI %s current-vector-step requested:"
            " torque_target=%d flux_target=%d duration_ms=%d voltage_limit=%d"
            % (
                self.driver.name,
                torque_target,
                flux_target,
                duration_ms,
                voltage_limit,
            )
        )

    def current_torque_sample_test(self, gcmd) -> None:
        """Run a bounded torque pulse and sample it before the dwell floor."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 5, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        self.current_torque_sample_details.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )
        self.current_torque_sample_labels.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )

        self.driver.protocol.run_current_torque_sample_test(
            target=target,
            flux_target=flux_target,
            sample_delay_ms=sample_delay_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            "FOCI %s current-torque-sample requested:"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d"
            % (
                self.driver.name,
                target,
                flux_target,
                sample_delay_ms,
                voltage_limit,
            )
        )

    def position_torque_offset_test(self, gcmd) -> None:
        """Run a bounded torque-offset sample while staying in position mode."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        detail_key = (target, 0, sample_delay_ms, voltage_limit)
        self.current_torque_sample_details.pop(detail_key, None)
        self.current_torque_sample_labels[detail_key] = "position torque offset sample"

        self.driver.protocol.run_position_torque_offset_sample_test(
            target=target,
            sample_delay_ms=sample_delay_ms,
            voltage_limit=voltage_limit,
        )

        gcmd.respond_info(
            "FOCI %s position-torque-offset requested:"
            " target=%d sample_delay_ms=%d voltage_limit=%d"
            % (self.driver.name, target, sample_delay_ms, voltage_limit)
        )

    def handle_resistance_profile(self, params: dict) -> None:
        """Handle foci_resistance_profile from firmware.

        Displays board/profile constants used by the resistance sweep
        exactly as reported. The host performs no interpretation.
        """
        msg = (
            "FOCI %s resistance profile: profile_version=%d"
            " pwm_maxcnt=%d bbm_h=%d bbm_l=%d"
            " dsadc_mdec_a=%d dsadc_mdec_b=%d"
            " linear_current_threshold_count=%d encoder_move_warn_counts=%d"
            " status_flags_warn_mask=0x%08x scale_metadata_validated=%d"
            % (
                self.driver.name,
                params["profile_version"],
                params["pwm_maxcnt"],
                params["bbm_h"],
                params["bbm_l"],
                params["dsadc_mdec_a"],
                params["dsadc_mdec_b"],
                params["linear_current_threshold_count"],
                params["encoder_move_warn_counts"],
                params["status_flags_warn_mask"],
                params["scale_metadata_validated"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_resistance_run(self, params: dict) -> None:
        """Handle foci_resistance_run from firmware.

        Displays the firmware-selected count-space resistance slope and
        run-level warning/readback evidence as reported. The host does not
        recompute or re-select this value. Also caches the run fields
        (keyed by oid) so a subsequent commission completion can fold
        them into the persisted result; see pop_resistance_cache().
        """
        self.resistance_cache.setdefault(params["oid"], {})["run"] = {
            "selected_r_count_slope_milli": params["selected_r_count_slope_milli"],
            "gain_path_count_slope_milli": params.get("gain_path_count_slope_milli", 0),
            "status_flags_or": params["status_flags_or"],
            "warning_flags": params["warning_flags"],
            "profile_version": params["profile_version"],
        }
        msg = (
            "FOCI %s resistance run: status=%d profile_version=%d"
            " selected_r_count_slope_milli=%d warning_flags=%d"
            " status_flags_or=0x%08x pwm_maxcnt_readback=%d"
            " bbm_readback=0x%04x dsadc_mdec_readback=0x%08x"
            " pwm_sv_chop_readback=0x%08x"
            % (
                self.driver.name,
                params["status"],
                params["profile_version"],
                params["selected_r_count_slope_milli"],
                params["warning_flags"],
                params["status_flags_or"],
                params["pwm_maxcnt_readback"],
                params["bbm_readback"],
                params["dsadc_mdec_readback"],
                params["pwm_sv_chop_readback"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_resistance_axis(self, params: dict) -> None:
        """Handle foci_resistance_axis from firmware.

        Displays the firmware-fitted per-axis resistance evidence exactly
        as reported: count-slope, intercept, fit residual, point-selection
        masks, signed-anchor slope/asymmetry, and thermal drift. The host
        does not fit, select points, or evaluate quality gates here. Also
        caches the axis fields (keyed by oid, routed by electrical_axis —
        not arrival order) so a subsequent commission completion can fold
        them into the persisted result; see pop_resistance_cache().
        """
        axis_key = "axis%d" % params["electrical_axis"]
        self.resistance_cache.setdefault(params["oid"], {})[axis_key] = {
            "r_count_slope_milli": params["r_count_slope_milli"],
            "intercept_count": params.get("intercept_count", 0),
            "rmse_permille": params.get("rmse_permille", 0),
            "selected_mask": params.get("selected_mask", 0),
            "signed_count_slope_milli": params.get("signed_count_slope_milli", 0),
            "signed_asymmetry_permille": params.get("signed_asymmetry_permille", 0),
            "drift_permille": params.get("drift_permille", 0),
        }
        msg = (
            "FOCI %s resistance axis: electrical_axis=%d phi_e_ext=%d"
            " count_slope=%d intercept_count=%d rmse_permille=%d"
            " selected_mask=0x%04x excluded_point_mask=0x%04x"
            " selected_count=%d signed_count_slope=%d"
            " signed_asymmetry_permille=%d drift_permille=%d"
            " warning_flags=%d"
            % (
                self.driver.name,
                params["electrical_axis"],
                params["phi_e_ext"],
                params["r_count_slope_milli"],
                params.get("intercept_count", 0),
                params.get("rmse_permille", 0),
                params.get("selected_mask", 0),
                params.get("excluded_point_mask", 0),
                params.get("selected_count", 0),
                params.get("signed_count_slope_milli", 0),
                params.get("signed_asymmetry_permille", 0),
                params.get("drift_permille", 0),
                params["warning_flags"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def pop_resistance_cache(self, oid: int) -> dict:
        """Fold cached commission-stream resistance replies into result keys.

        Returns a dict of `resistance_*` keys (the keys
        CommissioningWorkflow.persist_commission_results' presence-gated
        resistance block already expects), built from the cached
        foci_resistance_run / foci_resistance_axis replies for `oid` by
        handle_resistance_run / handle_resistance_axis. Clears the cache
        entry for `oid` unconditionally (see clear_resistance_cache).

        All-or-nothing: returns the full folded dict only when the cache
        holds the run reply AND both axis0 and axis1 replies. If any of
        the three is missing — for example a commission that completed
        before every resistance reply arrived — returns `{}` so the
        presence-gate in persist_commission_results' resistance block
        skips the block entirely instead of persisting a partial set of
        identified_r_* keys (or raising a KeyError on the missing one).

        The host performs no fitting, point selection, unit conversion,
        or quality-gate evaluation here: every value is copied through
        from the firmware-reported reply fields as-is.
        """
        cached = self.clear_resistance_cache(oid)
        if not cached:
            return {}

        run = cached.get("run")
        axis0 = cached.get("axis0")
        axis1 = cached.get("axis1")
        if run is None or axis0 is None or axis1 is None:
            return {}

        folded: dict = {
            "resistance_selected_count_slope_milli": run[
                "selected_r_count_slope_milli"
            ],
            "resistance_gain_path_count_slope_milli": run[
                "gain_path_count_slope_milli"
            ],
            "resistance_status_flags_or": run["status_flags_or"],
            "resistance_warning_flags": run["warning_flags"],
            "resistance_profile_version": run["profile_version"],
        }

        for axis_index, axis in ((0, axis0), (1, axis1)):
            folded["resistance_axis%d_count_slope_milli" % axis_index] = axis[
                "r_count_slope_milli"
            ]
            folded["resistance_axis%d_intercept_count" % axis_index] = axis[
                "intercept_count"
            ]
            folded["resistance_axis%d_rmse_permille" % axis_index] = axis[
                "rmse_permille"
            ]
            folded["resistance_selected_mask_axis%d" % axis_index] = axis[
                "selected_mask"
            ]
            folded["resistance_axis%d_signed_count_slope_milli" % axis_index] = axis[
                "signed_count_slope_milli"
            ]
            folded["resistance_axis%d_signed_asymmetry_permille" % axis_index] = axis[
                "signed_asymmetry_permille"
            ]
            folded["resistance_axis%d_drift_permille" % axis_index] = axis[
                "drift_permille"
            ]

        return folded

    def clear_resistance_cache(self, oid: int) -> dict:
        """Discard and return the cached resistance replies for `oid`.

        Called by pop_resistance_cache on the commission success path, and
        directly by CommissioningWorkflow on every early-exit failure path
        (timeout, mid-phase error) so a failed or aborted commission never
        leaves a stale resistance-reply cache for a later run to fold in.
        Returns an empty dict if nothing was cached.
        """
        return self.resistance_cache.pop(oid, None) or {}

    def voltage_step_test(self, gcmd) -> None:
        """Run a bounded open-loop voltage-vector pulse and sample it."""
        uq_ext = gcmd.get_int("UQ", minval=-1024, maxval=1024)
        ud_ext = gcmd.get_int("UD", 0, minval=-1024, maxval=1024)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)

        self.driver.protocol.run_voltage_step_test(
            uq_ext=uq_ext,
            ud_ext=ud_ext,
            sample_delay_ms=sample_delay_ms,
        )

        gcmd.respond_info(
            "FOCI %s voltage-step requested:"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d"
            % (self.driver.name, uq_ext, ud_ext, sample_delay_ms)
        )

    def resistance_test(self, gcmd) -> None:
        """Run the shared firmware resistance-identification diagnostic.

        Triggers the same firmware engine used by FOCI_COMMISSION's
        resistance-identification phase. Results stream back via the
        foci_resistance_profile/run/axis replies, which are displayed
        as reported with no host-side fitting or pass/fail evaluation.
        """
        detail = gcmd.get_int("DETAIL", 0, minval=0, maxval=255)

        self.driver.protocol.run_resistance_test(detail=detail)

        gcmd.respond_info(
            "FOCI %s resistance-test requested: detail=%d" % (self.driver.name, detail)
        )
