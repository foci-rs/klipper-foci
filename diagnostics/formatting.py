"""Pure formatting helpers for FOCI diagnostics."""

from __future__ import annotations

STEPPER_EVENT_REASON_NAMES: dict[int, str] = {
    1: "queue_empty",
    2: "missed_deadline_load",
    3: "missed_deadline_step",
    4: "trsync_stop",
    5: "p1_stop",
    6: "reset_step_clock",
    7: "tmc_disable_signal",
}


def stepper_dir_inverted(stepper) -> bool:
    """Return whether a Klipper stepper's direction is inverted."""
    get_dir_inverted = getattr(stepper, "get_dir_inverted", None)
    if get_dir_inverted is None:
        return False
    dir_info = get_dir_inverted()
    if isinstance(dir_info, (list, tuple)):
        return bool(dir_info[0])
    return bool(dir_info)


def format_stepper_event(stepper_name: str, params: dict) -> str:
    """Format one firmware stepper diagnostic event."""
    reason_code = params.get("reason", 0)
    reason_name = STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")
    return (
        f"FOCI_STEPPER_EVENT {stepper_name} reason={reason_name}({int(reason_code)}) channel="
        f"{int(params.get('channel', 255))} pos={int(params.get('position', 0))} clock="
        f"{int(params.get('clock', 0))} timer_active={int(params.get('timer_active', 0))} "
        f"queue_len={int(params.get('queue_len', 65535))} dir={int(params.get('direction', 0))} "
        f"data0={int(params.get('data0', 0))} data1={int(params.get('data1', 0))}"
    )
