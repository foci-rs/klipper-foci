"""Self-test workflow for FOCI host commands."""

from __future__ import annotations

from .commissioning import COMMISSION_ERROR_NAMES, format_commission_detail

SELFTEST_STAGES: dict[int, str] = {
    1: "ADC calibration",
    2: "Motor coil A",
    3: "Motor coil B",
    4: "Phase wiring",
    5: "Encoder",
    6: "Encoder direction",
    7: "R-model evidence",
    8: "L-model evidence",
}


def format_selftest_value(stage: int, status: int, value: int) -> str:
    """Return a stage-specific detail string, or empty string for bare PASS."""
    if status != 0:
        return " (FAIL, raw=%d)" % value
    if stage == 1:
        offset_i0 = value & 0xFFFF
        offset_i1 = (value >> 16) & 0xFFFF
        return " (offset_i0=%d, offset_i1=%d)" % (offset_i0, offset_i1)
    if stage in (2, 3):
        low16 = value & 0xFFFF
        signed = low16 if low16 < 0x8000 else low16 - 0x10000
        return " (current=%d)" % signed
    if stage == 4:
        return ""
    if stage == 5:
        return " (delta=%d)" % value
    if stage == 6:
        return " (reversed)" if value == 1 else " (increasing)"
    if stage == 7:
        return " (r_count_milli=%d)" % value
    if stage == 8:
        return " (l_count_micro=%d)" % value
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
        if not self.driver.state.try_acquire():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.driver.name
            )
        try:
            self.driver.homing.invalidate_homing()

            reactor = self.driver.printer.get_reactor()
            self.results = []
            self.complete = False
            self.status = 0
            self.driver.commissioning.clear_details()

            self.driver.protocol.run_selftest()

            deadline = reactor.monotonic() + 15.0
            while not self.complete:
                if reactor.monotonic() > deadline:
                    raise self.driver.printer.command_error(
                        "FOCI %s: selftest timed out" % self.driver.stepper_name
                    )
                reactor.pause(reactor.monotonic() + 0.05)
        finally:
            self.driver.state.release()

        status_names = {0: "PASS", 1: "FAIL", 2: "SKIP"}
        lines = ["Self-Test: %s" % self.driver.stepper_name]
        passed = 0
        total = len(self.results)
        for result in self.results:
            stage_id = result["stage"]
            stage_status = result["status"]
            stage_value = result["value"]
            name = SELFTEST_STAGES.get(stage_id, "Stage %d" % stage_id)
            status_str = status_names.get(stage_status, "?")
            detail = format_selftest_value(stage_id, stage_status, stage_value)
            dots = "." * max(1, 35 - len(name))
            lines.append("  %s %s %s%s" % (name, dots, status_str, detail))
            if stage_status == 0:
                passed += 1

        if self.driver.commissioning.details:
            lines.append("Diagnostics:")
            for detail in self.driver.commissioning.details:
                lines.append("  %s" % format_commission_detail(detail))

        if self.status == 0:
            overall = "PASS"
        else:
            err = COMMISSION_ERROR_NAMES.get(
                self.status, "unknown error %d" % self.status
            )
            self.driver.commissioning.maybe_clear_calibration_for_chip_reset(
                self.status
            )
            overall = "FAIL (%s)" % err
        lines.append("Result: %s (%d/%d stages)" % (overall, passed, total))
        gcmd.respond_info("\n".join(lines))

        if self.status != 0:
            err = COMMISSION_ERROR_NAMES.get(
                self.status, "unknown error %d" % self.status
            )
            self.driver.commissioning.maybe_clear_calibration_for_chip_reset(
                self.status
            )
            raise self.driver.printer.command_error(
                "FOCI %s: selftest failed: %s" % (self.driver.stepper_name, err)
            )
