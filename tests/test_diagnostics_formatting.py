"""Tests for per-board CPU-cycle diagnostics formatting."""

from klipper_foci.diagnostics.formatting import cpu_cycles_per_us, format_stepper_perf_event


class _FakeMcu:
    def __init__(self, mcu_name: str | None):
        self._mcu_name = mcu_name

    def get_constants(self) -> dict:
        return {} if self._mcu_name is None else {"MCU": self._mcu_name}


def test_cpu_cycles_per_us_resolves_openffboard():
    assert cpu_cycles_per_us(_FakeMcu("stm32f407xx")) == 168


def test_cpu_cycles_per_us_resolves_ouroboros():
    assert cpu_cycles_per_us(_FakeMcu("stm32h723xx")) == 520


def test_cpu_cycles_per_us_defaults_when_mcu_constant_missing():
    assert cpu_cycles_per_us(_FakeMcu(None)) == 168


def test_cpu_cycles_per_us_defaults_when_get_constants_unavailable():
    class _NoConstants:
        pass

    assert cpu_cycles_per_us(_NoConstants()) == 168


def test_format_stepper_perf_event_uses_supplied_cycles_per_us():
    params = {"reason": 5, "channel": 0, "crit_max_cycles": 190000}

    openffboard = format_stepper_perf_event("stepper_x", params, 168)
    ouroboros = format_stepper_perf_event("stepper_x", params, 520)

    assert "crit_max_us=1130" in openffboard
    assert "crit_max_us=365" in ouroboros
