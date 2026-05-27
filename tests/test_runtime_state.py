from klipper_foci.state import FociRuntimeState


def test_runtime_state_lock_starts_available():
    state = FociRuntimeState()

    assert state.try_acquire() is True
    assert state.operation_lock is True


def test_runtime_state_lock_rejects_second_acquire():
    state = FociRuntimeState()
    assert state.try_acquire() is True

    assert state.try_acquire() is False


def test_runtime_state_release_makes_lock_available():
    state = FociRuntimeState(operation_lock=True)

    state.release()

    assert state.operation_lock is False
    assert state.try_acquire() is True


def test_runtime_status_defaults_to_uncommissioned():
    state = FociRuntimeState()

    assert state.runtime_status == "uncommissioned"
    assert state.active_gains is None
