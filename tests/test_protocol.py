"""Tests for the klipper-foci host-to-firmware protocol boundary."""

from __future__ import annotations

import pytest

from klipper_foci.protocol import FociProtocol

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockCommand,
    MockMCU,
    make_driver,
)


def response_names(mcu):
    return [(name, oid) for _callback, name, oid in mcu._serial.responses]


def test_bind_mcu_looks_up_commands_and_registers_responses():
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver.protocol.bind_mcu(mcu, driver.oid)

    commands = driver.protocol.commands
    assert commands.set_current is not None
    assert commands.set_encoder is not None
    assert commands.calibrate is not None
    assert commands.commission is not None
    assert commands.tune is not None
    assert commands.selftest is not None
    assert commands.dump_registers is not None
    assert commands.stepper_perf_stats is not None
    assert commands.current_step_test is not None

    assert (
        "stepper_get_position oid=%c",
        "stepper_position oid=%c pos=%i",
        driver.oid,
    ) in mcu.query_commands
    assert (
        "foci_stepper_perf_stats oid=%c clear=%c",
        commands.STEPPER_PERF_STATS_RESPONSE,
        driver.oid,
    ) in mcu.query_commands

    registrations = response_names(mcu)
    assert ("foci_dump_value", driver.oid) in registrations
    assert ("foci_dump_done", driver.oid) in registrations
    assert ("foci_calibrate_result", driver.oid) in registrations
    assert ("foci_commission_phase", driver.oid) in registrations
    assert ("foci_commission_result", driver.oid) in registrations
    assert ("foci_tune_result", driver.oid) in registrations
    assert ("foci_selftest_result", driver.oid) in registrations
    assert ("foci_selftest_done", driver.oid) in registrations
    assert ("foci_stepper_event", None) in registrations
    assert ("foci_stepper_perf_event", None) in registrations
    assert ("foci_commission_detail", driver.oid) in registrations
    assert ("foci_current_step_result", driver.oid) in registrations
    assert ("foci_current_vector_step_result", driver.oid) in registrations
    assert ("foci_current_torque_sample_result", driver.oid) in registrations
    assert (
        "foci_current_torque_sample_detail_result",
        driver.oid,
    ) in registrations
    assert ("foci_voltage_step_result", driver.oid) in registrations
    assert ("foci_resistance_profile", driver.oid) in registrations
    assert ("foci_resistance_run", driver.oid) in registrations
    assert ("foci_resistance_axis", driver.oid) in registrations
    assert ("foci_current_loop_run", driver.oid) in registrations
    assert ("foci_current_validation_axis", driver.oid) in registrations
    assert ("foci_impedance_profile", driver.oid) in registrations
    assert ("foci_impedance_fit", driver.oid) in registrations
    assert ("foci_impedance_observation", driver.oid) in registrations
    assert ("foci_impedance_run", driver.oid) in registrations
    assert len(registrations) == len(set(registrations))


def test_driver_mcu_identify_binds_protocol_without_driver_aliases():
    driver = make_driver(
        stepper_name="stepper_x",
        kinematics=MockCartesianKinematics([["stepper_x"]]),
    )
    driver.mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver._handle_mcu_identify()

    assert driver.protocol.commands.set_current is not None
    assert driver.protocol.commands.calibrate is not None
    assert not hasattr(driver, "set_current_cmd")
    assert not hasattr(driver, "calibrate_cmd")
    assert ("foci_calibrate_result", driver.oid) in response_names(driver.mcu)


class RecordingCommand:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls
        self.last_args = None

    def send(self, args=None):
        self.last_args = args
        self.calls.append((self.name, args))
        return None


def install_recording_commands(commands, names):
    calls = []
    for name in names:
        setattr(commands, name, RecordingCommand(name, calls))
    return calls


def test_configure_startup_sends_existing_connect_payload_order():
    driver = make_driver()
    commands = driver.protocol.commands
    calls = install_recording_commands(
        commands,
        [
            "set_current",
            "set_voltage_limit",
            "set_encoder",
            "set_encoder_dir",
            "set_pid_gains",
            "set_velocity_filter",
            "set_torque_filter",
            "set_position_filter",
            "set_flux_filter",
            "set_position_gains",
            "set_velocity_feedforward",
            "set_velocity_limit",
        ],
    )

    driver.protocol.configure_startup(
        current_ma=800,
        voltage_limit=16000,
        channel=0,
        encoder_ppr=1000,
        encoder_reversed=True,
        pid_gains=(100, 200, 300, 400),
        filter_hz={
            "velocity": 80,
            "torque": 90,
            "position": 100,
            "flux": 110,
        },
        position_gains=(700, 0, 1100, 0),
        velocity_feedforward=(True, 8),
        velocity_limit=50000,
    )

    assert calls == [
        ("set_current", [driver.oid, 800]),
        ("set_voltage_limit", [driver.oid, 16000]),
        ("set_encoder", [driver.oid, 0, 1000]),
        ("set_encoder_dir", [driver.oid, 0, 1]),
        ("set_pid_gains", [driver.oid, 100, 200, 300, 400]),
        ("set_velocity_filter", [driver.oid, 80]),
        ("set_torque_filter", [driver.oid, 90]),
        ("set_position_filter", [driver.oid, 100]),
        ("set_flux_filter", [driver.oid, 110]),
        ("set_position_gains", [driver.oid, 700, 0, 1100, 0]),
        ("set_velocity_feedforward", [driver.oid, 1, 8]),
        ("set_velocity_limit", [driver.oid, 50000]),
    ]


def test_configure_startup_skips_unset_optional_payloads():
    driver = make_driver()
    commands = driver.protocol.commands
    calls = install_recording_commands(
        commands,
        [
            "set_current",
            "set_voltage_limit",
            "set_encoder",
            "set_encoder_dir",
            "set_pid_gains",
            "set_velocity_filter",
            "set_position_gains",
            "set_velocity_feedforward",
            "set_velocity_limit",
        ],
    )

    driver.protocol.configure_startup(
        current_ma=800,
        voltage_limit=16000,
        channel=0,
        encoder_ppr=1000,
        encoder_reversed=False,
        pid_gains=None,
        filter_hz={"velocity": 0, "torque": 0, "position": 0, "flux": 0},
        position_gains=None,
        velocity_feedforward=(False, 1),
        velocity_limit=None,
    )

    assert calls == [
        ("set_current", [driver.oid, 800]),
        ("set_voltage_limit", [driver.oid, 16000]),
        ("set_encoder", [driver.oid, 0, 1000]),
        ("set_encoder_dir", [driver.oid, 0, 0]),
    ]


def test_fine_grained_control_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.set_current(1700)
    driver.protocol.set_pid_gains(1, 2, 3, 4)
    driver.protocol.set_position_gains(5, 6, 7, 8)
    driver.protocol.set_velocity_feedforward(True, 9)
    driver.protocol.set_velocity_limit(10)
    driver.protocol.set_voltage_limit(11000)

    commands = driver.protocol.commands
    assert commands.set_current.last_args == [driver.oid, 1700]
    assert commands.set_pid_gains.last_args == [driver.oid, 1, 2, 3, 4]
    assert commands.set_position_gains.last_args == [driver.oid, 5, 6, 7, 8]
    assert commands.set_velocity_feedforward.last_args == [driver.oid, 1, 9]
    assert commands.set_velocity_limit.last_args == [driver.oid, 10]
    assert commands.set_voltage_limit.last_args == [driver.oid, 11000]


def test_expert_control_protocol_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.set_velocity_transient_feedforward(
        enable=True,
        lead_time_us=400,
        gain=750,
        max_offset=1200,
        rate_hz=10000,
    )
    driver.protocol.set_accel_feedforward(
        enable=False,
        accel_gain=750,
        decel_gain=250,
    )
    driver.protocol.set_decoupling_feedforward(
        enable=True,
        r_int=3000,
        l_int=4095,
        pole_pairs=50,
        position_units_per_rev=65536,
        f_pwm_hz=25000,
        max_offset=500,
    )
    driver.protocol.set_position_lead(
        enable=True,
        gain=10,
        max_counts=20,
    )
    driver.protocol.set_phase_advance(
        enable=False,
        gain_ppm=60000,
        max_counts=64,
        deadband=16,
    )

    commands = driver.protocol.commands
    assert commands.set_velocity_transient_feedforward.last_args == [
        driver.oid,
        1,
        400,
        750,
        1200,
        10000,
    ]
    assert commands.set_accel_feedforward.last_args == [
        driver.oid,
        0,
        750,
        250,
    ]
    assert commands.set_decoupling_feedforward.last_args == [
        driver.oid,
        1,
        3000,
        4095,
        50,
        65536,
        25000,
        500,
    ]
    assert commands.set_position_lead.last_args == [driver.oid, 1, 10, 20]
    assert commands.set_phase_advance.last_args == [
        driver.oid,
        0,
        60000,
        64,
        16,
    ]


def test_passive_diagnostic_protocol_methods_send_existing_payloads():
    driver = make_driver()
    driver.protocol.commands.stepper_get_position = MockCommand({"pos": -19176})
    driver.protocol.commands.stepper_stats = MockCommand({"position": -26360})
    driver.protocol.commands.stepper_exec_stats = MockCommand(
        {"executed_pos_steps": 39538}
    )
    driver.protocol.commands.stepper_timing_stats = MockCommand({"activation_count": 2})
    driver.protocol.commands.stepper_stop_stats = MockCommand({"stop_count": 1})
    driver.protocol.commands.stepper_perf_stats = MockCommand(
        {"crit_max_cycles": 190000}
    )

    assert driver.protocol.get_step_position() == {"pos": -19176}
    stats = driver.protocol.get_stepper_stats()
    perf = driver.protocol.get_stepper_perf_stats(clear=True)

    assert stats == (
        {"position": -26360},
        {"executed_pos_steps": 39538},
        {"activation_count": 2},
        {"stop_count": 1},
    )
    assert perf == {"crit_max_cycles": 190000}
    assert driver.protocol.commands.stepper_get_position.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_exec_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_timing_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_stop_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_perf_stats.last_args == [driver.oid, 1]


def test_passive_diagnostic_protocol_methods_preserve_errors():
    driver = make_driver()
    driver.protocol.commands.stepper_get_position = None
    with pytest.raises(
        CommandError, match="FOCI_STEP_POSITION is not available before MCU identify"
    ):
        driver.protocol.get_step_position()

    driver.protocol.commands.stepper_get_position = MockCommand({})
    with pytest.raises(
        CommandError, match="FOCI_STEP_POSITION query returned no position"
    ):
        driver.protocol.get_step_position()

    driver.protocol.commands.stepper_stats = MockCommand(None)
    with pytest.raises(
        CommandError, match="FOCI_STEPPER_STATS stats query returned no data"
    ):
        driver.protocol.get_stepper_stats()


def test_active_diagnostic_protocol_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.run_current_step_test(
        axis=1,
        target=250,
        duration_ms=80,
        voltage_limit=12000,
    )
    driver.protocol.run_current_vector_step_test(
        torque_target=0,
        flux_target=300,
        duration_ms=90,
        voltage_limit=13000,
    )
    driver.protocol.run_current_torque_sample_test(
        target=-400,
        flux_target=25,
        sample_delay_ms=5,
        voltage_limit=14000,
    )
    driver.protocol.run_position_torque_offset_sample_test(
        target=500,
        sample_delay_ms=2,
        voltage_limit=15000,
    )
    driver.protocol.run_voltage_step_test(
        uq_ext=256,
        ud_ext=-128,
        sample_delay_ms=3,
    )

    commands = driver.protocol.commands
    assert commands.current_step_test.last_args == [
        driver.oid,
        1,
        250,
        80,
        12000,
    ]
    assert commands.current_vector_step_test.last_args == [
        driver.oid,
        0,
        300,
        90,
        13000,
    ]
    assert commands.current_torque_sample_test.last_args == [
        driver.oid,
        -400,
        25,
        5,
        14000,
    ]
    assert commands.position_torque_offset_sample_test.last_args == [
        driver.oid,
        500,
        2,
        15000,
    ]
    assert commands.voltage_step_test.last_args == [
        driver.oid,
        256,
        -128,
        3,
    ]


def test_core_workflow_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.set_auto_calibrate_on_enable(True)
    driver.protocol.run_calibration()
    driver.protocol.run_commission(2)
    driver.protocol.run_selftest()
    driver.protocol.dump_registers()

    commands = driver.protocol.commands
    assert commands.set_auto_calibrate_on_enable.last_args == [driver.oid, 1]
    assert commands.calibrate.last_args == [driver.oid]
    assert commands.commission.last_args == [driver.oid, 2]
    assert commands.selftest.last_args == [driver.oid]
    assert commands.dump_registers.last_args == [driver.oid]


def test_run_tune_sends_existing_payload():
    driver = make_driver()

    driver.protocol.run_tune(
        profile_code=1,
        mode_code=2,
        inner_lambda=1200,
        theta_e=160,
        current_ringing=7,
        current_bw=500,
        tau_e_us=730,
        tau_e_crosscheck_us=731,
        tau_residual_permille=3,
        inner_warning_flags=8,
    )

    assert driver.protocol.commands.tune.last_args == [
        driver.oid,
        1,
        2,
        1200,
        160,
        7,
        500,
        730,
        731,
        3,
        8,
    ]


def test_preload_active_gains_sends_existing_payloads():
    driver = make_driver()
    gains = {
        "flux_p": 11,
        "flux_i": 12,
        "torque_p": 13,
        "torque_i": 14,
        "velocity_p": 21,
        "velocity_i": 22,
        "position_p": 23,
        "position_i": 24,
        "velocity_limit": 25000,
        "velocity_filter_hz": 80,
        "torque_filter_hz": 90,
        "position_filter_hz": 100,
        "flux_filter_hz": 110,
    }

    driver.protocol.preload_active_gains(gains, voltage_limit=29000)

    commands = driver.protocol.commands
    assert commands.set_voltage_limit.last_args == [driver.oid, 29000]
    assert commands.set_pid_gains.last_args == [driver.oid, 11, 12, 13, 14]
    assert commands.set_position_gains.last_args == [driver.oid, 23, 24, 21, 22]
    assert commands.set_velocity_limit.last_args == [driver.oid, 25000]
    assert commands.set_velocity_filter.last_args == [driver.oid, 80]
    assert commands.set_torque_filter.last_args == [driver.oid, 90]
    assert commands.set_position_filter.last_args == [driver.oid, 100]
    assert commands.set_flux_filter.last_args == [driver.oid, 110]


def test_mock_driver_exposes_protocol_commands_without_driver_command_aliases():
    driver = make_driver()

    assert driver.protocol.commands.set_current is not None
    assert driver.protocol.commands.current_step_test is not None

    for name in (
        "set_current_cmd",
        "calibrate_cmd",
        "commission_cmd",
        "tune_cmd",
        "selftest_cmd",
        "dump_cmd",
        "current_step_test_cmd",
    ):
        assert not hasattr(driver, name)
