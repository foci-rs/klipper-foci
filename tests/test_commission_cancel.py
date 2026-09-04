"""Tests for the shared cancel-on-timeout / grace-period wait helper."""

from __future__ import annotations

import unittest

from klipper_foci.commissioning import COMMISSION_ERROR_NAMES
from klipper_foci.constants import COMMISSION_CANCEL_GRACE_PERIOD_S

from tests.mocks import MockGCmd, make_driver


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
        self.assertEqual(COMMISSION_ERROR_NAMES[74], "cancelled")


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


if __name__ == "__main__":
    unittest.main()
