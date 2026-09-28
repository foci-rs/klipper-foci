"""Mock Klipper objects for FociDriver unit tests.

Provides a factory function that creates a FociDriver with minimal
mocks, bypassing __init__ to avoid Klipper dependencies. Tests set
state fields directly and call methods under test.
"""

from __future__ import annotations

from types import SimpleNamespace

from klipper_foci.autotune import AutotuneWorkflow
from klipper_foci.commissioning import CommissioningWorkflow
from klipper_foci.config import FociControlSettings, parse_driver_config
from klipper_foci.controls import ControlsWorkflow
from klipper_foci.diagnostics import DiagnosticsWorkflow
from klipper_foci.driver import FociDriver
from klipper_foci.dump import RegisterDumpWorkflow
from klipper_foci.homing import HomingWorkflow
from klipper_foci.protocol import FociProtocol
from klipper_foci.registry import FociGlobalConfig
from klipper_foci.selftest import SelftestWorkflow
from klipper_foci.state import FociRuntimeState
from klipper_foci.virtual_endstop import FociVirtualEndstop

SAMPLE_ACTIVE_GAINS = {
    "flux_p": 256,
    "flux_i": 416,
    "torque_p": 256,
    "torque_i": 416,
    "velocity_p": 1152,
    "velocity_i": 0,
    "position_p": 640,
    "position_i": 0,
    "velocity_limit": 500000,
    "velocity_filter_hz": 0,
    "torque_filter_hz": 0,
    "position_filter_hz": 200,
    "flux_filter_hz": 0,
}

SAMPLE_COMMISSION_RESULT = {
    "status": 0,
    "flux_p": 256,
    "flux_i": 416,
    "torque_p": 256,
    "torque_i": 416,
    "r_count_milli": 1706,
    "l_count_micro": 1245,
    "lambda_us": 0,
    "theta_e_us": 160,
    "theta_source": 1,
    "bandwidth_hz": 0,
}


def complete_commission_result():
    result = SAMPLE_COMMISSION_RESULT.copy()
    result.update(
        {
            "fallback_velocity_p": 1152,
            "fallback_velocity_i": 0,
            "fallback_position_p": 640,
            "inner_warning_flags": 0,
        }
    )
    return result


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
        self._position = [100.0, 100.0, 0.0, 0.0]
        self._axis_minimum = [0.0, 0.0, 0.0, 0.0]
        self._axis_maximum = [200.0, 200.0, 0.0, 0.0]
        self.last_move_time = 0.0
        self.max_velocity = 300.0
        self.max_accel = 8000.0

    def get_kinematics(self):
        return self._kinematics

    def get_last_move_time(self):
        return self.last_move_time

    def set_bounds(self, *, x_min=0.0, x_max=200.0, y_min=0.0, y_max=200.0):
        self._axis_minimum[0] = float(x_min)
        self._axis_maximum[0] = float(x_max)
        self._axis_minimum[1] = float(y_min)
        self._axis_maximum[1] = float(y_max)

    def set_position(self, *, x=100.0, y=100.0, z=0.0):
        self._position[0] = float(x)
        self._position[1] = float(y)
        self._position[2] = float(z)

    def get_status(self, _time):
        return {
            "homed_axes": self._homed_axes,
            "position": tuple(self._position),
            "axis_minimum": tuple(self._axis_minimum),
            "axis_maximum": tuple(self._axis_maximum),
            "max_velocity": self.max_velocity,
            "max_accel": self.max_accel,
        }

    def wait_moves(self):
        pass


class MockNoneKinematics:
    """NoneKinematics, no get_rails, no axes."""

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
    """CoreXY kinematics, class name used for coupling lookup."""

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
        self.note_homing_end_calls = 0

    def get_name(self):
        return self._name

    def note_homing_end(self):
        self.note_homing_end_calls += 1

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
    """Mock stepper enable line.

    Mirrors real Klipper's EnableTracking and StepperEnablePin: state
    callbacks run before is_enabled flips, and enable_count tracks the
    pin's reference count, so re-entrant enables leave it above 1.
    """

    def __init__(self):
        self._enabled = False
        self._callbacks = []
        self.enable_count = 0
        self.real_disable_count = 0

    def is_motor_enabled(self):
        return self._enabled

    def motor_enable(self, print_time):
        if not self._enabled:
            for callback in self._callbacks:
                callback(print_time, True)
            self.enable_count += 1
            self._enabled = True

    def motor_disable(self, print_time):
        if self._enabled:
            for callback in self._callbacks:
                callback(print_time, False)
            self.enable_count -= 1
            self._enabled = False
            self.real_disable_count += 1

    def register_state_callback(self, callback):
        self._callbacks.append(callback)


class MockStepperEnable:
    """Mock stepper_enable module."""

    def __init__(self):
        self._lines = {}

    def lookup_enable(self, stepper_name):
        if stepper_name not in self._lines:
            self._lines[stepper_name] = MockEnableLine()
        return self._lines[stepper_name]


class MockPrintStats:
    """Mock print_stats module."""

    def __init__(self, state="standby"):
        self.state = state

    def get_status(self, _eventtime):
        return {"state": self.state}


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
                raise CommandError(f"Missing parameter '{key}'")
            return default
        value = int(self._params[key])
        if minval is not None and value < minval:
            raise CommandError(f"Parameter '{key}' below minimum")
        if maxval is not None and value > maxval:
            raise CommandError(f"Parameter '{key}' above maximum")
        return value

    def get_float(self, key, default=None, minval=None, maxval=None):
        if key not in self._params:
            if default is None:
                raise CommandError(f"Missing parameter '{key}'")
            return default
        value = float(self._params[key])
        if minval is not None and value < minval:
            raise CommandError(f"Parameter '{key}' below minimum")
        if maxval is not None and value > maxval:
            raise CommandError(f"Parameter '{key}' above maximum")
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
        self._scripts = []

    def register_mux_command(self, *args, **kwargs):
        self._mux_commands.append((args, kwargs))

    def respond_info(self, msg):
        self._responses.append(msg)

    def run_script_from_command(self, command):
        self._scripts.append(command)


class MockReactor:
    """Minimal reactor for _ensure_calibrated."""

    def __init__(self):
        self._time = 0.0
        self.completion_result = None
        self._prevent_pause_count = 0

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
        self.call_count = 0
        self.response = response

    def send(self, args=None):
        self.call_count += 1
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

    def __init__(self, name="foci", allowed_pins=None, constants=None):
        self.name = name
        self.allowed_pins = set(allowed_pins) if allowed_pins is not None else None
        self.constants = dict(constants or {})
        self._next_oid = 1
        self._config_callbacks = []
        self.config_commands = []
        self.command_formats = []
        self.query_commands = []
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
        self.config_commands.append(cmd)

    def alloc_command_queue(self):
        return object()

    def lookup_command(self, _fmt, cq=None):
        self.command_formats.append(_fmt)
        return MockCommand()

    def lookup_query_command(self, _send_fmt, _recv_fmt, oid=None):
        self.query_commands.append((_send_fmt, _recv_fmt, oid))
        if _send_fmt == "foci_adc_vm_offset oid=%c":
            return MockCommand(
                {
                    "offset_raw": 33662,
                    "sample_count": 8,
                    "status": 0,
                }
            )
        if _send_fmt == "foci_stall_query oid=%c":
            return MockCommand(
                {
                    "latched": 1,
                    "peak_error_units": 1234,
                    "trigger_tick": 7,
                    "clamp_active": 0,
                    "trigger_path": 2,
                    "peak_margin_delta_units": 45,
                }
            )
        return MockCommand()

    def get_constants(self):
        return self.constants.copy()

    def get_name(self):
        return self.name


class MockPins:
    """Mock pins object that resolves chip-prefixed virtual FOCI pins."""

    error = CommandError

    def __init__(self, chips):
        self._chips = chips
        self.registered_chips = {}
        self.setup_calls = []

    def parse_pin(self, pin, can_invert=False):
        chip_name, pin_name = pin.split(":", 1)
        chip = self._chips[chip_name]
        if chip.allowed_pins is not None and pin_name not in chip.allowed_pins:
            raise CommandError(f"Unknown pin {pin_name} on chip {chip_name}")
        return {"chip": chip, "pin": pin_name}

    def register_chip(self, name, chip):
        self.registered_chips[name] = chip

    def setup_pin(self, pin_type, pin_desc):
        self.setup_calls.append((pin_type, pin_desc))
        return SimpleNamespace(pin_type=pin_type, pin_desc=pin_desc)


class MockConfig:
    """Minimal config section object."""

    def __init__(self, printer, sections, name):
        self._printer = printer
        self._sections = sections
        self._name = name
        self._accessed_keys: set[str] = set()

    def get_name(self):
        return self._name

    def get_printer(self):
        return self._printer

    def has_section(self, name):
        return name in self._sections

    def getsection(self, name):
        return MockConfig(self._printer, self._sections, name)

    def get(self, key, default=None):
        self._accessed_keys.add(key)
        return self._sections.get(self._name, {}).get(key, default)

    def unused_options(self):
        """Keys present in this section that were never read.

        Mirrors Klipper's real unused-config-option check, which this
        simplified test double does not otherwise model.
        """
        return sorted(set(self._sections.get(self._name, {})) - self._accessed_keys)

    def getint(self, key, default=None, minval=None, maxval=None):
        present = key in self._sections.get(self._name, {})
        value = self.get(key, default)
        if not present or value is None:
            return value
        value = int(value)
        if minval is not None and value < minval:
            raise self.error(f"{key} below minimum")
        if maxval is not None and value > maxval:
            raise self.error(f"{key} above maximum")
        return value

    def getfloat(self, key, default=None, minval=None, maxval=None, above=None):
        present = key in self._sections.get(self._name, {})
        value = self.get(key, default)
        if not present or value is None:
            return value
        value = float(value)
        if minval is not None and value < minval:
            raise self.error(f"{key} below minimum")
        if maxval is not None and value > maxval:
            raise self.error(f"{key} above maximum")
        if above is not None and value <= above:
            raise self.error(f"{key} must be above {above}")
        return value

    def getlists(self, key, default=None, seps=(",",), count=None, parser=str):
        value = self.get(key, None)
        if value is None:
            return default

        def split(text, depth):
            parts = [part.strip() for part in text.split(seps[depth]) if part.strip()]
            if depth == 0:
                values = tuple(parser(part) for part in parts)
                if count is not None and len(values) != count:
                    raise self.error(f"{key} must have {count} values")
                return values
            return tuple(split(part, depth - 1) for part in parts)

        return split(str(value), len(seps) - 1)

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
            raise self.error(f"{key} must be one of {sorted(choices)}")
        return choices[value]

    def error(self, msg):
        return CommandError(msg)


def make_config_printer(stepper_sections, chips=None, kinematics=None):
    """Create a printer/config section set for FociDriver construction."""
    chips = chips or {"foci": MockMCU("foci")}
    sections = {}
    stepper_names = []
    next_stepper_oid = 10
    for name, values in stepper_sections.items():
        section = {
            "microsteps": values.get("microsteps", 20),
            "full_steps_per_rotation": values.get("full_steps_per_rotation", 200),
            "rotation_distance": values.get("rotation_distance", 40.0),
            "homing_speed": values.get("homing_speed", 5.0),
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
    printer._objects["print_stats"] = MockPrintStats()
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
    bind_protocol=True,
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
    driver.oid = 0
    driver.stepper_oid = None
    driver.channel = 0
    driver.global_config = SimpleNamespace(debug=False)

    # Printer and objects
    toolhead = MockToolhead(kinematics)
    toolhead._homed_axes = homed_axes
    printer = MockPrinter()
    printer._objects["gcode"] = MockGCode()
    printer._objects["toolhead"] = toolhead
    printer._objects["stepper_enable"] = MockStepperEnable()
    printer._objects["print_stats"] = MockPrintStats()
    driver.printer = printer

    # Runtime collaborators installed by FociDriver.__init__.
    driver.protocol = FociProtocol(driver)
    driver.state = FociRuntimeState()
    driver.dump = RegisterDumpWorkflow(driver)
    driver.controls = ControlsWorkflow(driver)
    driver.homing = HomingWorkflow(driver)
    driver.commissioning = CommissioningWorkflow(driver)
    driver.selftest = SelftestWorkflow(driver)
    driver.autotune = AutotuneWorkflow(driver)
    driver.diagnostics = DiagnosticsWorkflow(driver)

    driver.mcu = MockMCU(
        constants={
            "ENVELOPE_PROPORTIONAL_NUM": 3,
            "ENVELOPE_PROPORTIONAL_DEN": 2,
            "ENVELOPE_ABSOLUTE_MARGIN_MREV_S": 2000,
            "CLOCK_FREQ": 84_000_000,
        }
    )
    printer._objects["pins"] = MockPins({"foci": driver.mcu})
    sections = {
        driver.stepper_name: {
            "microsteps": 20,
            "full_steps_per_rotation": 200,
            "rotation_distance": 40.0,
            "homing_speed": 5.0,
            "step_pin": "foci:STEP0",
            "dir_pin": "foci:DIR0",
        },
        driver.name: {
            "run_current": 0.8,
            "homing_current": "0.7",
            "encoder_ppr": 1000,
            "voltage_limit": 16000,
            "identified_lambda_us": 0,
            "identified_theta_e_us": 160,
            "identified_bandwidth_hz": 0,
            "pid_velocity_limit": 500000,
        },
    }
    driver.config = parse_driver_config(MockConfig(printer, sections, driver.name))
    driver.settings = FociControlSettings.from_config(driver.config)
    driver.name = driver.config.name
    driver.stepper_name = driver.config.stepper_name
    driver.mcu = driver.config.mcu
    driver.channel = driver.config.channel
    driver.virtual_endstop = FociVirtualEndstop(driver)

    if bind_protocol:
        driver.protocol.bind_mcu(driver.mcu, driver.oid)

    return driver
