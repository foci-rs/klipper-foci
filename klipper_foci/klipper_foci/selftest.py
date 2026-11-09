"""Self-test workflow for FOCI host commands."""

from __future__ import annotations

import logging

from .commissioning import (
    COMMISSION_REASON_NAMES,
    _encoder_direction_sweep_failed,
    format_commission_detail,
    format_encoder_direction_failure,
    operator_failure_phrase,
)
from .constants import ELECTRICAL_ID_WAIT_TIMEOUT_S
from .report import report_detail, report_summary

log = logging.getLogger(__name__)

SELFTEST_STAGES: dict[int, str] = {
    1: "ADC calibration",
    2: "Motor coil A",
    3: "Motor coil B",
    4: "Phase wiring",
    5: "Encoder",
    6: "Encoder direction",
    7: "R-model evidence",
    8: "L control-model evidence",
}


def format_selftest_value(stage: int, status: int, value: int) -> str:
    """Return a stage-specific detail string, or empty string for bare PASS."""
    if stage == 1:
        offset_i0 = value & 0xFFFF
        offset_i1 = (value >> 16) & 0xFFFF
        return f" (offset_i0={int(offset_i0)}, offset_i1={int(offset_i1)})"
    if stage in (2, 3):
        low16 = value & 0xFFFF
        signed = low16 if low16 < 0x8000 else low16 - 0x10000
        return f" (current={int(signed)})"
    if stage == 5:
        return f" (delta={int(value)})"
    if stage == 6:
        return " (reversed)" if value == 1 else " (increasing)"
    if stage == 7:
        return f" (r_count_milli={int(value)})"
    if stage == 8:
        return f" (control_l_count_micro={int(value)})"
    if status != 0:
        return f" (raw={int(value)})"
    return ""


class SelftestWorkflow:
    """Run TMC4671 self-test and format streamed stage results."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.results: list[dict] = []
        self.complete = False
        self.status = 0

    def handle_selftest_result(self, params: dict) -> None:
        """Collect one stage result streamed during FOCI_SELFTEST."""
        result = {
            "stage": params["stage"],
            "status": params["status"],
            "value": params["value"],
        }
        for idx, existing in enumerate(self.results):
            if existing["stage"] == result["stage"]:
                self.results[idx] = result
                return
        self.results.append(result)

    def handle_selftest_done(self, params: dict) -> None:
        """Terminal signal for FOCI_SELFTEST."""
        self.complete = True
        self.status = params["status"]

    def selftest(self, gcmd) -> None:
        """Run TMC4671 self-test and emit a per-stage report."""
        if not self.driver.state.try_acquire("selftest"):
            raise gcmd.error(f"FOCI {self.driver.name}: another FOCI operation is in progress")
        try:
            reactor = self._start_run(gcmd)
            self._wait_for_completion(reactor)
        finally:
            self.driver.state.release()

        stage_lines = self._format_stage_lines()
        for line in stage_lines:
            report_summary(gcmd, line)
        self._log_report(stage_lines)
        self._report_outcome(gcmd)
        self._raise_if_failed()

    def _start_run(self, gcmd):
        """Reset per-run state, announce the run and dispatch the firmware self-test."""
        self.driver.homing.invalidate_homing()

        reactor = self.driver.printer.get_reactor()
        self.results = []
        self.complete = False
        self.status = 0
        self.driver.commissioning.clear_details()

        report_summary(
            gcmd,
            f"FOCI {self.driver.stepper_name} selftest: running, can take up to 30s...",
        )
        self.driver.protocol.run_selftest()
        return reactor

    def _wait_for_completion(self, reactor) -> None:
        """Poll until the firmware signals completion, cancelling on timeout."""
        deadline = reactor.monotonic() + ELECTRICAL_ID_WAIT_TIMEOUT_S
        while not self.complete:
            if reactor.monotonic() > deadline:
                self.driver.commissioning.cancel_and_await_quiescence(
                    reactor, lambda: self.complete, reactor.monotonic()
                )
                raise self.driver.printer.command_error(
                    f"FOCI {self.driver.stepper_name}: selftest timed out"
                )
            reactor.pause(reactor.monotonic() + 0.05)

    def _format_stage_lines(self) -> list[str]:
        """Format one report line per collected stage result."""
        status_names = {0: "PASS", 1: "FAIL", 2: "SKIP"}
        stage_lines = []
        for result in self.results:
            stage_id = result["stage"]
            stage_status = result["status"]
            stage_value = result["value"]
            name = SELFTEST_STAGES.get(stage_id, f"Stage {int(stage_id)}")
            status_str = status_names.get(stage_status, "?")
            detail = format_selftest_value(stage_id, stage_status, stage_value)
            dots = "." * max(1, 35 - len(name))
            stage_lines.append(f"  {name} {dots} {status_str}{detail}")
        return stage_lines

    def _log_report(self, stage_lines: list[str]) -> None:
        """Log the stage lines followed by any commissioning diagnostics."""
        lines = list(stage_lines)
        if self.driver.commissioning.details:
            lines.append("Diagnostics:")
            for detail in self.driver.commissioning.details:
                lines.append(f"  {format_commission_detail(detail)}")

        report_detail(log, self.driver.global_config.debug, "\n".join(lines))

    def _report_outcome(self, gcmd) -> None:
        """Emit the SUCCEEDED or FAILED summary line."""
        if self.status == 0:
            report_summary(
                gcmd,
                f"FOCI_SELFTEST {self.driver.stepper_name}: SUCCEEDED, all "
                f"{len(self.results)} stages passed.",
            )
        else:
            last_phase_detail_reason = None
            if _encoder_direction_sweep_failed(self.driver.commissioning.details):
                last_phase_detail_reason = format_encoder_direction_failure(
                    self.driver.commissioning.details
                )
            err = last_phase_detail_reason or operator_failure_phrase(self.status)
            self.driver.commissioning.maybe_clear_calibration_for_chip_reset(self.status)
            report_summary(gcmd, f"FOCI_SELFTEST {self.driver.stepper_name}: FAILED, {err}.")

    def _raise_if_failed(self) -> None:
        """Raise a command error naming the failure reason when the run failed."""
        if self.status != 0:
            err = COMMISSION_REASON_NAMES.get(self.status, f"unknown error {int(self.status)}")
            self.driver.commissioning.maybe_clear_calibration_for_chip_reset(self.status)
            raise self.driver.printer.command_error(
                f"FOCI {self.driver.stepper_name}: selftest failed: {err}"
            )
