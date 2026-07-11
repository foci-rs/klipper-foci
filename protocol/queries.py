"""Passive diagnostic query helpers for klipper-foci protocol."""

from __future__ import annotations


MOTION_SCALE_STATS_FIELDS = (
    "physical_pos_pulses",
    "physical_neg_pulses",
    "planner_steps_per_rev",
    "encoder_ppr",
    "encoder_counts_per_rev",
    "tmc_grid",
    "physical_step_width",
    "motion_scale_configured",
    "step_half_period_ticks",
    "dir_setup_ticks",
    "waveform_worst_case_ticks",
    "fatal_lateness_ticks",
)


def get_step_position(protocol) -> dict:
    if protocol.driver.oid is None or protocol.commands.stepper_get_position is None:
        raise protocol.driver.printer.command_error(
            "FOCI_STEP_POSITION is not available before MCU identify"
        )
    params = protocol.commands.stepper_get_position.send([protocol.driver.oid])
    if params is None or "pos" not in params:
        raise protocol.driver.printer.command_error(
            "FOCI_STEP_POSITION query returned no position"
        )
    return params


def get_stepper_stats(protocol) -> tuple[dict, dict, dict, dict]:
    queries = (
        ("stats", protocol.commands.stepper_stats),
        ("exec_stats", protocol.commands.stepper_exec_stats),
        ("timing_stats", protocol.commands.stepper_timing_stats),
        ("stop_stats", protocol.commands.stepper_stop_stats),
    )
    if protocol.driver.oid is None or any(cmd is None for _, cmd in queries):
        raise protocol.driver.printer.command_error(
            "FOCI_STEPPER_STATS is not available before MCU identify"
        )
    responses = []
    for name, cmd in queries:
        response = cmd.send([protocol.driver.oid])
        if response is None:
            raise protocol.driver.printer.command_error(
                "FOCI_STEPPER_STATS %s query returned no data" % name
            )
        if name == "exec_stats":
            missing = [
                field for field in MOTION_SCALE_STATS_FIELDS if field not in response
            ]
            if missing:
                raise protocol.driver.printer.command_error(
                    "FOCI_STEPPER_STATS exec_stats query returned incomplete data: %s"
                    % ", ".join(missing)
                )
        responses.append(response)
    return tuple(responses)


def get_stepper_perf_stats(protocol, *, clear: bool) -> dict:
    if protocol.driver.oid is None or protocol.commands.stepper_perf_stats is None:
        raise protocol.driver.printer.command_error(
            "FOCI_DISPATCH_STATS is not available before MCU identify"
        )
    response = protocol.commands.stepper_perf_stats.send(
        [protocol.driver.oid, int(clear)]
    )
    if response is None:
        raise protocol.driver.printer.command_error(
            "FOCI_DISPATCH_STATS query returned no data"
        )
    return response
