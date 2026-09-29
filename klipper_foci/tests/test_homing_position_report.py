"""Tests for FOCI homing position diagnostics."""

import logging
from types import SimpleNamespace

import pytest

from tests.mocks import MockStepper, make_driver

HOMING_LOGGER = "klipper_foci.homing"


def test_homing_move_end_reports_nothing_without_debug(caplog):
    """Homing diagnostics are per-move noise: report_detail's contract is
    that with [foci] debug off, they are dropped everywhere -- not console,
    not log."""
    driver = make_driver(stepper_name="stepper_y")
    gcode = driver.printer.lookup_object("gcode")
    stepper = MockStepper("stepper_y", step_dist=0.01)
    homing_move = SimpleNamespace(
        stepper_positions=[
            SimpleNamespace(
                stepper=stepper,
                stepper_name="stepper_y",
                endstop_name="x",
                start_pos=-13904,
                trig_pos=13692,
                halt_pos=26934,
            ),
        ]
    )

    with caplog.at_level(logging.INFO, logger=HOMING_LOGGER):
        driver.homing.handle_homing_move_end(homing_move)

    assert gcode._responses == []
    assert caplog.records == []


def test_homing_move_end_skips_stall_query_without_debug():
    driver = make_driver(stepper_name="stepper_y")
    homing_move = SimpleNamespace(
        stepper_positions=[
            SimpleNamespace(
                stepper=MockStepper("stepper_y", step_dist=0.01),
                stepper_name="stepper_y",
                endstop_name="x",
                start_pos=-13904,
                trig_pos=13692,
                halt_pos=26934,
            ),
        ]
    )

    driver.homing.handle_homing_move_end(homing_move)

    assert driver.config.homing_current > 0.0
    assert driver.protocol.commands.query_stall.call_count == 0


def test_homing_move_end_reports_matching_stepper_positions(caplog):
    """With [foci] debug on, homing diagnostics reach klippy.log but still
    never the console -- they stay developer detail, not an operator
    summary."""
    driver = make_driver(stepper_name="stepper_y")
    driver.global_config.debug = True
    gcode = driver.printer.lookup_object("gcode")
    stepper = MockStepper("stepper_y", step_dist=0.01)
    homing_move = SimpleNamespace(
        stepper_positions=[
            SimpleNamespace(
                stepper=MockStepper("stepper_x", step_dist=0.01),
                stepper_name="stepper_x",
                endstop_name="x",
                start_pos=-13904,
                trig_pos=13692,
                halt_pos=13692,
            ),
            SimpleNamespace(
                stepper=stepper,
                stepper_name="stepper_y",
                endstop_name="x",
                start_pos=-13904,
                trig_pos=13692,
                halt_pos=26934,
            ),
        ]
    )

    with caplog.at_level(logging.INFO, logger=HOMING_LOGGER):
        driver.homing.handle_homing_move_end(homing_move)

    assert gcode._responses == []
    messages = [record.message for record in caplog.records]
    assert messages[0] == (
        "FOCI_HOME_POSITION stepper_y endstop=x start=-13904 trig=13692 "
        "halt=26934 move_steps=40838 over_steps=13242 "
        "move_mm=408.380 over_mm=132.420"
    )
    assert messages[1] == (
        "FOCI_HOME_STALL stepper_y latched=1 peak_error_units=1234 "
        "peak_error_mm=0.753 trigger_tick=7 clamp_active=0 trigger_path=margin "
        "peak_margin_delta_units=45"
    )


@pytest.mark.parametrize(
    "trigger_path,expected_name",
    [
        (0, "none"),
        (1, "ceiling"),
    ],
)
def test_report_stall_result_names_non_margin_trigger_paths(trigger_path, expected_name, caplog):
    driver = make_driver(stepper_name="stepper_y")
    driver.global_config.debug = True
    driver.protocol.commands.query_stall.response = {
        "latched": 0,
        "peak_error_units": 1234,
        "trigger_tick": 7,
        "clamp_active": 0,
        "trigger_path": trigger_path,
        "peak_margin_delta_units": 45,
    }

    with caplog.at_level(logging.INFO, logger=HOMING_LOGGER):
        driver.homing._report_stall_result()

    assert caplog.records[0].message == (
        "FOCI_HOME_STALL stepper_y latched=0 peak_error_units=1234 "
        "peak_error_mm=0.753 trigger_tick=7 clamp_active=0 "
        f"trigger_path={expected_name} peak_margin_delta_units=45"
    )


def test_homing_move_end_reports_step_history_summary(caplog):
    driver = make_driver(stepper_name="stepper_y")
    driver.global_config.debug = True
    gcode = driver.printer.lookup_object("gcode")
    toolhead = driver.printer.lookup_object("toolhead")
    toolhead.last_move_time = 12.0
    stepper = MockStepper(
        "stepper_y",
        step_dist=0.01,
        step_history=[
            SimpleNamespace(
                first_clock=12050,
                last_clock=12100,
                start_position=-13000,
                step_count=300,
                interval=10,
                add=0,
            ),
            SimpleNamespace(
                first_clock=12100,
                last_clock=12200,
                start_position=-12700,
                step_count=500,
                interval=10,
                add=0,
            ),
        ],
    )
    homing_move = SimpleNamespace(
        toolhead=toolhead,
        stepper_positions=[
            SimpleNamespace(
                stepper=stepper,
                stepper_name="stepper_y",
                endstop_name="x",
                start_pos=-13000,
                trig_pos=-12200,
                halt_pos=-12200,
            )
        ],
    )

    driver.homing.handle_homing_move_begin(homing_move)
    toolhead.last_move_time = 13.0
    with caplog.at_level(logging.INFO, logger=HOMING_LOGGER):
        driver.homing.handle_homing_move_end(homing_move)

    assert gcode._responses == []
    messages = [record.message for record in caplog.records]
    assert len(messages) == 4
    assert messages[1] == (
        "FOCI_HOME_STEP_HISTORY stepper_y start_clock=12000 end_clock=13000 "
        "segments=2 move_segments=2 marker_segments=0 signed_steps=800 "
        "abs_steps=800 pos_steps=800 neg_steps=0 dir_changes=0 "
        "gap_steps=0 planned_start=-13000 planned_end=-12200 "
        "first_clock=12050 last_clock=12200 signed_mm=8.000 abs_mm=8.000"
    )
    assert messages[2] == (
        "FOCI_HOME_STEP_SEGMENTS stepper_y first="
        "12050:-13000:+300@10/+0,12100:-12700:+500@10/+0 last="
        "12050:-13000:+300@10/+0,12100:-12700:+500@10/+0 markers=none"
    )
    assert messages[3] == (
        "FOCI_HOME_STALL stepper_y latched=1 peak_error_units=1234 "
        "peak_error_mm=0.753 trigger_tick=7 clamp_active=0 trigger_path=margin "
        "peak_margin_delta_units=45"
    )


def test_homing_move_end_reports_signed_step_history_details(caplog):
    driver = make_driver(stepper_name="stepper_x")
    driver.global_config.debug = True
    gcode = driver.printer.lookup_object("gcode")
    toolhead = driver.printer.lookup_object("toolhead")
    toolhead.last_move_time = 20.0
    stepper = MockStepper(
        "stepper_x",
        step_dist=0.01,
        step_history=[
            SimpleNamespace(
                first_clock=20010,
                last_clock=20100,
                start_position=0,
                step_count=100,
                interval=10,
                add=0,
            ),
            SimpleNamespace(
                first_clock=20100,
                last_clock=20200,
                start_position=100,
                step_count=-70,
                interval=11,
                add=-1,
            ),
            SimpleNamespace(
                first_clock=20200,
                last_clock=20300,
                start_position=30,
                step_count=20,
                interval=12,
                add=1,
            ),
            SimpleNamespace(
                first_clock=20310,
                last_clock=20310,
                start_position=50,
                step_count=0,
                interval=0,
                add=0,
            ),
        ],
    )
    homing_move = SimpleNamespace(
        toolhead=toolhead,
        stepper_positions=[
            SimpleNamespace(
                stepper=stepper,
                stepper_name="stepper_x",
                endstop_name="x",
                start_pos=0,
                trig_pos=50,
                halt_pos=50,
            )
        ],
    )

    driver.homing.handle_homing_move_begin(homing_move)
    toolhead.last_move_time = 21.0
    with caplog.at_level(logging.INFO, logger=HOMING_LOGGER):
        driver.homing.handle_homing_move_end(homing_move)

    assert gcode._responses == []
    messages = [record.message for record in caplog.records]
    assert len(messages) == 4
    assert messages[1] == (
        "FOCI_HOME_STEP_HISTORY stepper_x start_clock=20000 end_clock=21000 "
        "segments=4 move_segments=3 marker_segments=1 signed_steps=50 "
        "abs_steps=190 pos_steps=120 neg_steps=70 dir_changes=2 "
        "gap_steps=0 planned_start=0 planned_end=50 first_clock=20010 "
        "last_clock=20300 signed_mm=0.500 abs_mm=1.900"
    )
    assert messages[2] == (
        "FOCI_HOME_STEP_SEGMENTS stepper_x first="
        "20010:0:+100@10/+0,20100:100:-70@11/-1,"
        "20200:30:+20@12/+1 last="
        "20010:0:+100@10/+0,20100:100:-70@11/-1,"
        "20200:30:+20@12/+1 markers=20310:50"
    )
    assert messages[3] == (
        "FOCI_HOME_STALL stepper_x latched=1 peak_error_units=1234 "
        "peak_error_mm=0.753 trigger_tick=7 clamp_active=0 trigger_path=margin "
        "peak_margin_delta_units=45"
    )


def test_homing_move_end_ignores_unrelated_moves():
    driver = make_driver(stepper_name="stepper_z")
    gcode = driver.printer.lookup_object("gcode")
    homing_move = SimpleNamespace(
        stepper_positions=[
            SimpleNamespace(
                stepper=MockStepper("stepper_x", step_dist=0.01),
                stepper_name="stepper_x",
                endstop_name="x",
                start_pos=0,
                trig_pos=10,
                halt_pos=10,
            )
        ]
    )

    driver.homing.handle_homing_move_end(homing_move)

    assert gcode._responses == []


def test_homing_move_end_skips_stall_line_when_clamp_disabled(caplog):
    driver = make_driver(stepper_name="stepper_y")
    driver.global_config.debug = True
    driver.config.homing_current = 0.0
    gcode = driver.printer.lookup_object("gcode")
    stepper = MockStepper("stepper_y", step_dist=0.01)
    homing_move = SimpleNamespace(
        stepper_positions=[
            SimpleNamespace(
                stepper=stepper,
                stepper_name="stepper_y",
                endstop_name="y",
                start_pos=0,
                trig_pos=100,
                halt_pos=100,
            )
        ]
    )
    with caplog.at_level(logging.INFO, logger=HOMING_LOGGER):
        driver.homing.handle_homing_move_end(homing_move)
    assert gcode._responses == []
    assert len(caplog.records) == 1
