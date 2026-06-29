# main_test.py
# Tests for main.py built-in handlers.
#
# main.py is the permanent integration layer — we test its
# handler functions in isolation without running the main loop.

import os
import json
import time
import test_runner as t
import test_fixtures as tf
import logger
import env
import wifi
import slots
import ota
import http_server

# ============================================================
# SETUP
# ============================================================

logger.configure(
    log_file="test_main_log.txt",
    max_lines=100,
    min_level=logger.DEBUG,
    echo_console=False,
)

# Disable real watchdog for tests
import watchdog
watchdog._wdt     = None
watchdog._started = False

# Disable real WiFi
class _MockWLAN:
    def __init__(self, connected=True, ifconfig=tf.TEST_IFCONFIG):
        self._connected = connected
        self._ifconfig  = ifconfig
        self._status    = 3 if connected else -1
    def active(self, v=None): return True
    def ifconfig(self, cfg=None):
        if cfg is not None:
            self._ifconfig = cfg
        return self._ifconfig
    def connect(self, s, p): pass
    def disconnect(self): self._connected = False
    def isconnected(self): return self._connected
    def status(self): return self._status

def _install_wifi(connected=True):
    mock = _MockWLAN(connected)
    wifi.set_wlan_factory(lambda _: mock)
    wifi.configure(
        ssid="TestNet",
        password="TestPass",
        static_ip=tf.TEST_STATIC_IP,
        subnet=tf.TEST_SUBNET,
        gateway=tf.TEST_GATEWAY,
        dns=tf.TEST_DNS,
    )
    wifi._wlan = mock
    wifi._ip   = tf.TEST_STATIC_IP if connected else ""
    return mock

def cleanup():
    for f in ("test_main_log.txt", slots.SLOT_FILE,
              slots.HEARTBEAT_FILE, ota.META_FILE):
        try:
            os.remove(f)
        except:
            pass
    http_server.unregister_all()
    wifi.set_wlan_factory(None)

# ============================================================
# HANDLER TESTS
# We import and test handler functions directly rather than
# running the full main loop.
# ============================================================

# Load env for handler context
env.load(".env")

# Build handler functions matching main.py's implementations
# These mirror what main.py registers — tested in isolation

def _make_handlers(ext=None, slot="a"):
    """Build the four built-in handlers as closures."""
    reboot_state = {"pending": False, "at": 0}

    def handle_ping(parts, method, body, query):
        return 200, {
            "status":       "ok",
            "main_version": "1.0.0",
            "ext_version":  getattr(ext, "EXT_VERSION", None),
            "slot":         slot,
            "wifi":         wifi.is_connected(),
            "ip":           wifi.ip(),
            "ts":           time.time(),
        }

    def handle_log(parts, method, body, query):
        fmt   = query.get("format", "json").lower()
        limit = None
        if "limit" in query:
            try:
                limit = int(query["limit"])
            except:
                pass
        if fmt not in ("json", "csv", "text"):
            return 400, {"error": f"Unknown format: {fmt}"}
        raw = logger.read_formatted(fmt=fmt, limit=limit)
        if fmt == "json":
            try:
                return 200, json.loads(raw)
            except:
                return 200, {"log": [], "error": "parse error"}
        return 200, {"log": raw, "format": fmt}

    def handle_update(parts, method, body, query):
        if len(parts) < 2:
            return 400, {"error": "Try: check, status, rollback"}
        sub = parts[1].lower()
        if sub == "check":
            if not wifi.is_connected():
                return 503, {"error": "WiFi not connected"}
            result  = ota.check(slot)
            updated = result.get("updated", False)
            if updated:
                reboot_state["pending"] = True
                reboot_state["at"]      = time.time() + 2
            return 200, {
                "status":  "updated" if updated else "checked",
                "result":  result,
                "reboot":  updated,
            }
        elif sub == "status":
            meta = ota.load_meta()
            return 200, {
                "main_version":      "1.0.0",
                "ext_slot":          slot,
                "ext_version":       getattr(ext, "EXT_VERSION", None),
                "ota_ext_version":   meta.get("ext_version", 0),
                "fail_count":        meta.get("fail_count", 0),
                "backoff_until":     meta.get("backoff_until", 0),
                "backoff_remaining": ota.remaining_backoff(meta),
            }
        elif sub == "rollback":
            other = slots.other_slot(slot)
            if slots.write_slot(other):
                reboot_state["pending"] = True
                reboot_state["at"]      = time.time() + 2
                return 200, {
                    "status": "rollback",
                    "from":   slot,
                    "to":     other,
                    "reboot": True,
                }
            return 500, {"error": "Could not write slot file"}
        return 400, {"error": f"Unknown sub-command: {sub}"}

    def handle_wifi(parts, method, body, query):
        return 200, wifi.stats()

    return (handle_ping, handle_log,
            handle_update, handle_wifi,
            reboot_state)

# ============================================================
# PING TESTS
# ============================================================

def test_ping_connected():
    t.suite("main / ping — connected")
    _install_wifi(connected=True)
    handle_ping, _, _, _, _ = _make_handlers(slot="a")

    status, resp = handle_ping(["ping"], "GET", None, {})
    t.expect_eq("status 200",          status,          200)
    t.expect_eq("status ok",           resp["status"],  "ok")
    t.expect_eq("slot correct",        resp["slot"],    "a")
    t.expect_true("wifi connected",    resp["wifi"])
    t.expect_eq("ip correct",          resp["ip"], tf.TEST_STATIC_IP)
    t.expect_not_none("main_version",  resp.get("main_version"))
    t.expect_gt("ts set",              resp["ts"], 0)

def test_ping_disconnected():
    t.suite("main / ping — disconnected")
    _install_wifi(connected=False)
    handle_ping, _, _, _, _ = _make_handlers(slot="b")

    status, resp = handle_ping(["ping"], "GET", None, {})
    t.expect_eq("status 200",       status,         200)
    t.expect_false("wifi false",    resp["wifi"])
    t.expect_eq("ip empty",         resp["ip"],     "")
    t.expect_eq("slot b",           resp["slot"],   "b")

def test_ping_with_ext():
    t.suite("main / ping — with extension")

    class _FakeExt:
        EXT_VERSION = 42

    _install_wifi(connected=True)
    handle_ping, _, _, _, _ = _make_handlers(ext=_FakeExt(), slot="a")

    status, resp = handle_ping(["ping"], "GET", None, {})
    t.expect_eq("ext_version present",
                resp["ext_version"], 42)

def test_ping_no_ext():
    t.suite("main / ping — no extension loaded")
    _install_wifi(connected=True)
    handle_ping, _, _, _, _ = _make_handlers(ext=None, slot="a")

    status, resp = handle_ping(["ping"], "GET", None, {})
    t.expect_eq("status 200",           status, 200)
    t.expect_none("ext_version None",   resp["ext_version"])

# ============================================================
# LOG TESTS
# ============================================================

def test_log_json():
    t.suite("main / log — JSON format")
    logger.configure(log_file="test_main_log.txt", max_lines=50,
                     min_level=logger.DEBUG, echo_console=False)
    logger.clear()
    logger.info("Test entry", data={"x": 1})

    _, handle_log, _, _, _ = _make_handlers()
    status, resp = handle_log(["log"], "GET", None, {"format": "json"})

    t.expect_eq("status 200",        status, 200)
    t.expect_in("log key",           "log",   resp)
    t.expect_in("count key",         "count", resp)
    t.expect_gt("has entries",       resp["count"], 0)

def test_log_text():
    t.suite("main / log — text format")
    logger.configure(log_file="test_main_log.txt", max_lines=50,
                     min_level=logger.DEBUG, echo_console=False)
    logger.clear()
    logger.info("Text test entry")

    _, handle_log, _, _, _ = _make_handlers()
    status, resp = handle_log(["log"], "GET", None, {"format": "text"})

    t.expect_eq("status 200",     status, 200)
    t.expect_in("log key",        "log",    resp)
    t.expect_in("format key",     "format", resp)
    t.expect_true("text content",
                  "Text test entry" in resp["log"])

def test_log_csv():
    t.suite("main / log — CSV format")
    logger.configure(log_file="test_main_log.txt", max_lines=50,
                     min_level=logger.DEBUG, echo_console=False)
    logger.clear()
    logger.info("CSV test entry")

    _, handle_log, _, _, _ = _make_handlers()
    status, resp = handle_log(["log"], "GET", None, {"format": "csv"})

    t.expect_eq("status 200",        status, 200)
    t.expect_true("has header row",
                  resp["log"].startswith("ts,level"))

def test_log_invalid_format():
    t.suite("main / log — invalid format")
    _, handle_log, _, _, _ = _make_handlers()
    status, resp = handle_log(["log"], "GET", None,
                              {"format": "xml"})
    t.expect_eq("status 400",    status, 400)
    t.expect_in("error in resp", "error", resp)

def test_log_default_format():
    t.suite("main / log — default format is JSON")
    logger.configure(log_file="test_main_log.txt", max_lines=50,
                     min_level=logger.DEBUG, echo_console=False)
    logger.clear()
    logger.info("Default format test")

    _, handle_log, _, _, _ = _make_handlers()
    status, resp = handle_log(["log"], "GET", None, {})
    t.expect_eq("status 200",  status, 200)
    t.expect_in("log key",     "log",   resp)
    t.expect_in("count key",   "count", resp)

def test_log_limit():
    t.suite("main / log — limit parameter")
    logger.configure(log_file="test_main_log.txt", max_lines=50,
                     min_level=logger.DEBUG, echo_console=False)
    logger.clear()
    for i in range(10):
        logger.info(f"Entry {i}")

    _, handle_log, _, _, _ = _make_handlers()
    status, resp = handle_log(["log"], "GET", None,
                              {"format": "json", "limit": "3"})
    t.expect_eq("status 200",       status,       200)
    t.expect_eq("limited to 3",     resp["count"], 3)

# ============================================================
# UPDATE TESTS
# ============================================================

def test_update_no_subcommand():
    t.suite("main / update — no subcommand")
    _, _, handle_update, _, _ = _make_handlers()
    status, resp = handle_update(["update"], "GET", None, {})
    t.expect_eq("status 400",    status, 400)
    t.expect_in("error in resp", "error", resp)

def test_update_unknown_sub():
    t.suite("main / update — unknown subcommand")
    _, _, handle_update, _, _ = _make_handlers()
    status, resp = handle_update(
        ["update", "foobar"], "GET", None, {})
    t.expect_eq("status 400",    status, 400)
    t.expect_in("error in resp", "error", resp)

def test_update_status():
    t.suite("main / update/status")
    ota.clear_meta()
    _, _, handle_update, _, _ = _make_handlers(slot="a")
    status, resp = handle_update(
        ["update", "status"], "GET", None, {})

    t.expect_eq("status 200",          status, 200)
    t.expect_in("main_version",        "main_version",    resp)
    t.expect_in("ext_slot",            "ext_slot",        resp)
    t.expect_in("ota_ext_version",     "ota_ext_version", resp)
    t.expect_in("fail_count",          "fail_count",      resp)
    t.expect_in("backoff_remaining",   "backoff_remaining", resp)
    t.expect_eq("slot a",              resp["ext_slot"], "a")
    t.expect_eq("fail_count 0",        resp["fail_count"], 0)

def test_update_check_no_wifi():
    t.suite("main / update/check — no WiFi")
    _install_wifi(connected=False)
    _, _, handle_update, _, _ = _make_handlers()
    status, resp = handle_update(
        ["update", "check"], "GET", None, {})
    t.expect_eq("status 503",    status, 503)
    t.expect_in("error in resp", "error", resp)

def test_update_check_up_to_date():
    t.suite("main / update/check — up to date")
    _install_wifi(connected=True)
    ota.save_meta({"ext_version": 5, "fail_count": 0,
                   "backoff_until": 0})
    ota.set_fetch_fn(lambda url: "5"
                     if url.endswith("version_ext.txt") else None)

    _, _, handle_update, _, reboot_state = _make_handlers(slot="a")
    status, resp = handle_update(
        ["update", "check"], "GET", None, {})

    t.expect_eq("status 200",          status,              200)
    t.expect_eq("status checked",      resp["status"],      "checked")
    t.expect_false("not rebooting",    resp["reboot"])
    t.expect_false("reboot not set",   reboot_state["pending"])

    ota.set_fetch_fn(None)

def test_update_check_new_version():
    t.suite("main / update/check — new version available")
    _install_wifi(connected=True)
    ota.clear_meta()

    # GitHub always serves EXT_SLOT = "a"
    # ota._patch_slot will rewrite it to "b" for the inactive slot
    valid_ext = (
        'EXT_SLOT = "a"\n'
        'EXT_VERSION = 2\n'
        'NUM_LEDS = 22\n'
        'MAX_BRIGHTNESS = 0.3\n'
        'PIN_L1 = 0\n'
        'PIN_L2 = 1\n'
        'PIN_R1 = 2\n'
        'PIN_R2 = 3\n'
        'def setup(env): pass\n'
        'def tick(): pass\n'
        'def handle_request(p,m,b,q): return 200, {}\n'
        'def teardown(): pass\n'
    )

    def fetch(url):
        if url.endswith("version_ext.txt"):
            return "2"
        if url.endswith("extensions.py"):
            return valid_ext
        return None

    ota.set_fetch_fn(fetch)
    slots.write_slot("a")

    _, _, handle_update, _, reboot_state = _make_handlers(slot="a")
    status, resp = handle_update(
        ["update", "check"], "GET", None, {})

    t.expect_eq("status 200",        status,          200)
    t.expect_eq("status updated",     resp["status"],  "updated")
    t.expect_true("reboot flagged",   resp["reboot"])
    t.expect_true("reboot scheduled", reboot_state["pending"])

    ota.set_fetch_fn(None)

    try:
        os.remove("extensions_b.py")
    except:
        pass

def test_update_rollback():
    t.suite("main / update/rollback")
    slots.write_slot("a")
    _, _, handle_update, _, reboot_state = _make_handlers(slot="a")
    status, resp = handle_update(
        ["update", "rollback"], "GET", None, {})

    t.expect_eq("status 200",         status,           200)
    t.expect_eq("rollback status",     resp["status"],   "rollback")
    t.expect_eq("from slot a",         resp["from"],     "a")
    t.expect_eq("to slot b",           resp["to"],       "b")
    t.expect_true("reboot flagged",    resp["reboot"])
    t.expect_true("reboot scheduled",  reboot_state["pending"])
    t.expect_eq("slot file updated",   slots.read_slot(), "b")

# ============================================================
# WIFI HANDLER TESTS
# ============================================================

def test_wifi_handler_connected():
    t.suite("main / wifi handler — connected")
    _install_wifi(connected=True)
    _, _, _, handle_wifi, _ = _make_handlers()
    status, resp = handle_wifi(["wifi"], "GET", None, {})

    t.expect_eq("status 200",        status, 200)
    t.expect_in("ssid",              "ssid",          resp)
    t.expect_in("ip",                "ip",            resp)
    t.expect_in("connected",         "connected",     resp)
    t.expect_in("connect_count",     "connect_count", resp)
    t.expect_in("fail_count",        "fail_count",    resp)
    t.expect_true("connected True",  resp["connected"])
    t.expect_eq("ip correct",        resp["ip"], tf.TEST_STATIC_IP)

def test_wifi_handler_disconnected():
    t.suite("main / wifi handler — disconnected")
    _install_wifi(connected=False)
    _, _, _, handle_wifi, _ = _make_handlers()
    status, resp = handle_wifi(["wifi"], "GET", None, {})

    t.expect_eq("status 200",         status, 200)
    t.expect_false("connected False",  resp["connected"])
    t.expect_eq("ip empty",            resp["ip"], "")

# ============================================================
# HTTP SERVER INTEGRATION TESTS
# ============================================================

def test_builtin_handlers_register():
    t.suite("main / built-in handlers register correctly")
    http_server.unregister_all()

    handle_ping, handle_log, handle_update, handle_wifi, _ = \
        _make_handlers()

    http_server.register("ping",   handle_ping)
    http_server.register("log",    handle_log)
    http_server.register("update", handle_update)
    http_server.register("wifi",   handle_wifi)

    for cmd in ("ping", "log", "update", "wifi"):
        t.expect_in(f"{cmd} registered",
                    cmd, http_server.registered_commands())

def test_dispatch_ping_via_server():
    t.suite("main / dispatch ping via http_server")
    http_server.unregister_all()
    _install_wifi(connected=True)

    handle_ping, handle_log, handle_update, handle_wifi, _ = \
        _make_handlers(slot="a")

    http_server.register("ping",   handle_ping)
    http_server.register("log",    handle_log)
    http_server.register("update", handle_update)
    http_server.register("wifi",   handle_wifi)

    status, resp = http_server.dispatch(
        ["ping"], "GET", None, {})
    t.expect_eq("status 200",   status,         200)
    t.expect_eq("status ok",    resp["status"], "ok")

def test_dispatch_unknown_returns_404():
    t.suite("main / dispatch unknown returns 404")
    http_server.unregister_all()
    handle_ping, handle_log, handle_update, handle_wifi, _ = \
        _make_handlers()
    http_server.register("ping",   handle_ping)
    http_server.register("log",    handle_log)
    http_server.register("update", handle_update)
    http_server.register("wifi",   handle_wifi)

    status, resp = http_server.dispatch(
        ["doesnotexist"], "GET", None, {})
    t.expect_eq("status 404",    status, 404)
    t.expect_in("error in resp", "error", resp)

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_ping_connected()
    test_ping_disconnected()
    test_ping_with_ext()
    test_ping_no_ext()
    test_log_json()
    test_log_text()
    test_log_csv()
    test_log_invalid_format()
    test_log_default_format()
    test_log_limit()
    test_update_no_subcommand()
    test_update_unknown_sub()
    test_update_status()
    test_update_check_no_wifi()
    test_update_check_up_to_date()
    test_update_check_new_version()
    test_update_rollback()
    test_wifi_handler_connected()
    test_wifi_handler_disconnected()
    test_builtin_handlers_register()
    test_dispatch_ping_via_server()
    test_dispatch_unknown_returns_404()
    cleanup()
    return t.summary()

run()