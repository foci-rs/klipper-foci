"""Host-side derivation of stepper motion-scale and physical-waveform fields."""

from __future__ import annotations

QUADRATURE_COUNTS_PER_PULSE = 4
POSITION_UNITS_PER_REV = 65_536
MAX_STEP_RISING_EDGE_HZ = 12_500_000


def _next_power_of_two(value: int) -> int:
    """Match Rust's `u32::next_power_of_two` for positive `value`."""
    if value <= 1:
        return 1
    return 1 << (value - 1).bit_length()


def tmc_grid(planner_steps_per_rev: int) -> int:
    """Return the TMC pulse grid the firmware maps planner steps onto.

    Zero means motion scale is not configured.
    """
    if planner_steps_per_rev == 0:
        return 0
    return min(_next_power_of_two(planner_steps_per_rev), POSITION_UNITS_PER_REV)


def derived_exec_stats(planner_steps_per_rev: int, encoder_ppr: int, clock_freq: int) -> dict:
    """Return the fields `foci_stepper_exec_stats_result` no longer sends."""
    encoder_counts_per_rev = QUADRATURE_COUNTS_PER_PULSE * encoder_ppr

    grid = tmc_grid(planner_steps_per_rev)
    physical_step_width = POSITION_UNITS_PER_REV // grid if grid else 0
    motion_scale_configured = int(planner_steps_per_rev != 0)

    half_period_denominator_hz = 2 * MAX_STEP_RISING_EDGE_HZ
    step_half_period_ticks = -(-clock_freq // half_period_denominator_hz)
    dir_setup_ticks = 2 * step_half_period_ticks
    waveform_worst_case_ticks = 6 * step_half_period_ticks
    fatal_lateness_ticks = clock_freq // 1_000

    return {
        "encoder_counts_per_rev": encoder_counts_per_rev,
        "tmc_grid": grid,
        "physical_step_width": physical_step_width,
        "motion_scale_configured": motion_scale_configured,
        "step_half_period_ticks": step_half_period_ticks,
        "dir_setup_ticks": dir_setup_ticks,
        "waveform_worst_case_ticks": waveform_worst_case_ticks,
        "fatal_lateness_ticks": fatal_lateness_ticks,
    }
