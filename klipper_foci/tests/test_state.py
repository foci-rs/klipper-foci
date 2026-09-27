"""Tests for FociRuntimeState's operation lock and active_label."""

from klipper_foci.state import FociRuntimeState


def test_try_acquire_sets_active_label_on_success():
    state = FociRuntimeState()
    assert state.try_acquire("setup") is True
    assert state.active_label == "setup"


def test_try_acquire_fails_when_already_held():
    state = FociRuntimeState()
    state.try_acquire("setup")
    assert state.try_acquire("selftest") is False
    assert state.active_label == "setup"


def test_release_clears_active_label():
    state = FociRuntimeState()
    state.try_acquire("autotune")
    state.release()
    assert state.operation_lock is False
    assert state.active_label is None


def test_reacquire_after_release_can_change_label():
    state = FociRuntimeState()
    state.try_acquire("autotune")
    state.release()
    state.try_acquire("autotune")
    assert state.active_label == "autotune"
