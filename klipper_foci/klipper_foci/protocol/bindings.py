"""MCU response registration helpers for klipper-foci."""

from __future__ import annotations

import logging
import weakref

from ..diagnostics.formatting import format_stepper_event
from ..report import report_detail

log = logging.getLogger(__name__)

_STEPPER_EVENT_ROUTES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

MOTION_SCALE_REJECTION_NAMES = {
    1: "encoder_ppr is zero",
    2: "encoder_ppr exceeds 1073741823",
    3: "planner_steps_per_rev is zero",
    4: "planner_steps_per_rev exceeds 16777216",
    5: "motor runtime is enabled",
    6: "armed mirror is set",
    7: "physical step queue is not empty",
    8: "physical step timer is active",
    9: "mapper installation failed",
    10: "ABN_DECODER_PPR write failed",
    11: "STEP_WIDTH write failed",
    12: "TMC request queue is full",
    13: "board channel is unavailable",
}


def register_motion_scale_responses(serial, driver, oid: int) -> None:
    """Register the cause-specific motion-scale rejection diagnostic."""

    def handle_rejection(params) -> None:
        stage = {0: "P2", 1: "P1"}.get(params["stage"], f"stage {int(params['stage'])}")
        reason = MOTION_SCALE_REJECTION_NAMES.get(
            params["reason"], f"unknown reason {int(params['reason'])}"
        )
        logging.error(
            "FOCI %s motion-scale configuration rejected in %s: %s",
            driver.stepper_name,
            stage,
            reason,
        )

    serial.register_response(handle_rejection, "foci_motion_scale_rejected", oid)


def register_dump_responses(serial, driver, oid: int) -> None:
    serial.register_response(driver.dump.handle_dump_value, "foci_dump_value", oid)
    serial.register_response(driver.dump.handle_dump_done, "foci_dump_done", oid)


_LAST_BOOT_FAULT_KIND_NAMES = {1: "rust_panic", 2: "hard_fault"}


def register_last_boot_diagnostic_response(serial, driver, oid: int) -> None:
    """Log a previous-boot fault."""

    def handle_last_boot_diagnostic(params: dict) -> None:
        fault_kind = params.get("fault_kind", 0)

        if fault_kind != 0:
            fault_name = _LAST_BOOT_FAULT_KIND_NAMES.get(fault_kind, f"unknown({fault_kind})")
            logging.error(
                "FOCI board recovered last-boot fault: kind=%s line=%s pc=0x%08x file_hash=0x%08x",
                fault_name,
                params.get("line"),
                params.get("pc", 0),
                params.get("file_hash", 0),
            )

    serial.register_response(handle_last_boot_diagnostic, "foci_last_boot_diagnostic", oid)


def register_homing_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.homing.handle_calibrate_response,
        "foci_calibrate_result",
        oid,
    )


def register_commissioning_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.commissioning.handle_commission_phase,
        "foci_commission_phase",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_done,
        "foci_commission_done",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_result,
        "foci_commission_result",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_detail,
        "foci_commission_detail",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_timing,
        "foci_commission_timing",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_run,
        "foci_inductance_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_frame,
        "foci_inductance_frame",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_estimate,
        "foci_inductance_estimate",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_filters,
        "foci_current_loop_filters",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_run,
        "foci_resistance_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_axis,
        "foci_resistance_axis",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_run,
        "foci_current_loop_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_hold,
        "foci_current_loop_hold",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_closed_loop_activation,
        "foci_closed_loop_activation",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_axis,
        "foci_current_validation_axis",
        oid,
    )


def register_selftest_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.selftest.handle_selftest_result,
        "foci_selftest_result",
        oid,
    )
    serial.register_response(
        driver.selftest.handle_selftest_done,
        "foci_selftest_done",
        oid,
    )


def register_diagnostic_only_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.diagnostics.handle_current_step_result,
        "foci_current_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_vector_step_result,
        "foci_current_vector_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_torque_sample_result,
        "foci_current_torque_sample_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_torque_sample_pid_result,
        "foci_current_torque_sample_pid_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_torque_sample_detail_result,
        "foci_current_torque_sample_detail_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_voltage_step_detail_result,
        "foci_voltage_step_detail_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_voltage_step_result,
        "foci_voltage_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_profile,
        "foci_resistance_profile",
        oid,
    )


def register_stepper_event_response(mcu, driver) -> None:
    """Route `foci_stepper_event` to the driver that owns the event's channel.

    The reply carries a board channel but no oid, so it is registered once per
    MCU; a per-driver registration would let whichever driver bound last
    receive, and mislabel, every channel's events.
    """
    serial = mcu._serial
    routes = _STEPPER_EVENT_ROUTES.get(serial)
    if routes is None:
        routes = {}
        _STEPPER_EVENT_ROUTES[serial] = routes
        mcu_name = mcu.get_name()

        def handle_stepper_event(params: dict) -> None:
            owner = routes.get(int(params.get("channel", 255)))
            if owner is not None:
                owner.diagnostics.handle_stepper_event(params)
                return
            debug = any(d.global_config.debug for d in routes.values())
            report_detail(log, debug, format_stepper_event(f"mcu {mcu_name}", params))

        serial.register_response(handle_stepper_event, "foci_stepper_event")
    routes[int(driver.channel)] = driver
