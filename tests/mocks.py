"""Mock Klipper objects for FociDriver unit tests.

Provides a factory function that creates a FociDriver with minimal
mocks, bypassing __init__ to avoid Klipper dependencies. Tests set
state fields directly and call methods under test.
"""

from __future__ import annotations

from klipper_foci.driver import FociDriver
from klipper_foci.registry import FociGlobalConfig
from klipper_foci.state import FociRuntimeState


class CommandError(Exception):
    """Stand-in for Klipper's printer.command_error."""


class MockPrinter:
    """Minimal printer mock for FociDriver."""

    def __init__(self):
        self._objects: dict[str, object] = {}
        self._object_lists: dict[str, list[tuple[str, object]]] = {}
        self._event_handlers: dict[str, list[object]] = {}
        self._reactor = MockReactor()

    def lookup_object(self, name, default=None):
        return self._objects.get(name, default)

    def lookup_objects(self, module=None):
        return list(self._object_lists.get(module, []))

    def register_event_handler(self, event, callback):
        self._event_handlers.setdefault(event, []).append(callback)

    def load_object(self, config, name):
        if name in self._objects:
            return self._objects[name]
        if name == "foci":
            obj = FociGlobalConfig(config.getsection("foci"))
            self._objects[name] = obj
            return obj
        return self.lookup_object(name)

    def command_error(self, msg):
        return CommandError(msg)

    def config_error(self, msg):
        return CommandError(msg)

    def get_reactor(self):
        return self._reactor


class MockToolhead:
    """Minimal toolhead mock."""

    def __init__(self, kinematics=None):
        self._kinematics = kinematics or MockNoneKinematics()
        self._homed_axes = ""
        self.last_move_time = 0.0

    def get_kinematics(self):
        return self._kinematics

    def get_last_move_time(self):
        return self.last_move_time

    def get_status(self, _time):
        return {"homed_axes": self._homed_axes}

    def wait_moves(self):
        pass


class MockNoneKinematics:
    """NoneKinematics — no get_rails, no axes."""

    pass


class MockCartesianKinematics:
    """Cartesian kinematics with configurable rails.

    Matches both Klipper and Kalico: exposes ``rails`` attribute
    (used by _invalidate_homing) and ``get_steppers()`` (flattened).
    """

    def __init__(self, stepper_names=None):
        stepper_names = stepper_names or [["stepper_x"], ["stepper_y"], ["stepper_z"]]
        self.rails = []
        for names in stepper_names:
            self.rails.append(MockRail(names))
        self._cleared_axes = None

    def get_steppers(self):
        return [s for rail in self.rails for s in rail.get_steppers()]

    def clear_homing_state(self, axes):
        self._cleared_axes = axes


class MockCoreXYKinematics(MockCartesianKinematics):
    """CoreXY kinematics — class name used for coupling lookup."""

    # The COUPLED_AXES table uses type(kin).__name__
    pass


# Give it the right class name for the coupling table lookup
MockCoreXYKinematics.__name__ = "CoreXYKinematics"


class MockRail:
    """Mock rail containing named steppers."""

    def __init__(self, stepper_names):
        self._steppers = [
            stepper if isinstance(stepper, MockStepper) else MockStepper(stepper)
            for stepper in stepper_names
        ]

    def get_steppers(self):
        return self._steppers


class MockStepper:
    """Mock stepper with a name."""

    def __init__(
        self,
        name,
        oid=0,
        mcu_position=0,
        dir_inverted=False,
        step_dist=0.01,
        step_history=None,
    ):
        self._name = name
        self._oid = oid
        self._mcu_position = mcu_position
        self._dir_inverted = dir_inverted
        self._step_dist = step_dist
        self._step_history = step_history or []
        self._mcu = MockClockMCU()

    def get_name(self):
        return self._name

    def get_oid(self):
        return self._oid

    def get_mcu_position(self):
        return self._mcu_position

    def get_dir_inverted(self):
        return self._dir_inverted, None

    def get_step_dist(self):
        return self._step_dist

    def get_mcu(self):
        return self._mcu

    def dump_steps(self, count, start_clock, end_clock):
        data = sorted(
            [
                step
                for step in self._step_history
                if start_clock < step.last_clock and end_clock > step.first_clock
            ],
            key=lambda step: step.first_clock,
            reverse=True,
        )[:count]
        return data, len(data)


class MockClockMCU:
    """Mock MCU clock conversion."""

    def print_time_to_clock(self, print_time):
        return int(print_time * 1000)


class MockEnableLine:
    """Mock stepper enable line."""

    def __init__(self):
        self._enabled = False

    def is_motor_enabled(self):
        return self._enabled

    def motor_enable(self, print_time):
        self._enabled = True

    def motor_disable(self, print_time):
        self._enabled = False

    def register_state_callback(self, callback):
        pass


class MockStepperEnable:
    """Mock stepper_enable module."""

    def __init__(self):
        self._lines = {}

    def lookup_enable(self, stepper_name):
        if stepper_name not in self._lines:
            self._lines[stepper_name] = MockEnableLine()
        return self._lines[stepper_name]


class MockGCmd:
    """Mock GCode command object for command handlers."""

    def __init__(self, params=None):
        self._params = params or {}
        self._responses = []
        self.last_info = None

    def get(self, key, default=None):
        return self._params.get(key, default)

    def get_int(self, key, default=None, minval=None, maxval=None):
        if key not in self._params:
            if default is None:
                raise CommandError("Missing parameter '%s'" % key)
            return default
        value = int(self._params[key])
        if minval is not None and value < minval:
            raise CommandError("Parameter '%s' below minimum" % key)
        if maxval is not None and value > maxval:
            raise CommandError("Parameter '%s' above maximum" % key)
        return value

    def get_float(self, key, default=None, minval=None, maxval=None):
        if key not in self._params:
            if default is None:
                raise CommandError("Missing parameter '%s'" % key)
            return default
        value = float(self._params[key])
        if minval is not None and value < minval:
            raise CommandError("Parameter '%s' below minimum" % key)
        if maxval is not None and value > maxval:
            raise CommandError("Parameter '%s' above maximum" % key)
        return value

    def error(self, msg):
        return CommandError(msg)

    def respond_info(self, msg):
        self._responses.append(msg)
        self.last_info = msg


class MockGCode:
    """Mock gcode module."""

    def __init__(self):
        self._mux_commands = []
        self._responses = []

    def register_mux_command(self, *args, **kwargs):
        self._mux_commands.append((args, kwargs))

    def respond_info(self, msg):
        self._responses.append(msg)


class MockReactor:
    """Minimal reactor for _ensure_calibrated."""

    def __init__(self):
        self._time = 0.0
        self.completion_result = None

    def monotonic(self):
        return self._time

    def completion(self):
        return MockCompletion(self.completion_result)

    def pause(self, deadline):
        self._time = deadline
        return self._time


class MockCompletion:
    """Reactor completion mock."""

    def __init__(self, result=None):
        self._result = result

    def wait(self, deadline):
        return self._result

    def complete(self, result):
        self._result = result


class MockCommand:
    """Mock firmware command."""

    def __init__(self, response=None):
        self.last_args = None
        self.response = response

    def send(self, args=None):
        self.last_args = args
        return self.response


class MockSerial:
    """Mock MCU serial response registry."""

    def __init__(self):
        self.responses = []

    def register_response(self, callback, name, oid=None):
        self.responses.append((callback, name, oid))


class MockMCU:
    """Mock Klipper MCU object with config-build callbacks."""

    def __init__(self, name="foci", allowed_pins=None):
        self.name = name
        self.allowed_pins = set(allowed_pins) if allowed_pins is not None else None
        self._next_oid = 1
        self._config_callbacks = []
        self.config_cmds = []
        self.query_cmds = []
        self._serial = MockSerial()

    def create_oid(self):
        oid = self._next_oid
        self._next_oid += 1
        return oid

    def register_config_callback(self, callback):
        self._config_callbacks.append(callback)

    def run_config_callbacks(self):
        for callback in list(self._config_callbacks):
            callback()

    def add_config_cmd(self, cmd):
        self.config_cmds.append(cmd)

    def alloc_command_queue(self):
        return object()

    def lookup_command(self, _fmt, cq=None):
        return MockCommand()

    def lookup_query_command(self, _send_fmt, _recv_fmt, oid=None):
        self.query_cmds.append((_send_fmt, _recv_fmt, oid))
        return MockCommand()


class MockPins:
    """Mock pins object that resolves chip-prefixed virtual FOCI pins."""

    def __init__(self, chips):
        self._chips = chips

    def parse_pin(self, pin, can_invert=False):
        chip_name, pin_name = pin.split(":", 1)
        chip = self._chips[chip_name]
        if chip.allowed_pins is not None and pin_name not in chip.allowed_pins:
            raise CommandError("Unknown pin %s on chip %s" % (pin_name, chip_name))
        return {"chip": chip, "pin": pin_name}


class MockConfig:
    """Minimal config section object."""

    def __init__(self, printer, sections, name):
        self._printer = printer
        self._sections = sections
        self._name = name

    def get_name(self):
        return self._name

    def get_printer(self):
        return self._printer

    def has_section(self, name):
        return name in self._sections

    def getsection(self, name):
        return MockConfig(self._printer, self._sections, name)

    def get(self, key, default=None):
        return self._sections.get(self._name, {}).get(key, default)

    def getint(self, key, default=None, minval=None, maxval=None):
        value = self.get(key, default)
        if value is None:
            return None
        value = int(value)
        if minval is not None and value < minval:
            raise self.error("%s below minimum" % key)
        if maxval is not None and value > maxval:
            raise self.error("%s above maximum" % key)
        return value

    def getfloat(self, key, default=None, above=None):
        value = self.get(key, default)
        if value is None:
            return None
        value = float(value)
        if above is not None and value <= above:
            raise self.error("%s must be above %s" % (key, above))
        return value

    def getboolean(self, key, default=False):
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)

    def getchoice(self, key, choices, default=None):
        value = self.get(key, default)
        if value not in choices:
            raise self.error("%s must be one of %s" % (key, sorted(choices)))
        return choices[value]

    def error(self, msg):
        return CommandError(msg)


def make_config_printer(stepper_sections, chips=None, kinematics=None, foci_mode=None):
    """Create a printer/config section set for FociDriver construction."""
    chips = chips or {"foci": MockMCU("foci")}
    sections = {}
    if foci_mode is not None:
        sections["foci"] = {"mode": foci_mode}
    stepper_names = []
    next_stepper_oid = 10
    for name, values in stepper_sections.items():
        section = {
            "microsteps": values.get("microsteps", 20),
            "full_steps_per_rotation": values.get("full_steps_per_rotation", 200),
            "step_pin": values["step_pin"],
            "dir_pin": values.get("dir_pin", "foci:DIR0"),
        }
        sections[name] = section
        stepper_names.append(MockStepper(name, values.get("oid", next_stepper_oid)))
        next_stepper_oid += 1
        sections["foci " + name] = {
            "run_current": values.get("run_current", 0.8),
            "encoder_ppr": values.get("encoder_ppr", 1000),
            "voltage_limit": values.get("voltage_limit", 16000),
        }
    printer = MockPrinter()
    printer._objects["gcode"] = MockGCode()
    printer._objects["pins"] = MockPins(chips)
    printer._objects["stepper_enable"] = MockStepperEnable()
    printer._objects["toolhead"] = MockToolhead(
        kinematics or MockCartesianKinematics([[stepper] for stepper in stepper_names])
    )
    return printer, chips, sections


def make_config_driver(printer, sections, name):
    """Construct a real FociDriver from mocked config sections."""
    return FociDriver(MockConfig(printer, sections, name))


def make_driver(
    stepper_name="manual_stepper stepper_x",
    kinematics=None,
    homed_axes="",
) -> FociDriver:
    """Create a FociDriver with mocked dependencies, bypassing __init__.

    Returns a driver with all state fields at their defaults and minimal
    mock objects attached. Tests can then set fields directly and call
    methods.
    """
    driver = FociDriver.__new__(FociDriver)

    # Identity
    driver.name = "foci " + stepper_name
    driver.stepper_name = stepper_name
    driver._current_torque_sample_details = {}
    driver._current_torque_sample_labels = {}
    driver.oid = 0
    driver.stepper_oid = None
    driver.channel = 0

    # Printer and objects
    toolhead = MockToolhead(kinematics)
    toolhead._homed_axes = homed_axes
    printer = MockPrinter()
    printer._objects["gcode"] = MockGCode()
    printer._objects["toolhead"] = toolhead
    printer._objects["stepper_enable"] = MockStepperEnable()
    driver.printer = printer

    # Volatile state (matches __init__ lines 700-719)
    driver.state = FociRuntimeState()
    driver._enable_patched = False

    # Commission polling state
    driver._commission_done = False
    driver._commission_result = None
    driver._commission_error_code = 0
    driver._last_phase_id = None
    driver._commission_details = []

    # Selftest streaming state
    driver._selftest_results = []
    driver._selftest_complete = False
    driver._selftest_status = 0
    driver._homing_move_start_times = {}

    # Config values (needed by some methods)
    driver.microsteps = 20
    driver.full_steps = 200
    driver.encoder_ppr = 1000
    driver.encoder_reversed = False
    driver.run_current = 0.8
    driver.voltage_limit = 16000
    driver.velocity_feedforward = False
    driver.velocity_feedforward_multiplier = 1
    driver.velocity_transient_feedforward = False
    driver.velocity_transient_lead_time_us = 0
    driver.velocity_transient_gain = 0
    driver.velocity_transient_max_offset = 0
    driver.velocity_transient_rate_hz = 1000
    driver.accel_feedforward = False
    driver.accel_feedforward_accel_gain = 1000
    driver.accel_feedforward_decel_gain = 1000
    driver.decoupling_feedforward = False
    driver.decoupling_r_int = 3000
    driver.decoupling_l_int = 4095
    driver.decoupling_pole_pairs = 50
    driver.decoupling_position_units_per_rev = 65536
    driver.decoupling_f_pwm_hz = 25000
    driver.decoupling_max_offset = 500
    driver.position_lead = False
    driver.position_lead_gain = 0
    driver.position_lead_max_counts = 0
    driver.phase_advance = False
    driver.phase_advance_gain_ppm = 0
    driver.phase_advance_max_counts = 0
    driver.phase_advance_deadband = 16

    # Identified values (from prior commission, used by AUTOTUNE)
    driver.identified_r_int = None
    driver.identified_l_int = None
    driver.identified_lambda_us = 0
    driver.identified_theta_e_us = 160
    driver.identified_ringing_count = 7
    driver.identified_bandwidth_hz = 0

    # Phase 1 inner-confidence fields (added 2026-04-30). Default to None
    # so `_resolve_inner_confidence` exercises the host-default fallback.
    driver.identified_tau_e_us = None
    driver.identified_tau_e_crosscheck_us = None
    driver.identified_tau_residual_permille = None
    driver.identified_inner_warning_flags = None

    # Persisted gain fields
    driver.pid_flux_p = None
    driver.pid_flux_i = None
    driver.pid_torque_p = None
    driver.pid_torque_i = None
    driver.pid_position_p = None
    driver.pid_position_i = None
    driver.pid_velocity_p = None
    driver.pid_velocity_i = None
    driver.pid_velocity_limit = None

    # Commissioned fallback gains (from SAVE_CONFIG)
    driver.commissioned_velocity_p = None
    driver.commissioned_velocity_i = None
    driver.commissioned_position_p = None
    driver.commissioned_position_i = None
    driver.commissioned_velocity_limit = None

    # Persisted status and filter config
    driver.autotune_status = None
    driver.velocity_filter_hz = 0
    driver.torque_filter_hz = 0
    driver.position_filter_hz = 0
    driver.flux_filter_hz = 0

    # Mock firmware commands (used by _ensure_calibrated, etc.)
    driver.set_current_cmd = MockCommand()
    driver.set_encoder_cmd = MockCommand()
    driver.set_encoder_dir_cmd = MockCommand()
    driver.calibrate_cmd = MockCommand()
    driver.commission_cmd = MockCommand()
    driver.tune_cmd = MockCommand()
    driver.selftest_cmd = MockCommand()
    driver.set_pid_gains_cmd = MockCommand()
    driver.set_position_gains_cmd = MockCommand()
    driver.set_velocity_feedforward_cmd = MockCommand()
    driver.set_velocity_transient_feedforward_cmd = MockCommand()
    driver.set_accel_feedforward_cmd = MockCommand()
    driver.set_decoupling_feedforward_cmd = MockCommand()
    driver.set_position_lead_cmd = MockCommand()
    driver.set_phase_advance_cmd = MockCommand()
    driver.set_velocity_limit_cmd = MockCommand()
    driver.set_voltage_limit_cmd = MockCommand()
    driver.current_step_test_cmd = MockCommand()
    driver.current_vector_step_test_cmd = MockCommand()
    driver.current_torque_sample_test_cmd = MockCommand()
    driver.position_torque_offset_sample_test_cmd = MockCommand()
    driver.voltage_step_test_cmd = MockCommand()
    driver.set_velocity_filter_cmd = MockCommand()
    driver.set_torque_filter_cmd = MockCommand()
    driver.set_position_filter_cmd = MockCommand()
    driver.set_flux_filter_cmd = MockCommand()
    driver.set_auto_calibrate_on_enable_cmd = MockCommand()
    driver.trace_start_cmd = MockCommand()
    driver.trace_stop_cmd = MockCommand()
    driver.stepper_stats_cmd = MockCommand()
    driver.stepper_exec_stats_cmd = MockCommand()
    driver.stepper_timing_stats_cmd = MockCommand()
    driver.stepper_stop_stats_cmd = MockCommand()

    return driver
