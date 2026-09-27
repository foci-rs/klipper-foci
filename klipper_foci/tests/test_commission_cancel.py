"""Tests for the shared cancel-on-timeout / grace-period wait helper."""

from __future__ import annotations

import unittest

from klipper_foci.commissioning import COMMISSION_REASON_NAMES
from klipper_foci.constants import COMMISSION_CANCEL_GRACE_PERIOD_S
from tests.mocks import SAMPLE_ACTIVE_GAINS, MockGCmd, make_driver


class CommissionTimeoutCancelTests(unittest.TestCase):
    def test_commission_timeout_sends_cancel_before_raising(self):
        d = make_driver()
        sent = []
        d.protocol.run_commission = lambda profile_code: None
        d.protocol.run_commission_cancel = lambda: sent.append(True)
        reactor = d.printer.get_reactor()

        def pause(deadline):
            reactor._time = deadline
            return reactor._time

        reactor.pause = pause

        with self.assertRaises(Exception) as ctx:
            d.commissioning.commission(MockGCmd({}))

        self.assertIn("timed out", str(ctx.exception))
        self.assertEqual(sent, [True])
        self.assertFalse(d.state.operation_lock)


class CancelAndAwaitQuiescenceTests(unittest.TestCase):
    def test_sends_cancel_and_waits_up_to_the_grace_period(self):
        d = make_driver()
        sent = []
        d.protocol.run_commission_cancel = lambda: sent.append(True)
        reactor = d.printer.get_reactor()

        calls = []

        def pause(deadline):
            calls.append(deadline)
            reactor._time = deadline
            return reactor._time

        reactor.pause = pause

        done_after = 2
        state = {"n": 0}

        def predicate():
            state["n"] += 1
            return state["n"] > done_after

        eventtime = d.commissioning.cancel_and_await_quiescence(
            reactor, predicate, reactor.monotonic()
        )

        self.assertEqual(sent, [True])
        self.assertLessEqual(eventtime - reactor.monotonic(), COMMISSION_CANCEL_GRACE_PERIOD_S)
        self.assertGreater(len(calls), 0)

    def test_never_touches_the_operation_lock_itself(self):
        """The spec's central acceptance criterion is that the caller's lock
        stays held while the grace period runs and is released only by the
        caller's own existing finally, after this helper returns -- never by
        this helper. Assert this directly: the lock is untouched throughout
        and after the call, regardless of how the predicate resolves."""
        d = make_driver()
        d.protocol.run_commission_cancel = lambda: None
        d.state.operation_lock = True
        reactor = d.printer.get_reactor()
        lock_states_during_wait = []

        def pause(deadline):
            lock_states_during_wait.append(d.state.operation_lock)
            reactor._time = deadline
            return reactor._time

        reactor.pause = pause

        d.commissioning.cancel_and_await_quiescence(reactor, lambda: False, reactor.monotonic())

        self.assertTrue(lock_states_during_wait, "the wait loop must have polled at least once")
        self.assertTrue(all(lock_states_during_wait), "lock must stay held throughout the wait")
        self.assertTrue(d.state.operation_lock, "lock must still be held after the helper returns")

    def test_gives_up_after_the_grace_period_elapses(self):
        d = make_driver()
        d.protocol.run_commission_cancel = lambda: None
        reactor = d.printer.get_reactor()

        def pause(deadline):
            reactor._time = deadline
            return reactor._time

        reactor.pause = pause

        d.commissioning.cancel_and_await_quiescence(reactor, lambda: False, reactor.monotonic())

        self.assertGreaterEqual(reactor._time - 0.0, COMMISSION_CANCEL_GRACE_PERIOD_S)

    def test_commission_error_names_recognizes_cancelled(self):
        self.assertEqual(COMMISSION_REASON_NAMES[74], "cancelled")

    def test_commission_error_names_recognizes_safe_state_incomplete(self):
        self.assertEqual(COMMISSION_REASON_NAMES[75], "safe-state cleanup incomplete")


class SelftestTimeoutCancelTests(unittest.TestCase):
    def test_selftest_timeout_sends_cancel_before_raising(self):
        d = make_driver()
        sent = []
        d.protocol.run_selftest = lambda: None
        d.protocol.run_commission_cancel = lambda: sent.append(True)
        reactor = d.printer.get_reactor()

        def pause(deadline):
            reactor._time = deadline
            return reactor._time

        reactor.pause = pause

        with self.assertRaises(Exception) as ctx:
            d.selftest.selftest(MockGCmd({}))

        self.assertIn("timed out", str(ctx.exception))
        self.assertEqual(sent, [True])


class EnsureCalibratedTimeoutCancelTests(unittest.TestCase):
    def test_ensure_calibrated_timeout_sends_cancel_and_waits_again(self):
        d = make_driver()  # commissioned, not yet calibrated for this call
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        sent = []
        d.protocol.run_calibration = lambda: None
        d.protocol.run_commission_cancel = lambda: sent.append(True)
        reactor = d.printer.get_reactor()

        wait_deadlines = []

        class FakeCompletion:
            def complete(self, result):
                pass

            def wait(self, deadline, waketime_result=None):
                wait_deadlines.append(deadline)
                reactor._time = deadline
                return waketime_result  # always times out, both calls

        fake = FakeCompletion()
        reactor.completion = lambda: fake

        with self.assertRaises(Exception) as ctx:
            d.homing.ensure_calibrated()

        self.assertIn("timed out", str(ctx.exception))
        self.assertEqual(sent, [True])
        self.assertEqual(len(wait_deadlines), 2)
        self.assertGreater(wait_deadlines[1], wait_deadlines[0])

    def test_ensure_calibrated_cancelled_status_reports_cancelled_not_a_generic_failure(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.protocol.run_calibration = lambda: None
        d.protocol.run_commission_cancel = lambda: None
        reactor = d.printer.get_reactor()

        class FakeCompletion:
            def __init__(self):
                self.calls = 0

            def complete(self, result):
                pass

            def wait(self, deadline, waketime_result=None):
                self.calls += 1
                reactor._time = deadline
                if self.calls == 1:
                    return waketime_result
                return {"status": 10}  # CalibrationError::Cancelled

        reactor.completion = lambda: FakeCompletion()

        with self.assertRaises(Exception) as ctx:
            d.homing.ensure_calibrated()

        self.assertIn("cancelled", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
