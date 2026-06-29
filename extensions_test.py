# extensions_test.py
# Tests for extensions.py
#
# NOTE: NeoPixel hardware is not available in tests.
# We mock the strips and test all logic paths:
# state management, routing, effect engine, handlers.

import os
import json
import time
import test_runner as t
import logger
import http_server

# ============================================================
# MOCK NEOPIXEL
# ============================================================

class _MockStrip:
    """Simulates a NeoPixel strip without hardware."""
    def __init__(self, pin, num_leds, bpp=4):
        self.num_leds = num_leds
        self.bpp      = bpp
        self._data    = [(0, 0, 0, 0)] * num_leds
        self.writes   = 0

    def __setitem__(self, idx, val):
        self._data[idx] = val

    def __getitem__(self, idx):
        return self._data[idx]

    def write(self):
        self.writes += 1


class _MockPin:
    def __init__(self, n, *args, **kwargs):
        self.n = n


class _MockNeoPixel:
    """Mock neopixel module."""
    def __init__(self):
        self.strips = []

    def NeoPixel(self, pin, num_leds, bpp=4):
        strip = _MockStrip(pin, num_leds, bpp)
        self.strips.append(strip)
        return strip


class _MockMachine:
    """Mock machine module."""
    def Pin(self, n, *args, **kwargs):
        return _MockPin(n)


# ============================================================
# SETUP
# ============================================================

# Install mocks before importing extensions
import sys
_mock_np      = _MockNeoPixel()
_mock_machine = _MockMachine()
sys.modules["neopixel"] = _mock_np
sys.modules["machine"]  = _mock_machine

import extensions as ext

def setup():
    logger.configure(
        log_file="test_ext_log.txt",
        max_lines=200,
        min_level=logger.DEBUG,
        echo_console=False,
    )
    http_server.unregister_all()
    _mock_np.strips = []

    # Reset module state
    ext._strips = None
    ext._state  = None
    ext._engine = None

    # Clean state file
    try:
        os.remove(ext.STATE_FILE)
    except:
        pass

def setup_with_init():
    """Setup and call ext.setup() with mock env."""
    setup()
    ext.setup({})
    return ext

def cleanup():
    try:
        os.remove(ext.STATE_FILE)
    except:
        pass
    try:
        os.remove("test_ext_log.txt")
    except:
        pass
    http_server.unregister_all()

# ============================================================
# IDENTITY TESTS
# ============================================================

def test_identity_fields():
    t.suite("extensions / identity fields")
    setup()
    t.expect_type("EXT_SLOT is str",    ext.EXT_SLOT,    str)
    t.expect_type("EXT_VERSION is int", ext.EXT_VERSION, int)
    t.expect_in("EXT_SLOT valid",       ext.EXT_SLOT, ("a", "b"))
    t.expect_gt("EXT_VERSION > 0",      ext.EXT_VERSION, 0)

def test_hardware_constants():
    t.suite("extensions / hardware constants")
    setup()
    t.expect_type("NUM_LEDS int",       ext.NUM_LEDS,       int)
    t.expect_type("MAX_BRIGHTNESS float", ext.MAX_BRIGHTNESS, float)
    t.expect_gt("NUM_LEDS > 0",         ext.NUM_LEDS,       0)
    t.expect_gt("MAX_BRIGHTNESS > 0",   ext.MAX_BRIGHTNESS, 0.0)
    t.expect_lt("MAX_BRIGHTNESS <= 1",  ext.MAX_BRIGHTNESS, 1.01)
    t.expect_type("PIN_L1 int",         ext.PIN_L1,         int)
    t.expect_type("PIN_L2 int",         ext.PIN_L2,         int)
    t.expect_type("PIN_R1 int",         ext.PIN_R1,         int)
    t.expect_type("PIN_R2 int",         ext.PIN_R2,         int)

# ============================================================
# SETUP / TEARDOWN TESTS
# ============================================================

def test_setup_initialises_strips():
    t.suite("extensions / setup initialises strips")
    setup()
    ext.setup({})
    t.expect_not_none("_strips set",         ext._strips)
    t.expect_eq("four strips created",       len(ext._strips), 4)
    t.expect_eq("mock strips registered",    len(_mock_np.strips), 4)

def test_setup_initialises_engine():
    t.suite("extensions / setup initialises engine")
    setup()
    ext.setup({})
    t.expect_not_none("_engine set",         ext._engine)
    t.expect_false("engine not running",     ext._engine["running"])
    t.expect_false("engine not fading",      ext._engine["fading_out"])

def test_setup_loads_default_state():
    t.suite("extensions / setup loads default state")
    setup()
    ext.setup({})
    t.expect_not_none("_state set",          ext._state)
    t.expect_false("on is False",            ext._state["on"])
    t.expect_in("default effect",
                ext._state["effect"], ext.EFFECTS)

def test_setup_registers_handlers():
    t.suite("extensions / setup registers handlers")
    setup()
    ext.setup({})
    for cmd in ("on", "off", "stop", "effect",
                "brightness", "colour", "status", "set"):
        t.expect_in(f"{cmd} registered",
                    cmd, http_server.registered_commands())

def test_teardown_unregisters_handlers():
    t.suite("extensions / teardown unregisters handlers")
    setup()
    ext.setup({})
    ext.teardown()
    for cmd in ("on", "off", "stop", "effect",
                "brightness", "colour", "status", "set"):
        t.expect_false(f"{cmd} unregistered",
                       cmd in http_server.registered_commands())

def test_teardown_saves_state():
    t.suite("extensions / teardown saves state")
    setup()
    ext.setup({})
    ext._state["on"] = True
    ext.teardown()
    t.expect_true("state file written",
                  os.path.exists(ext.STATE_FILE) if
                  hasattr(os, "path") else True)

# ============================================================
# STATE PERSISTENCE TESTS
# ============================================================

def test_state_roundtrip():
    t.suite("extensions / state roundtrip")
    setup()
    ext.setup({})
    ext._state["on"]        = True
    ext._state["brightness"] = 0.5
    ext._state["effect"]    = "TWINKLE"
    ext._state["colour"]    = [100, 50, 25, 10]
    ext._save_state(ext._state)

    loaded = ext._load_state()
    t.expect_true("on persists",         loaded["on"])
    t.expect_eq("brightness persists",   loaded["brightness"],  0.5)
    t.expect_eq("effect persists",       loaded["effect"],      "TWINKLE")
    t.expect_eq("colour persists",       loaded["colour"],      [100, 50, 25, 10])

def test_state_default_on_missing_file():
    t.suite("extensions / state defaults on missing file")
    setup()
    state = ext._load_state()
    t.expect_false("on defaults False",  state["on"])
    t.expect_eq("default effect",        state["effect"], "CHASE_SMOOTH")

def test_state_clamps_brightness():
    t.suite("extensions / state clamps brightness")
    setup()
    with open(ext.STATE_FILE, "w") as f:
        json.dump({"brightness": 99.9,
                   "brightness_per_strip": [99.9, -1.0, 0.5, 0.3]}, f)
    state = ext._load_state()
    t.expect_eq("brightness clamped to 1.0", state["brightness"], 1.0)
    t.expect_eq("strip 0 clamped",
                state["brightness_per_strip"][0], 1.0)
    t.expect_eq("strip 1 clamped",
                state["brightness_per_strip"][1], 0.0)

# ============================================================
# LED HELPER TESTS
# ============================================================

def test_make_colour_brightness():
    t.suite("extensions / _make_colour brightness scaling")
    setup_with_init()
    c = ext._make_colour(200, 100, 50, 80, 0.5)
    t.expect_eq("R scaled", c[0], 100)
    t.expect_eq("G scaled", c[1], 50)
    t.expect_eq("B scaled", c[2], 25)
    t.expect_eq("W scaled", c[3], 40)

def test_make_colour_clamps():
    t.suite("extensions / _make_colour clamps values")
    setup_with_init()
    c = ext._make_colour(999, -1, 300, 0, 1.0)
    t.expect_eq("R clamped to 255", c[0], 255)
    t.expect_eq("G clamped to 0",   c[1], 0)
    t.expect_eq("B clamped to 255", c[2], 255)

def test_make_colour_zero_brightness():
    t.suite("extensions / _make_colour zero brightness")
    setup_with_init()
    c = ext._make_colour(255, 255, 255, 255, 0.0)
    t.expect_eq("all zero at 0 brightness", c, (0, 0, 0, 0))

def test_validate_colour_valid():
    t.suite("extensions / _validate_colour valid")
    setup_with_init()
    t.expect_eq("valid colour",
                ext._validate_colour([15, 5, 0, 80]),
                [15, 5, 0, 80])
    t.expect_eq("clamps values",
                ext._validate_colour([999, -1, 128, 0]),
                [255, 0, 128, 0])

def test_validate_colour_invalid():
    t.suite("extensions / _validate_colour invalid")
    setup_with_init()
    t.expect_none("wrong length",  ext._validate_colour([1, 2, 3]))
    t.expect_none("not a list",    ext._validate_colour("red"))
    t.expect_none("None input",    ext._validate_colour(None))

def test_safe_int():
    t.suite("extensions / _safe_int")
    setup_with_init()
    t.expect_eq("valid int",          ext._safe_int("42"),          42)
    t.expect_eq("with min",           ext._safe_int("5", min_val=0), 5)
    t.expect_none("below min",        ext._safe_int("5", min_val=10))
    t.expect_none("above max",        ext._safe_int("200", max_val=100))
    t.expect_none("non-numeric",      ext._safe_int("abc"))
    t.expect_none("empty string",     ext._safe_int(""))

def test_resolve_target():
    t.suite("extensions / _resolve_target")
    setup_with_init()
    t.expect_eq("l1",     ext._resolve_target(["on", "l1"], 1),    [0])
    t.expect_eq("l2",     ext._resolve_target(["on", "l2"], 1),    [1])
    t.expect_eq("r1",     ext._resolve_target(["on", "r1"], 1),    [2])
    t.expect_eq("r2",     ext._resolve_target(["on", "r2"], 1),    [3])
    t.expect_eq("left",   ext._resolve_target(["on", "left"], 1),  [0, 1])
    t.expect_eq("right",  ext._resolve_target(["on", "right"], 1), [2, 3])
    t.expect_eq("all",    ext._resolve_target(["on", "all"], 1),   [0, 1, 2, 3])
    t.expect_eq("default all",
                ext._resolve_target(["on"], 1), [0, 1, 2, 3])
    t.expect_none("unknown target",
                  ext._resolve_target(["on", "xyz"], 1))

def test_resolve_led_colour():
    t.suite("extensions / _resolve_led_colour")
    setup_with_init()
    # Default — uses strip colour
    ext._state["colour_per_strip"][0] = [10, 20, 30, 40]
    ext._state["colour_per_led"][0][0] = None
    t.expect_eq("uses strip colour when led is None",
                ext._resolve_led_colour(0, 0), [10, 20, 30, 40])

    # Per-LED override
    ext._state["colour_per_led"][0][0] = [1, 2, 3, 4]
    t.expect_eq("uses per-LED colour when set",
                ext._resolve_led_colour(0, 0), [1, 2, 3, 4])

# ============================================================
# HTTP HANDLER TESTS
# ============================================================

def test_handle_on_all():
    t.suite("extensions / handle_on all strips")
    setup_with_init()
    status, resp = ext._handle_on(["on"], "GET", None, {})
    t.expect_eq("status 200",        status,          200)
    t.expect_eq("status on",         resp["status"],  "on")
    t.expect_eq("all strips",        len(resp["strips"]), 4)
    t.expect_true("state on",        ext._state["on"])

def test_handle_on_target():
    t.suite("extensions / handle_on with target")
    setup_with_init()
    status, resp = ext._handle_on(["on", "left"], "GET", None, {})
    t.expect_eq("status 200",        status,         200)
    t.expect_eq("two strips",        len(resp["strips"]), 2)

def test_handle_on_invalid_target():
    t.suite("extensions / handle_on invalid target")
    setup_with_init()
    status, resp = ext._handle_on(["on", "xyz"], "GET", None, {})
    t.expect_eq("status 400",        status, 400)
    t.expect_in("error in resp",     "error", resp)

def test_handle_off():
    t.suite("extensions / handle_off")
    setup_with_init()
    ext._state["on"] = True
    status, resp = ext._handle_off(["off"], "GET", None, {})
    t.expect_eq("status 200",        status,         200)
    t.expect_eq("status off",        resp["status"], "off")
    t.expect_false("state off",      ext._state["on"])

def test_handle_stop():
    t.suite("extensions / handle_stop")
    setup_with_init()
    status, resp = ext._handle_stop(["stop"], "GET", None, {})
    t.expect_eq("status 200",        status,          200)
    t.expect_eq("status stopped",    resp["status"],  "stopped")

def test_handle_effect_valid():
    t.suite("extensions / handle_effect valid")
    setup_with_init()
    status, resp = ext._handle_effect(
        ["effect", "TWINKLE"], "GET", None, {})
    t.expect_eq("status 200",           status,           200)
    t.expect_eq("effect name returned", resp["effect"],   "TWINKLE")
    t.expect_eq("state updated",        ext._state["effect"], "TWINKLE")

def test_handle_effect_invalid():
    t.suite("extensions / handle_effect invalid")
    setup_with_init()
    status, resp = ext._handle_effect(
        ["effect", "DOESNOTEXIST"], "GET", None, {})
    t.expect_eq("status 400",  status, 400)
    t.expect_in("error",       "error", resp)
    t.expect_in("options",     "options", resp)

def test_handle_effect_no_name():
    t.suite("extensions / handle_effect no name")
    setup_with_init()
    status, resp = ext._handle_effect(["effect"], "GET", None, {})
    t.expect_eq("status 400",  status, 400)
    t.expect_in("error",       "error", resp)

def test_handle_brightness_valid():
    t.suite("extensions / handle_brightness valid")
    setup_with_init()
    status, resp = ext._handle_brightness(
        ["brightness", "50"], "GET", None, {})
    t.expect_eq("status 200",        status,              200)
    t.expect_eq("brightness in resp", resp["brightness"], 50)
    t.expect_eq("strip 0 updated",
                ext._state["brightness_per_strip"][0], 0.5)

def test_handle_brightness_target():
    t.suite("extensions / handle_brightness with target")
    setup_with_init()
    status, resp = ext._handle_brightness(
        ["brightness", "75", "l1"], "GET", None, {})
    t.expect_eq("status 200",   status, 200)
    t.expect_eq("strip 0 set",
                ext._state["brightness_per_strip"][0], 0.75)
    t.expect_eq("strip 1 unchanged",
                ext._state["brightness_per_strip"][1],
                ext.MAX_BRIGHTNESS)

def test_handle_brightness_invalid():
    t.suite("extensions / handle_brightness invalid")
    setup_with_init()
    status, _ = ext._handle_brightness(
        ["brightness", "abc"], "GET", None, {})
    t.expect_eq("status 400", status, 400)

    status, _ = ext._handle_brightness(
        ["brightness", "150"], "GET", None, {})
    t.expect_eq("out of range 400", status, 400)

def test_handle_colour_valid():
    t.suite("extensions / handle_colour valid")
    setup_with_init()
    status, resp = ext._handle_colour(
        ["colour", "255", "0", "0", "0"], "GET", None, {})
    t.expect_eq("status 200",     status, 200)
    t.expect_eq("colour in resp", resp["colour"], [255, 0, 0, 0])
    t.expect_eq("strip 0 colour",
                ext._state["colour_per_strip"][0], [255, 0, 0, 0])

def test_handle_colour_with_target():
    t.suite("extensions / handle_colour with target")
    setup_with_init()
    status, resp = ext._handle_colour(
        ["colour", "100", "50", "25", "0", "l1"],
        "GET", None, {})
    t.expect_eq("status 200",    status, 200)
    t.expect_eq("l1 colour set",
                ext._state["colour_per_strip"][0], [100, 50, 25, 0])
    t.expect_eq("l2 colour unchanged",
                ext._state["colour_per_strip"][1],
                ext.DEFAULT_COLOUR)

def test_handle_colour_invalid():
    t.suite("extensions / handle_colour invalid")
    setup_with_init()
    status, _ = ext._handle_colour(
        ["colour", "abc", "0", "0"], "GET", None, {})
    t.expect_eq("too few parts 400", status, 400)

def test_handle_status():
    t.suite("extensions / handle_status")
    setup_with_init()
    status, resp = ext._handle_status(["status"], "GET", None, {})
    t.expect_eq("status 200",         status, 200)
    t.expect_in("on",                 "on",              resp)
    t.expect_in("effect",             "effect",          resp)
    t.expect_in("brightness",         "brightness",      resp)
    t.expect_in("effects",            "effects",         resp)
    t.expect_in("ext_version",        "ext_version",     resp)
    t.expect_in("ext_slot",           "ext_slot",        resp)
    t.expect_eq("ext_version matches", resp["ext_version"], ext.EXT_VERSION)
    t.expect_eq("ext_slot matches",    resp["ext_slot"],    ext.EXT_SLOT)

def test_handle_set_on():
    t.suite("extensions / handle_set on")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST", {"on": True}, {})
    t.expect_eq("status 200",       status,          200)
    t.expect_in("on in changes",    "on",            resp["changes"])
    t.expect_true("state on",       ext._state["on"])

def test_handle_set_off():
    t.suite("extensions / handle_set off")
    setup_with_init()
    ext._state["on"] = True
    status, resp = ext._handle_set(
        ["set"], "POST", {"on": False}, {})
    t.expect_eq("status 200",       status,          200)
    t.expect_in("off in changes",   "off",           resp["changes"])
    t.expect_false("state off",     ext._state["on"])

def test_handle_set_brightness():
    t.suite("extensions / handle_set brightness")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST", {"brightness": 60}, {})
    t.expect_eq("status 200",    status, 200)
    t.expect_eq("brightness set",
                ext._state["brightness_per_strip"][0], 0.6)

def test_handle_set_colour():
    t.suite("extensions / handle_set colour")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST",
        {"colour": [200, 100, 50, 0]}, {})
    t.expect_eq("status 200",   status, 200)
    t.expect_eq("colour set",
                ext._state["colour"][0], 200)

def test_handle_set_effect():
    t.suite("extensions / handle_set effect")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST", {"effect": "PULSE"}, {})
    t.expect_eq("status 200",      status, 200)
    t.expect_eq("effect updated",
                ext._state["effect"], "PULSE")

def test_handle_set_leds():
    t.suite("extensions / handle_set leds")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST",
        {"leds": {
            "0": {"colour": [255, 0, 0, 0], "twinkle": True},
            "1": {"colour": [0, 255, 0, 0], "twinkle": False},
        }}, {})
    t.expect_eq("status 200",        status, 200)
    t.expect_eq("LED 0 colour set",
                ext._state["colour_per_led"][0][0], [255, 0, 0, 0])
    t.expect_eq("LED 1 colour set",
                ext._state["colour_per_led"][0][1], [0, 255, 0, 0])
    t.expect_true("LED 0 twinkle pinned True",
                  ext._state["twinkle_per_led"][0][0])
    t.expect_false("LED 1 twinkle pinned False",
                   ext._state["twinkle_per_led"][0][1])

def test_handle_set_clear_leds():
    t.suite("extensions / handle_set clear_leds")
    setup_with_init()
    ext._state["colour_per_led"][0][0]  = [255, 0, 0, 0]
    ext._state["twinkle_per_led"][0][0] = True
    status, resp = ext._handle_set(
        ["set"], "POST", {"clear_leds": True}, {})
    t.expect_eq("status 200",            status, 200)
    t.expect_none("LED 0 colour cleared",
                  ext._state["colour_per_led"][0][0])
    t.expect_none("LED 0 twinkle cleared",
                  ext._state["twinkle_per_led"][0][0])

def test_handle_set_wrong_method():
    t.suite("extensions / handle_set wrong method")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "GET", None, {})
    t.expect_eq("status 405", status, 405)

def test_handle_set_invalid_body():
    t.suite("extensions / handle_set invalid body")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST", "not a dict", {})
    t.expect_eq("status 400", status, 400)

def test_handle_set_target():
    t.suite("extensions / handle_set with target")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST",
        {"target": "left", "brightness": 80}, {})
    t.expect_eq("status 200",   status, 200)
    t.expect_eq("L1 updated",
                ext._state["brightness_per_strip"][0], 0.8)
    t.expect_eq("L2 updated",
                ext._state["brightness_per_strip"][1], 0.8)
    t.expect_eq("R1 unchanged",
                ext._state["brightness_per_strip"][2],
                ext.MAX_BRIGHTNESS)

def test_handle_set_invalid_target():
    t.suite("extensions / handle_set invalid target")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST",
        {"target": "nowhere", "brightness": 50}, {})
    t.expect_eq("status 400", status, 400)

def test_handle_set_invalid_led_index():
    t.suite("extensions / handle_set invalid LED index")
    setup_with_init()
    status, resp = ext._handle_set(
        ["set"], "POST",
        {"leds": {"999": {"colour": [255, 0, 0, 0]}}}, {})
    t.expect_eq("status 400",  status, 400)
    t.expect_in("error list",  "error", resp)

# ============================================================
# EFFECT ENGINE TESTS
# ============================================================

def test_engine_initial_state():
    t.suite("extensions / engine initial state")
    setup_with_init()
    t.expect_false("not running",    ext._engine["running"])
    t.expect_false("not fading",     ext._engine["fading_out"])
    t.expect_none("no effect",       ext._engine["effect"])

def test_start_effect_sets_running():
    t.suite("extensions / start_effect sets running")
    setup_with_init()
    ext._start_effect("SOLID", [0])
    # SOLID immediately sets running=False after fill
    # other effects should be running
    ext._start_effect("CHASE_SMOOTH", [0])
    t.expect_true("chase is running", ext._engine["running"])
    t.expect_eq("effect set",
                ext._engine["effect"], "CHASE_SMOOTH")

def test_start_effect_solid_not_running():
    t.suite("extensions / solid effect not running after init")
    setup_with_init()
    ext._start_effect("SOLID", [0])
    t.expect_false("solid not running", ext._engine["running"])

def test_stop_effect():
    t.suite("extensions / stop_effect")
    setup_with_init()
    ext._start_effect("CHASE_SMOOTH", [0])
    t.expect_true("running before stop", ext._engine["running"])
    ext._stop_effect()
    # stop triggers fade-out
    t.expect_true("fading after stop",   ext._engine["fading_out"])

def test_tick_does_not_crash():
    t.suite("extensions / tick does not crash")
    setup_with_init()
    try:
        for _ in range(10):
            ext.tick()
        t.expect_true("10 ticks without error", True)
    except Exception as e:
        t.expect_true(f"tick raised: {e}", False)

def test_start_effect_unknown():
    t.suite("extensions / start_effect unknown effect")
    setup_with_init()
    ext._start_effect("DOES_NOT_EXIST", [0])
    t.expect_false("not running for unknown effect",
                   ext._engine["running"])

def test_effects_dict_valid():
    t.suite("extensions / EFFECTS dict valid")
    setup()
    valid_types = {"chase", "twinkle", "pulse", "wave", "solid"}
    for name, defn in ext.EFFECTS.items():
        t.expect_in(f"{name} has type",   "type",   defn)
        t.expect_in(f"{name} has params", "params", defn)
        t.expect_in(f"{name} type valid",
                    defn["type"], valid_types)

# ============================================================
# INTEGRATION TESTS
# ============================================================

def test_http_server_routes_to_extension():
    t.suite("extensions / http_server routes to extension handlers")
    setup_with_init()
    # Dispatch via http_server — should reach our handlers
    status, resp = http_server.dispatch(
        ["status"], "GET", None, {})
    t.expect_eq("status 200 via dispatch", status, 200)
    t.expect_in("on in resp",              "on",   resp)

def test_on_off_via_dispatch():
    t.suite("extensions / on/off via http_server dispatch")
    setup_with_init()
    status, resp = http_server.dispatch(["on"], "GET", None, {})
    t.expect_eq("on status 200",   status,         200)
    t.expect_true("state is on",   ext._state["on"])

    status, resp = http_server.dispatch(["off"], "GET", None, {})
    t.expect_eq("off status 200",  status,         200)
    t.expect_false("state is off", ext._state["on"])

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_identity_fields()
    test_hardware_constants()
    test_setup_initialises_strips()
    test_setup_initialises_engine()
    test_setup_loads_default_state()
    test_setup_registers_handlers()
    test_teardown_unregisters_handlers()
    test_teardown_saves_state()
    test_state_roundtrip()
    test_state_default_on_missing_file()
    test_state_clamps_brightness()
    test_make_colour_brightness()
    test_make_colour_clamps()
    test_make_colour_zero_brightness()
    test_validate_colour_valid()
    test_validate_colour_invalid()
    test_safe_int()
    test_resolve_target()
    test_resolve_led_colour()
    test_handle_on_all()
    test_handle_on_target()
    test_handle_on_invalid_target()
    test_handle_off()
    test_handle_stop()
    test_handle_effect_valid()
    test_handle_effect_invalid()
    test_handle_effect_no_name()
    test_handle_brightness_valid()
    test_handle_brightness_target()
    test_handle_brightness_invalid()
    test_handle_colour_valid()
    test_handle_colour_with_target()
    test_handle_colour_invalid()
    test_handle_status()
    test_handle_set_on()
    test_handle_set_off()
    test_handle_set_brightness()
    test_handle_set_colour()
    test_handle_set_effect()
    test_handle_set_leds()
    test_handle_set_clear_leds()
    test_handle_set_wrong_method()
    test_handle_set_invalid_body()
    test_handle_set_target()
    test_handle_set_invalid_target()
    test_handle_set_invalid_led_index()
    test_engine_initial_state()
    test_start_effect_sets_running()
    test_start_effect_solid_not_running()
    test_stop_effect()
    test_tick_does_not_crash()
    test_start_effect_unknown()
    test_effects_dict_valid()
    test_http_server_routes_to_extension()
    test_on_off_via_dispatch()
    cleanup()
    return t.summary()

run()