"""Tests for host-side stepper motion-scale/waveform derivations.

Inputs and expected outputs are copied from the firmware drift guard
`host_exec_stats_derivations_match_firmware_formulas` in
`shared/foci-firmware/src/motion_scale.rs`, so both sides are pinned to the
same numbers.
"""

import pytest
from klipper_foci.diagnostics.stepper_scale import derived_exec_stats

WAVEFORM_TIMING_CASES = [
    # clock_freq, step_half_period_ticks, dir_setup_ticks, waveform_worst_case_ticks,
    # fatal_lateness_ticks
    (84_000_000, 4, 8, 24, 84_000),
    (260_000_000, 11, 22, 66, 260_000),
]

MOTION_SCALE_CASES = [
    # planner_steps_per_rev, tmc_grid, physical_step_width, motion_scale_configured
    (0, 0, 0, 0),
    (200, 256, 256, 1),
    (6_400, 8_192, 8, 1),
    (65_536, 65_536, 1, 1),
    (70_000, 65_536, 1, 1),
]


@pytest.mark.parametrize(
    "clock_freq,step_half_period_ticks,dir_setup_ticks,waveform_worst_case_ticks,"
    "fatal_lateness_ticks",
    WAVEFORM_TIMING_CASES,
)
def test_derived_exec_stats_waveform_timing(
    clock_freq,
    step_half_period_ticks,
    dir_setup_ticks,
    waveform_worst_case_ticks,
    fatal_lateness_ticks,
):
    result = derived_exec_stats(planner_steps_per_rev=200, encoder_ppr=1000, clock_freq=clock_freq)
    assert result["step_half_period_ticks"] == step_half_period_ticks
    assert result["dir_setup_ticks"] == dir_setup_ticks
    assert result["waveform_worst_case_ticks"] == waveform_worst_case_ticks
    assert result["fatal_lateness_ticks"] == fatal_lateness_ticks


@pytest.mark.parametrize(
    "planner_steps_per_rev,tmc_grid,physical_step_width,motion_scale_configured",
    MOTION_SCALE_CASES,
)
def test_derived_exec_stats_motion_scale(
    planner_steps_per_rev, tmc_grid, physical_step_width, motion_scale_configured
):
    result = derived_exec_stats(
        planner_steps_per_rev=planner_steps_per_rev, encoder_ppr=1000, clock_freq=84_000_000
    )
    assert result["tmc_grid"] == tmc_grid
    assert result["physical_step_width"] == physical_step_width
    assert result["motion_scale_configured"] == motion_scale_configured


def test_derived_exec_stats_encoder_counts_per_rev():
    result = derived_exec_stats(planner_steps_per_rev=200, encoder_ppr=1000, clock_freq=84_000_000)
    assert result["encoder_counts_per_rev"] == 4_000
