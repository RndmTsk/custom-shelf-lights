# watchdog.py
# Watchdog timer wrapper.
# Depends on nothing — safe to import anywhere.
# 
# The Pico's hardware watchdog reboots the device if feed()
# is not called within the timeout window. This module wraps
# that behaviour and adds a software pause mechanism for use
# during long operations like WiFi connect or OTA fetch.
#
# IMPORTANT: once started, the watchdog cannot be stopped.
# The only way out is to keep feeding it or let it reboot.

# ============================================================
# IMPORTS
# ============================================================

import machine
import time

# ============================================================
# GLOBALS
# ============================================================

_wdt          = None
_timeout_ms   = 8000
_started      = False
_paused       = False
_pause_fed_at = 0
_feed_count   = 0

# ============================================================
# CAPABILITIES
# ============================================================

def start(timeout_ms=8000):
    """
    Start the hardware watchdog.
    timeout_ms — reboot if feed() not called within this window.
    Minimum is 1000ms on the Pico, maximum is 8388ms (~8.3s).
    Safe to call multiple times — only starts once.
    """
    global _wdt, _timeout_ms, _started
    if _started:
        return
    _timeout_ms = max(1000, min(8388, timeout_ms))
    _wdt        = machine.WDT(timeout=_timeout_ms)
    _started    = True

def feed():
    """
    Feed the watchdog, resetting the countdown.
    Call this regularly in the main loop.
    If paused, feeds automatically to prevent reboot.
    """
    global _feed_count, _pause_fed_at
    if _wdt is None:
        return
    _wdt.feed()
    _feed_count += 1

def pause(duration_ms):
    """
    Block for duration_ms while keeping the watchdog fed.
    Use instead of time.sleep() for any sleep longer than
    the watchdog timeout.

    Example:
        watchdog.pause(30000)   # safe 30 second sleep
    """
    if _wdt is None:
        time.sleep_ms(duration_ms)
        return

    remaining = duration_ms
    interval  = max(100, _timeout_ms // 4)

    while remaining > 0:
        chunk = min(interval, remaining)
        time.sleep_ms(chunk)
        feed()
        remaining -= chunk

def feed_while(condition_fn, timeout_ms=None, interval_ms=500):
    """
    Feed the watchdog while condition_fn() returns True.
    Optionally stops after timeout_ms regardless of condition.
    Returns True if condition became False, False if timed out.

    Example:
        # Wait up to 20s for WiFi
        connected = watchdog.feed_while(
            lambda: not wlan.isconnected(),
            timeout_ms=20000,
            interval_ms=1000,
        )
    """
    start_ms  = time.ticks_ms()
    while condition_fn():
        feed()
        time.sleep_ms(interval_ms)
        if timeout_ms is not None:
            elapsed = time.ticks_diff(time.ticks_ms(), start_ms)
            if elapsed >= timeout_ms:
                return False
    return True

def is_started():
    """Return True if the watchdog has been started."""
    return _started

def timeout_ms():
    """Return the configured timeout in milliseconds."""
    return _timeout_ms

def feed_count():
    """Return total number of times feed() has been called."""
    return _feed_count