"""Passive diagnostic query helpers for klipper-foci protocol."""

from __future__ import annotations

MOTION_SCALE_STATS_FIELDS = (
    "physical_pos_pulses",
    "physical_neg_pulses",
    "planner_steps_per_rev",
    "encoder_ppr",
)


def get_step_position(protocol) -> dict:
    if protocol.driver.oid is None or protocol.commands.stepper_get_position is None:
        raise protocol.driver.printer.command_error(
            "FOCI_STEP_POSITION is not available before MCU identify"
        )
    params = protocol.commands.stepper_get_position.send([protocol.driver.oid])
    if params is None or "pos" not in params:
        raise protocol.driver.printer.command_error("FOCI_STEP_POSITION query returned no position")
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
                f"FOCI_STEPPER_STATS {name} query returned no data"
            )
        if name == "exec_stats":
            missing = [field for field in MOTION_SCALE_STATS_FIELDS if field not in response]
            if missing:
                raise protocol.driver.printer.command_error(
                    f"FOCI_STEPPER_STATS exec_stats query returned incomplete data: "
                    f"{', '.join(missing)}"
                )
        responses.append(response)
    return tuple(responses)


def get_stack_watermark(protocol) -> dict:
    if protocol.driver.oid is None or protocol.commands.stack_watermark is None:
        raise protocol.driver.printer.command_error(
            "FOCI_STACK_WATERMARK is not available before MCU identify"
        )
    response = protocol.commands.stack_watermark.send([protocol.driver.oid])
    if response is None:
        raise protocol.driver.printer.command_error("FOCI_STACK_WATERMARK query returned no data")
    missing = [
        field
        for field in ("stack_unused_bytes", "painted_bytes", "status")
        if field not in response
    ]
    if missing:
        raise protocol.driver.printer.command_error(
            f"FOCI_STACK_WATERMARK query returned incomplete data: {', '.join(missing)}"
        )
    return response
