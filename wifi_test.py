# wifi_test.py
# Tests for wifi.py

import os
import time
import test_runner as t
import test_fixtures as tf
import logger
import watchdog
import wifi

# ============================================================
# MOCK SUPPORT
# ============================================================

class _MockWLAN:
    """
    Mock WLAN for testing without real WiFi.
    should_connect — whether isconnected() will eventually return True
    connect_after  — how many isconnected() calls before returning True
    """
    def __init__(self, should_connect=True, connect_after=1,
                 ifconfig=tf.TEST_IFCONFIG):
        self.should_connect = should_connect
        self.connect_after  = connect_after
        self._call_count    = 0
        self._active        = False
        self._ifconfig      = ifconfig
        self._ifconfig_set  = None
        self._connected_ssid = None
        self._status        = 3 if should_connect else -1

    def active(self, val=None):
        if val is not None:
            self._active = val
        return self._active

    def ifconfig(self, cfg=None):
        if cfg is not None:
            self._ifconfig_set = cfg
            self._ifconfig     = cfg
        return self._ifconfig

    def connect(self, ssid, password):
        self._connected_ssid = ssid

    def disconnect(self):
        self.should_connect = False
        self._status        = 0

    def isconnected(self):
        if not self.should_connect:
            return False
        self._call_count += 1
        return self._call_count >= self.connect_after

    def status(self):
        return self._status

_current_mock = None

def _install_mock(should_connect=True, connect_after=1):
    """Install a mock WLAN factory and reset wifi state."""
    global _current_mock
    _current_mock = _MockWLAN(should_connect, connect_after)
    wifi.set_wlan_factory(lambda _: _current_mock)
    _reset_state()
    return _current_mock

def _full_reset():
    """Full reset to clean initial state including factory."""
    wifi.set_wlan_factory(None)
    wifi._wlan          = None
    wifi._ip            = ""
    wifi._connected_at  = 0
    wifi._connect_count = 0
    wifi._fail_count    = 0
    wifi._ssid          = ""       # ← truly empty
    wifi._password      = ""
    wifi._static_ip     = None
    wifi._subnet        = None
    wifi._gateway       = None
    wifi._dns           = None

def _reset_state(ifconfig=tf.TEST_IFCONFIG):
    """Reset wifi state with test credentials pre-loaded."""
    wifi._wlan          = None
    wifi._ip            = ""
    wifi._connected_at  = 0
    wifi._connect_count = 0
    wifi._fail_count    = 0
    wifi._ssid          = "TestNet"
    wifi._password      = "TestPass"
    wifi._static_ip     = ifconfig[0]
    wifi._subnet        = ifconfig[1]
    wifi._gateway       = ifconfig[2]
    wifi._dns           = ifconfig[3]

# Suppress logger output during tests
logger.configure(log_file="test_wifi_log.txt", max_lines=50,
                 min_level=logger.DEBUG, echo_console=False)

# Disable real watchdog
watchdog._wdt     = None
watchdog._started = False

# ============================================================
# TESTS
# ============================================================

def test_initial_state():
    t.suite("wifi / initial state")
    _full_reset()
    t.expect_false("not connected initially",  wifi.is_connected())
    t.expect_eq("ip empty initially",          wifi.ip(),   "")
    t.expect_eq("ssid empty initially",        wifi.ssid(), "")

def test_configure():
    t.suite("wifi / configure")
    _full_reset()
    cfg = {
        "ssid":      "MyNet",
        "password":  "MyPass",
        "static_ip": "10.0.0.1",
        "subnet":    "255.255.255.0",
        "gateway":   "10.0.0.254",
        "dns":       "1.1.1.1",
    }
    wifi.configure(**cfg)
    t.expect_eq("ssid set",      wifi.ssid(),      cfg["ssid"])
    t.expect_eq("static_ip set", wifi._static_ip,  cfg["static_ip"])
    t.expect_eq("subnet set",    wifi._subnet,     cfg["subnet"])
    t.expect_eq("gateway set",   wifi._gateway,    cfg["gateway"])
    t.expect_eq("dns set",       wifi._dns,        cfg["dns"])

def test_connect_success():
    t.suite("wifi / connect success")
    _install_mock(should_connect=True, connect_after=1)

    result = wifi.connect(timeout_ms=2000, interval_ms=100)

    t.expect_true("connect returns True",        result)
    t.expect_true("is_connected returns True",   wifi.is_connected())
    t.expect_eq("ip is set",                     wifi.ip(), tf.TEST_STATIC_IP)
    t.expect_eq("connect_count incremented",     wifi._connect_count, 1)
    t.expect_eq("fail_count unchanged",          wifi._fail_count,    0)
    t.expect_gt("connected_at set",              wifi._connected_at,  0)

def test_connect_failure():
    t.suite("wifi / connect failure")
    _install_mock(should_connect=False)

    result = wifi.connect(timeout_ms=300, interval_ms=100)

    t.expect_false("connect returns False",      result)
    t.expect_false("is_connected returns False", wifi.is_connected())
    t.expect_eq("ip remains empty",              wifi.ip(), "")
    t.expect_eq("fail_count incremented",        wifi._fail_count,    1)
    t.expect_eq("connect_count incremented",     wifi._connect_count, 1)

def test_connect_sets_static_ip():
    t.suite("wifi / connect sets static IP")
    mock = _install_mock(should_connect=True, connect_after=1)

    wifi.connect(timeout_ms=2000, interval_ms=100)

    t.expect_not_none("ifconfig was called with static IP",
                      mock._ifconfig_set)
    t.expect_eq("correct IP passed",
                mock._ifconfig_set[0], wifi._static_ip)
    t.expect_eq("full ifconfig tuple passed",
                mock._ifconfig_set, tf.TEST_IFCONFIG)

def test_connect_passes_ssid():
    t.suite("wifi / connect passes SSID")
    mock = _install_mock(should_connect=True, connect_after=1)

    wifi.connect(timeout_ms=2000, interval_ms=100)

    t.expect_eq("correct SSID passed to wlan.connect",
                mock._connected_ssid, "TestNet")

def test_is_connected_no_wlan():
    t.suite("wifi / is_connected with no wlan")
    _full_reset()
    t.expect_false("False when wlan is None", wifi.is_connected())

def test_ip_after_connect():
    t.suite("wifi / ip after connect")
    _install_mock(should_connect=True, connect_after=1)
    wifi.connect(timeout_ms=2000, interval_ms=100)
    t.expect_eq("ip returns connected address",
                wifi.ip(), tf.TEST_STATIC_IP)

def test_stats():
    t.suite("wifi / stats")
    _install_mock(should_connect=True, connect_after=1)
    wifi.connect(timeout_ms=2000, interval_ms=100)

    s = wifi.stats()
    t.expect_in("ssid in stats",          "ssid",          s)
    t.expect_in("ip in stats",            "ip",            s)
    t.expect_in("connected in stats",     "connected",     s)
    t.expect_in("connect_count in stats", "connect_count", s)
    t.expect_in("fail_count in stats",    "fail_count",    s)
    t.expect_in("connected_at in stats",  "connected_at",  s)
    t.expect_true("connected is True",    s["connected"])
    t.expect_eq("connect_count is 1",     s["connect_count"], 1)
    t.expect_eq("fail_count is 0",        s["fail_count"],    0)

def test_check_and_reconnect_already_connected():
    t.suite("wifi / check_and_reconnect when already connected")
    _install_mock(should_connect=True, connect_after=1)
    wifi.connect(timeout_ms=2000, interval_ms=100)

    count_before = wifi._connect_count
    result       = wifi.check_and_reconnect()

    t.expect_true("returns True when connected", result)
    t.expect_eq("did not reconnect",
                wifi._connect_count, count_before)

def test_check_and_reconnect_when_dropped():
    t.suite("wifi / check_and_reconnect when dropped")
    _install_mock(should_connect=True, connect_after=1)
    wifi.connect(timeout_ms=2000, interval_ms=100)

    # Simulate drop by swapping mock
    _install_mock(should_connect=True, connect_after=1)

    result = wifi.check_and_reconnect(timeout_ms=2000)
    t.expect_true("reconnects successfully", result)
    t.expect_eq("connect called again",
                wifi._connect_count, 1)

def test_disconnect_clears_ip():
    t.suite("wifi / disconnect clears ip")
    _install_mock(should_connect=True, connect_after=1)
    wifi.connect(timeout_ms=2000, interval_ms=100)

    t.expect_eq("ip set before disconnect",
                wifi.ip(), tf.TEST_STATIC_IP)
    wifi.disconnect()
    t.expect_eq("ip cleared after disconnect", wifi.ip(), "")

def test_status_no_wlan():
    t.suite("wifi / status with no wlan")
    _full_reset()
    t.expect_eq("status -1 when no wlan", wifi.status(), -1)

def test_status_connected():
    t.suite("wifi / status when connected")
    mock = _install_mock(should_connect=True)
    wifi._wlan = mock
    t.expect_eq("status 3 when connected", wifi.status(), 3)

def test_multiple_connect_attempts():
    t.suite("wifi / multiple connect attempts")
    _install_mock(should_connect=False)

    wifi.connect(timeout_ms=200, interval_ms=100)
    wifi.connect(timeout_ms=200, interval_ms=100)

    t.expect_eq("connect_count tracks attempts",
                wifi._connect_count, 2)
    t.expect_eq("fail_count tracks failures",
                wifi._fail_count,    2)

def test_wlan_activated():
    t.suite("wifi / wlan is activated on connect")
    mock = _install_mock(should_connect=True, connect_after=1)
    wifi.connect(timeout_ms=2000, interval_ms=100)
    t.expect_true("wlan.active() was called", mock._active)

# ============================================================
# CLEANUP
# ============================================================

def cleanup():
    _full_reset()
    try:
        os.remove("test_wifi_log.txt")
    except:
        pass

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_initial_state()
    test_configure()
    test_connect_success()
    test_connect_failure()
    test_connect_sets_static_ip()
    test_connect_passes_ssid()
    test_is_connected_no_wlan()
    test_ip_after_connect()
    test_stats()
    test_check_and_reconnect_already_connected()
    test_check_and_reconnect_when_dropped()
    test_disconnect_clears_ip()
    test_status_no_wlan()
    test_status_connected()
    test_multiple_connect_attempts()
    test_wlan_activated()
    cleanup()
    return t.summary()

run()