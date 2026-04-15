"""Mock Klipper objects for FociDriver unit tests.

Provides a factory function that creates a FociDriver with minimal
mocks, bypassing __init__ to avoid Klipper dependencies. Tests set
state fields directly and call methods under test.
"""

from __future__ import annotations

from tmc4671 import FociDriver


class CommandError(Exception):
    """Stand-in for Klipper's printer.command_error."""


class MockPrinter:
    """Minimal printer mock for FociDriver."""

    def __init__(self):
        self._objects: dict[str, object] = {}

    def lookup_object(self, name, default=None):
        return self._objects.get(name, default)

    def register_event_handler(self, event, callback):
        pass

    def command_error(self, msg):
        return CommandError(msg)


class MockToolhead:
    """Minimal toolhead mock."""

    def __init__(self, kinematics=None):
        self._kinematics = kinematics or MockNoneKinematics()
        self._homed_axes = ""

    def get_kinematics(self):
        return self._kinematics

    def get_last_move_time(self):
        return 0.0

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
        self._steppers = [MockStepper(n) for n in stepper_names]

    def get_steppers(self):
        return self._steppers


class MockStepper:
    """Mock stepper with a name."""

    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


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

    def get(self, key, default=None):
        return self._params.get(key, default)

    def error(self, msg):
        return CommandError(msg)

    def respond_info(self, msg):
        self._responses.append(msg)


class MockReactor:
    """Minimal reactor for _ensure_calibrated."""

    def __init__(self):
        self._time = 0.0

    def monotonic(self):
        return self._time

    def completion(self):
        return MockCompletion()

    def pause(self, deadline):
        self._time = deadline
        return self._time


class MockCompletion:
    """Reactor completion mock."""

    def __init__(self):
        self._result = None

    def wait(self, deadline):
        return self._result

    def complete(self, result):
        self._result = result


class MockCommand:
    """Mock firmware command."""

    def __init__(self):
        self.last_args = None

    def send(self, args=None):
        self.last_args = args


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
    driver.oid = 0

    # Printer and objects
    toolhead = MockToolhead(kinematics)
    toolhead._homed_axes = homed_axes
    printer = MockPrinter()
    printer._objects["toolhead"] = toolhead
    printer._objects["stepper_enable"] = MockStepperEnable()
    driver.printer = printer

    # Volatile state (matches __init__ lines 700-719)
    driver.is_calibrated = False
    driver._calibration_completion = None
    driver._inhibited = False
    driver._commissioned_result = None
    driver._active_gains = None
    driver._runtime_status = None
    driver._foci_lock = False

    # Commission polling state
    driver._commission_done = False
    driver._commission_result = None
    driver._commission_error_code = 0
    driver._last_phase_id = None

    # Selftest state (legacy commissioning-engine based)
    driver._selftest_done = False
    driver._selftest_in_flight = False

    # Selftest streaming state
    driver._selftest_results = []
    driver._selftest_complete = False
    driver._selftest_status = 0

    # Config values (needed by some methods)
    driver.microsteps = 20
    driver.full_steps = 200
    driver.encoder_ppr = 1000
    driver.run_current = 0.8
    driver.velocity_feedforward = False

    # Identified values (from prior commission, used by AUTOTUNE)
    driver.identified_lambda_us = 0
    driver.identified_theta_e_us = 160
    driver.identified_ringing_count = 7
    driver.identified_bandwidth_hz = 0

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
    driver.calibrate_cmd = MockCommand()
    driver.commission_cmd = MockCommand()
    driver.tune_cmd = MockCommand()
    driver.selftest_cmd = MockCommand()
    driver.set_pid_gains_cmd = MockCommand()
    driver.set_position_gains_cmd = MockCommand()
    driver.set_velocity_limit_cmd = MockCommand()
    driver.set_velocity_filter_cmd = MockCommand()
    driver.set_torque_filter_cmd = MockCommand()
    driver.set_position_filter_cmd = MockCommand()
    driver.set_flux_filter_cmd = MockCommand()

    return driver
