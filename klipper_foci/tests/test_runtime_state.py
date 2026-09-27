import unittest

from klipper_foci.state import FociRuntimeState
from tests.mocks import make_driver


def test_runtime_state_lock_starts_available():
    state = FociRuntimeState()

    assert state.try_acquire("setup") is True
    assert state.operation_lock is True


def test_runtime_state_lock_rejects_second_acquire():
    state = FociRuntimeState()
    assert state.try_acquire("setup") is True

    assert state.try_acquire("setup") is False


def test_runtime_state_release_makes_lock_available():
    state = FociRuntimeState(operation_lock=True)

    state.release()

    assert state.operation_lock is False
    assert state.try_acquire("setup") is True


def test_runtime_status_defaults_to_uncommissioned():
    state = FociRuntimeState()

    assert state.runtime_status == "uncommissioned"
    assert state.active_gains is None
    assert state.adc_vm_offset_raw is None


class TestOperationLock(unittest.TestCase):
    def test_acquire_when_free(self):
        d = make_driver()
        self.assertTrue(d.state.try_acquire("setup"))
        self.assertTrue(d.state.operation_lock)

    def test_acquire_when_held(self):
        d = make_driver()
        d.state.operation_lock = True
        self.assertFalse(d.state.try_acquire("setup"))

    def test_release_makes_available(self):
        d = make_driver()
        d.state.operation_lock = True
        d.state.release()
        self.assertFalse(d.state.operation_lock)
        self.assertTrue(d.state.try_acquire("setup"))
