# watchdog_test.py
# Tests for watchdog.py
#
# NOTE: We cannot test the actual hardware WDT reboot behaviour
# in a unit test — starting it would reboot the Pico if we
# stopped feeding it. Tests cover the safe public API only,
# using a mock mode that skips hardware WDT initialisation.

import time
import test_runner as t
import watchdog

# ============================================================
# MOCK SUPPORT
# 
# We patch watchdog internals to avoid starting the real WDT.
# This lets us test all logic paths safely.
# ============================================================

def _mock_start():
    """Simulate a started watchdog without touching hardware."""
    watchdog._started    = True
    watchdog._wdt        = _MockWDT()
    watchdog._feed_count = 0
    watchdog._timeout_ms = 8000

def _mock_reset():
    """Reset watchdog module state."""
    watchdog._started    = False
    watchdog._wdt        = None
    watchdog._feed_count = 0
    watchdog._timeout_ms = 8000

class _MockWDT:
    """Stands in for machine.WDT without touching hardware."""
    def __init__(self):
        self.fed = 0
    def feed(self):
        self.fed += 1

# ============================================================
# TESTS
# ============================================================

def test_initial_state():
    t.suite("watchdog / initial state")
    _mock_reset()
    t.expect_false("not started initially",  watchdog.is_started())
    t.expect_eq("feed_count is 0",           watchdog.feed_count(), 0)
    t.expect_eq("default timeout",           watchdog.timeout_ms(), 8000)

def test_feed_before_start():
    t.suite("watchdog / feed before start is safe")
    _mock_reset()
    # Should not raise even if WDT not started
    try:
        watchdog.feed()
        watchdog.feed()
        t.expect_true("feed() before start does not crash", True)
    except Exception as e:
        t.expect_true(f"feed() raised unexpectedly: {e}", False)

def test_feed_count():
    t.suite("watchdog / feed count")
    _mock_reset()
    _mock_start()
    t.expect_eq("starts at 0",     watchdog.feed_count(), 0)
    watchdog.feed()
    t.expect_eq("increments to 1", watchdog.feed_count(), 1)
    watchdog.feed()
    watchdog.feed()
    t.expect_eq("increments to 3", watchdog.feed_count(), 3)

def test_is_started():
    t.suite("watchdog / is_started")
    _mock_reset()
    t.expect_false("False before mock start", watchdog.is_started())
    _mock_start()
    t.expect_true("True after mock start",    watchdog.is_started())

def test_timeout_ms():
    t.suite("watchdog / timeout_ms")
    _mock_reset()
    watchdog._timeout_ms = 5000
    t.expect_eq("returns configured timeout", watchdog.timeout_ms(), 5000)

def test_pause_feeds_watchdog():
    t.suite("watchdog / pause feeds watchdog")
    _mock_reset()
    _mock_start()

    before = watchdog.feed_count()
    watchdog.pause(600)   # 600ms — should feed at least once
    after  = watchdog.feed_count()

    t.expect_gt("pause fed watchdog at least once", after - before, 0)

def test_pause_without_wdt():
    t.suite("watchdog / pause without WDT is safe")
    _mock_reset()
    # WDT not started — pause should just sleep
    try:
        watchdog.pause(100)
        t.expect_true("pause without WDT does not crash", True)
    except Exception as e:
        t.expect_true(f"pause raised unexpectedly: {e}", False)

def test_feed_while_condition_becomes_false():
    t.suite("watchdog / feed_while — condition becomes False")
    _mock_reset()
    _mock_start()

    counter = [0]
    def condition():
        counter[0] += 1
        return counter[0] < 3   # False on 3rd call

    result = watchdog.feed_while(condition, timeout_ms=5000, interval_ms=50)
    t.expect_true("returns True when condition becomes False", result)
    t.expect_gte("condition called at least 3 times", counter[0], 3)

def test_feed_while_timeout():
    t.suite("watchdog / feed_while — timeout")
    _mock_reset()
    _mock_start()

    result = watchdog.feed_while(
        lambda: True,       # never becomes False
        timeout_ms=300,
        interval_ms=50,
    )
    t.expect_false("returns False on timeout", result)

def test_feed_while_immediately_false():
    t.suite("watchdog / feed_while — immediately False")
    _mock_reset()
    _mock_start()

    result = watchdog.feed_while(
        lambda: False,      # already False
        timeout_ms=1000,
        interval_ms=50,
    )
    t.expect_true("returns True when already False", result)

def test_feed_while_feeds_watchdog():
    t.suite("watchdog / feed_while — feeds watchdog during wait")
    _mock_reset()
    _mock_start()

    counter = [0]
    def condition():
        counter[0] += 1
        return counter[0] < 4

    before = watchdog.feed_count()
    watchdog.feed_while(condition, timeout_ms=5000, interval_ms=50)
    after  = watchdog.feed_count()

    t.expect_gt("watchdog fed during feed_while", after - before, 0)

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_initial_state()
    test_feed_before_start()
    test_feed_count()
    test_is_started()
    test_timeout_ms()
    test_pause_feeds_watchdog()
    test_pause_without_wdt()
    test_feed_while_condition_becomes_false()
    test_feed_while_timeout()
    test_feed_while_immediately_false()
    test_feed_while_feeds_watchdog()
    return t.summary()

run()