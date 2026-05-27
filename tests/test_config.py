"""Tests for FOCI MCU config-build command emission."""

import pytest

from tests.mocks import CommandError, MockMCU, make_config_driver, make_config_printer


def test_package_entry_points_import_driver_and_global_config():
    import klipper_foci
    from klipper_foci.driver import FociDriver
    from klipper_foci.registry import FociGlobalConfig

    assert klipper_foci.FociDriver is FociDriver
    assert klipper_foci.FociGlobalConfig is FociGlobalConfig
    assert callable(klipper_foci.load_config)
    assert callable(klipper_foci.load_config_prefix)


DEFAULT_COMMANDS = {
    "FOCI_SELFTEST",
    "FOCI_COMMISSION",
    "FOCI_AUTOTUNE",
    "DUMP_FOCI",
    "DUMP_TMC",
    "FOCI_SET_GAINS",
    "FOCI_SET_INNER_GAINS",
    "FOCI_SET_CURRENT",
    "FOCI_SET_VELOCITY_FEEDFORWARD",
}

ADVANCED_COMMANDS = {
    "FOCI_STEP_POSITION",
    "FOCI_STEPPER_STATS",
    "FOCI_DISPATCH_STATS",
    "FOCI_TRACE_START",
    "FOCI_TRACE_STOP",
    "FOCI_TRACE",
}

EXPERT_COMMANDS = {
    "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
    "FOCI_SET_ACCEL_FEEDFORWARD",
    "FOCI_SET_DECOUPLING_FEEDFORWARD",
    "FOCI_SET_POSITION_LEAD",
    "FOCI_SET_PHASE_ADVANCE",
    "FOCI_SET_VOLTAGE_LIMIT",
    "FOCI_CURRENT_STEP_TEST",
    "FOCI_CURRENT_VECTOR_STEP_TEST",
    "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
    "FOCI_POSITION_TORQUE_OFFSET_TEST",
    "FOCI_VOLTAGE_STEP_TEST",
}


def registered_command_names(printer):
    gcode = printer.lookup_object("gcode")
    return {args[0] for args, _kwargs in gcode._mux_commands}


def build_driver_with_mode(mode=None):
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        },
        foci_mode=mode,
    )
    make_config_driver(printer, sections, "foci stepper_x")
    return printer


def test_absent_foci_section_registers_default_commands_only():
    printer = build_driver_with_mode(None)

    assert registered_command_names(printer) == DEFAULT_COMMANDS


def test_explicit_default_mode_registers_default_commands_only():
    printer = build_driver_with_mode("default")

    assert registered_command_names(printer) == DEFAULT_COMMANDS


def test_advanced_mode_registers_default_and_advanced_commands_only():
    printer = build_driver_with_mode("advanced")

    assert registered_command_names(printer) == DEFAULT_COMMANDS | ADVANCED_COMMANDS
    assert "FOCI_VOLTAGE_STEP_TEST" not in registered_command_names(printer)


def test_expert_mode_registers_default_advanced_and_expert_commands():
    printer = build_driver_with_mode("expert")

    assert registered_command_names(printer) == (
        DEFAULT_COMMANDS | ADVANCED_COMMANDS | EXPERT_COMMANDS
    )


def test_developer_mode_matches_expert_until_dev_only_commands_exist():
    printer = build_driver_with_mode("developer")

    assert registered_command_names(printer) == (
        DEFAULT_COMMANDS | ADVANCED_COMMANDS | EXPERT_COMMANDS
    )


def test_invalid_global_foci_mode_reports_valid_modes():
    with pytest.raises(CommandError) as excinfo:
        build_driver_with_mode("unsafe")

    message = str(excinfo.value)
    assert "mode" in message
    for mode in ("default", "advanced", "expert", "developer"):
        assert mode in message


def test_registry_resolves_component_handler_and_inline_help():
    from klipper_foci.registry import GcodeCommandSpec, register_gcode_commands

    class Component:
        def handle(self, gcmd):
            return None

    class Driver:
        stepper_name = "stepper_x"

        def __init__(self):
            self.component = Component()

    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")
    gcode._mux_commands.clear()

    driver = Driver()
    specs = (
        GcodeCommandSpec(
            name="FOCI_TEST",
            min_mode="default",
            component="component",
            handler_name="handle",
            help_text="test command",
        ),
    )

    register_gcode_commands(driver, gcode, "default", command_specs=specs)

    args, kwargs = gcode._mux_commands[0]
    assert args[:3] == ("FOCI_TEST", "STEPPER", "stepper_x")
    assert args[3].__self__ is driver.component
    assert args[3].__func__ is driver.component.handle.__func__
    assert kwargs["desc"] == "test command"


def test_dump_commands_register_register_dump_workflow_handler():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    dump_handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in {"DUMP_FOCI", "DUMP_TMC"}
    }

    assert dump_handlers["DUMP_FOCI"].__self__.__class__.__name__ == (
        "RegisterDumpWorkflow"
    )
    assert dump_handlers["DUMP_TMC"].__self__.__class__.__name__ == (
        "RegisterDumpWorkflow"
    )


def test_default_control_commands_register_controls_workflow_handlers():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_SET_GAINS",
        "FOCI_SET_INNER_GAINS",
        "FOCI_SET_CURRENT",
        "FOCI_SET_VELOCITY_FEEDFORWARD",
    }

    handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "ControlsWorkflow"
        for handler in handlers.values()
    )


def test_expert_control_commands_register_controls_workflow_handlers():
    printer = build_driver_with_mode("expert")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "FOCI_SET_ACCEL_FEEDFORWARD",
        "FOCI_SET_DECOUPLING_FEEDFORWARD",
        "FOCI_SET_POSITION_LEAD",
        "FOCI_SET_PHASE_ADVANCE",
        "FOCI_SET_VOLTAGE_LIMIT",
    }

    handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "ControlsWorkflow"
        for handler in handlers.values()
    )


def test_homing_events_register_homing_workflow_callbacks():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    make_config_driver(printer, sections, "foci stepper_x")

    for event in (
        "homing:home_rails_begin",
        "homing:homing_move_begin",
        "homing:homing_move_end",
    ):
        callbacks = printer._event_handlers[event]
        assert callbacks[0].__self__.__class__.__name__ == "HomingWorkflow"


def test_commission_registers_commissioning_workflow_handler():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    handler = next(
        args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_COMMISSION"
    )

    assert handler.__self__.__class__.__name__ == "CommissioningWorkflow"


def test_selftest_registers_selftest_workflow_handler():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    handler = next(
        args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_SELFTEST"
    )

    assert handler.__self__.__class__.__name__ == "SelftestWorkflow"


def test_autotune_registers_autotune_workflow_handler():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    handler = next(
        args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_AUTOTUNE"
    )

    assert handler.__self__.__class__.__name__ == "AutotuneWorkflow"


def test_observation_diagnostics_register_diagnostics_workflow_handlers():
    printer = build_driver_with_mode("advanced")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_STEP_POSITION",
        "FOCI_STEPPER_STATS",
        "FOCI_DISPATCH_STATS",
    }

    handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "DiagnosticsWorkflow"
        for handler in handlers.values()
    )


def test_active_diagnostics_register_diagnostics_workflow_handlers():
    printer = build_driver_with_mode("expert")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_CURRENT_STEP_TEST",
        "FOCI_CURRENT_VECTOR_STEP_TEST",
        "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "FOCI_POSITION_TORQUE_OFFSET_TEST",
        "FOCI_VOLTAGE_STEP_TEST",
    }

    handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "DiagnosticsWorkflow"
        for handler in handlers.values()
    )


def test_trace_commands_register_legacy_trace_workflow_handlers():
    printer = build_driver_with_mode("advanced")
    gcode = printer.lookup_object("gcode")
    command_names = {"FOCI_TRACE_START", "FOCI_TRACE_STOP", "FOCI_TRACE"}

    handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "LegacyTraceWorkflow"
        for handler in handlers.values()
    )


def test_foci_driver_no_longer_exposes_gcode_command_methods():
    from klipper_foci.driver import FociDriver

    command_methods = [name for name in dir(FociDriver) if name.startswith("cmd_FOCI_")]

    assert command_methods == []
    assert not hasattr(FociDriver, "cmd_DUMP_FOCI")


def test_registry_no_longer_points_at_driver_component():
    from klipper_foci.registry import GCODE_COMMANDS

    assert all(spec.component != "driver" for spec in GCODE_COMMANDS)


def test_same_mcu_dual_channel_uses_stepper_oids_without_foci_config():
    printer, chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
            },
        }
    )
    mcu = chips["foci"]
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    mcu.run_config_callbacks()
    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    assert mcu.config_commands == []
    assert driver_x.oid == 10
    assert driver_y.oid == 12


def test_same_mcu_dual_channel_response_handlers_use_distinct_oids():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
            },
        }
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    response_oids = {
        (name, oid) for _callback, name, oid in driver_x.mcu._serial.responses
    }
    assert ("foci_commission_result", 10) in response_oids
    assert ("foci_commission_result", 12) in response_oids
    assert ("foci_trace_info_result", 10) in response_oids
    assert ("foci_trace_info_result", 12) in response_oids


def test_perf_stats_query_format_includes_scheduler_attribution_fields():
    printer, chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")

    driver._handle_mcu_identify()

    send_fmt, recv_fmt, oid = next(
        query
        for query in chips["foci"].query_commands
        if query[0] == "foci_stepper_perf_stats oid=%c clear=%c"
    )
    assert send_fmt == "foci_stepper_perf_stats oid=%c clear=%c"
    assert oid == 10
    assert "scheduler_cycles_max=%u" in recv_fmt
    assert "scheduler_cycles_events_at_max=%u" in recv_fmt
    assert "scheduler_cycles_per_event_max=%u" in recv_fmt
    assert "scheduler_cycles_per_event_floor3_max=%u" in recv_fmt
    assert "scheduler_full_count=%u" in recv_fmt


def test_configured_voltage_limit_is_sent_on_connect():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "voltage_limit": 29000,
            },
        }
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert driver.voltage_limit == 29000
    assert driver.protocol.commands.set_voltage_limit.last_args == [10, 29000]


def test_configured_voltage_limit_accepts_raw_chip_range():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "voltage_limit": 0,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
                "voltage_limit": 32767,
            },
        }
    )

    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    assert driver_x.voltage_limit == 0
    assert driver_y.voltage_limit == 32767


def test_configured_voltage_limit_rejects_values_above_chip_range():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "voltage_limit": 32768,
            },
        }
    )

    with pytest.raises(CommandError, match="voltage_limit above maximum"):
        make_config_driver(printer, sections, "foci stepper_x")


def test_dual_mcu_single_channel_uses_stepper_oids_without_foci_config():
    mcu_x = MockMCU("foci_x")
    mcu_y = MockMCU("foci_y")
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci_x:STEP0",
                "dir_pin": "foci_x:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci_y:STEP0",
                "dir_pin": "foci_y:DIR0",
                "oid": 12,
            },
        },
        chips={"foci_x": mcu_x, "foci_y": mcu_y},
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    mcu_x.run_config_callbacks()
    mcu_y.run_config_callbacks()
    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    assert mcu_x.config_commands == []
    assert mcu_y.config_commands == []
    assert driver_x.oid == 10
    assert driver_y.oid == 12


def test_dual_mcu_drivers_keep_runtime_state_separate():
    mcu_x = MockMCU("foci_x")
    mcu_y = MockMCU("foci_y")
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci_x:STEP0",
                "dir_pin": "foci_x:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci_y:STEP0",
                "dir_pin": "foci_y:DIR0",
                "oid": 12,
            },
        },
        chips={"foci_x": mcu_x, "foci_y": mcu_y},
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    driver_x.state.operation_lock = True
    driver_x.state.inhibited = True
    driver_x.trace.trace_info = {"owner": "x"}

    assert driver_y.state.operation_lock is False
    assert driver_y.state.inhibited is False
    assert driver_y.trace.trace_info is None


def test_step1_rejected_when_mcu_pin_dictionary_lacks_step1():
    mcu = MockMCU(
        "foci",
        allowed_pins={"STEP0", "DIR0", "ENA0"},
    )
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 10,
            },
        },
        chips={"foci": mcu},
    )

    with pytest.raises(CommandError, match="Unknown pin STEP1"):
        make_config_driver(printer, sections, "foci stepper_x")


def test_saved_commission_and_tune_fields_are_accepted_on_restart():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    sections["foci stepper_x"].update(
        {
            "identified_r_count_milli": 1792,
            "identified_l_count_micro": 2046,
            "identified_lambda_us": 0,
            "identified_theta_e_us": 160,
            "identified_ringing_count": 7,
            "identified_bandwidth_hz": 0,
            "identified_tau_e_us": 1154,
            "identified_tau_e_crosscheck_us": 3821,
            "identified_tau_residual_permille": 1000,
            "identified_inner_warning_flags": 36,
            "identified_j_eff": 12345,
            "identified_b_eff": 678,
            "autotune_profile": "conservative",
            "autotune_mode": "nominal",
            "autotune_status": "commissioned",
        }
    )

    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert driver.identified_r_count_milli == 1792
    assert driver.identified_l_count_micro == 2046
    assert driver.identified_tau_e_us == 1154
    assert driver.identified_j_eff == 12345
    assert driver.identified_b_eff == 678
    assert driver.autotune_profile == "conservative"
    assert driver.autotune_mode == "nominal"
    assert driver.autotune_status == "commissioned"
