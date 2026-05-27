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
    assert commands.trace_fetch is not None
    assert commands.stepper_perf_stats is not None
    assert commands.current_step_test is not None

    assert (
        "stepper_get_position oid=%c",
        "stepper_position oid=%c pos=%i",
        driver.oid,
    ) in mcu.query_cmds
    assert (
        "foci_stepper_perf_stats oid=%c clear=%c",
        commands.STEPPER_PERF_STATS_RESPONSE,
        driver.oid,
    ) in mcu.query_cmds

    registrations = response_names(mcu)
    assert ("foci_dump_value", driver.oid) in registrations
    assert ("foci_dump_done", driver.oid) in registrations
    assert ("foci_calibrate_result", driver.oid) in registrations
    assert ("foci_commission_phase", driver.oid) in registrations
    assert ("foci_commission_result", driver.oid) in registrations
    assert ("foci_tune_result", driver.oid) in registrations
    assert ("foci_selftest_result", driver.oid) in registrations
    assert ("foci_selftest_done", driver.oid) in registrations
    assert ("foci_trace_info_result", driver.oid) in registrations
    assert ("foci_stepper_event", None) in registrations
    assert ("foci_stepper_perf_event", None) in registrations


def test_bind_mcu_keeps_dev_register_read_optional():
    class NoRegisterReadMCU(MockMCU):
        def lookup_query_command(self, send_fmt, recv_fmt, oid=None):
            if send_fmt == "tmc_read_register oid=%c addr=%c":
                raise CommandError("missing tmc_read_register")
            return super().lookup_query_command(send_fmt, recv_fmt, oid=oid)

    driver = make_driver()
    mcu = NoRegisterReadMCU()
    driver.protocol = FociProtocol(driver)

    driver.protocol.bind_mcu(mcu, driver.oid)

    assert driver.protocol.commands.read_register is None
    assert driver.protocol.commands.set_current is not None
    with pytest.raises(
        CommandError, match="Raw register access requires dev firmware build"
    ):
        driver.protocol.read_register(0x6C)


def test_read_register_returns_value_from_optional_query():
    driver = make_driver()
    driver.protocol = FociProtocol(driver)
    driver.protocol.bind_mcu(MockMCU(), driver.oid)
    driver.protocol.commands.read_register = MockCommand({"value": 0x12345678})

    assert driver.protocol.read_register(0x6C) == 0x12345678
    assert driver.protocol.commands.read_register.last_args == [driver.oid, 0x6C]


def test_driver_mcu_identify_binds_protocol_and_keeps_temporary_aliases():
    driver = make_driver(
        stepper_name="stepper_x",
        kinematics=MockCartesianKinematics([["stepper_x"]]),
    )
    driver.mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver._handle_mcu_identify()

    assert driver.protocol.commands.set_current is not None
    assert driver.protocol.commands.set_current is driver.set_current_cmd
    assert driver.protocol.commands.calibrate is driver.calibrate_cmd
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
        inner_warning_flags=4,
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
        4,
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
