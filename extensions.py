# extensions.py
# LED control endpoints and effect engine.
# Loaded by main.py via slots — can be updated OTA.
# Registers HTTP handlers with http_server on setup().
#
# Required interface (validated by ota.validate_ext):
#   EXT_SLOT, EXT_VERSION, NUM_LEDS, MAX_BRIGHTNESS,
#   PIN_L1, PIN_L2, PIN_R1, PIN_R2
#   setup(env), tick(), handle_request(...), teardown()

import machine
import neopixel
import time
import json
import random
import http_server
import logger

# ============================================================
# IDENTITY
# ============================================================

EXT_SLOT    = "a"   # patched to "b" by OTA when writing extensions_b.py
EXT_VERSION = 1

# ============================================================
# HARDWARE CONFIG
# ============================================================

NUM_LEDS         = 22
MAX_BRIGHTNESS   = 0.3
DEFAULT_COLOUR   = [15, 5, 0, 80]
PIN_L1           = 0
PIN_L2           = 1
PIN_R1           = 2
PIN_R2           = 3
STRIP_DIRECTIONS = [True, True, False, False]
STRIP_LABELS     = ["L1", "L2", "R1", "R2"]

STRIP_MAP = {
    "l1":    [0],
    "l2":    [1],
    "r1":    [2],
    "r2":    [3],
    "left":  [0, 1],
    "right": [2, 3],
    "all":   [0, 1, 2, 3],
}

# ============================================================
# EFFECT DEFINITIONS
# ============================================================

EFFECTS = {
    "CHASE_SNAPPY": {
        "type": "chase",
        "params": {"fade_time": 300, "chase_offset": 30}
    },
    "CHASE_SMOOTH": {
        "type": "chase",
        "params": {"fade_time": 1000, "chase_offset": 80}
    },
    "CHASE_DRAMATIC": {
        "type": "chase",
        "params": {"fade_time": 2000, "chase_offset": 200}
    },
    "CHASE_TOGETHER": {
        "type": "chase",
        "params": {"fade_time": 1000, "chase_offset": 0}
    },
    "TWINKLE": {
        "type": "twinkle",
        "params": {"speed": 80, "depth": 0.4, "coverage": 0.3}
    },
    "TWINKLE_SLOW": {
        "type": "twinkle",
        "params": {"speed": 200, "depth": 0.2, "coverage": 0.2}
    },
    "TWINKLE_WILD": {
        "type": "twinkle",
        "params": {"speed": 20, "depth": 0.8, "coverage": 0.6}
    },
    "PULSE": {
        "type": "pulse",
        "params": {"rate": 2000, "min_bright": 0.05, "max_bright": 1.0}
    },
    "PULSE_SLOW": {
        "type": "pulse",
        "params": {"rate": 4000, "min_bright": 0.1, "max_bright": 0.8}
    },
    "PULSE_FAST": {
        "type": "pulse",
        "params": {"rate": 800, "min_bright": 0.0, "max_bright": 1.0}
    },
    "WAVE": {
        "type": "wave",
        "params": {"width": 6, "speed": 60, "direction": 1, "falloff": 0.5}
    },
    "WAVE_WIDE": {
        "type": "wave",
        "params": {"width": 10, "speed": 80, "direction": 1, "falloff": 0.7}
    },
    "WAVE_NARROW": {
        "type": "wave",
        "params": {"width": 3, "speed": 40, "direction": 1, "falloff": 0.3}
    },
    "WAVE_REVERSE": {
        "type": "wave",
        "params": {"width": 6, "speed": 60, "direction": -1, "falloff": 0.5}
    },
    "SOLID": {
        "type": "solid",
        "params": {}
    },
}

FADE_STEPS = 20
STATE_FILE = "shelf_state.json"

# ============================================================
# MODULE STATE
# ============================================================

_strips = None
_state  = None
_engine = None

# ============================================================
# INTERFACE — called by main.py
# ============================================================

def setup(env):
    """
    Initialise hardware, load state, register HTTP handlers.
    Called by main.py after WiFi connects.
    env — dict from .env file (passed in, not imported directly)
    """
    global _strips, _state, _engine

    logger.info("Extensions setup",
                data={"slot": EXT_SLOT, "version": EXT_VERSION})

    # Initialise strips
    _strips = [
        neopixel.NeoPixel(machine.Pin(PIN_L1), NUM_LEDS, bpp=4),
        neopixel.NeoPixel(machine.Pin(PIN_L2), NUM_LEDS, bpp=4),
        neopixel.NeoPixel(machine.Pin(PIN_R1), NUM_LEDS, bpp=4),
        neopixel.NeoPixel(machine.Pin(PIN_R2), NUM_LEDS, bpp=4),
    ]

    # Initialise engine
    _engine = _make_engine()

    # Load persisted state
    _state = _load_state()

    # Clear strips on boot
    _clear_target([0, 1, 2, 3])

    # Restore previous on/off state
    if _state["on"]:
        logger.info("Restoring previous state — lights on")
        _start_effect(_state["effect"], [0, 1, 2, 3])
    else:
        logger.info("Previous state — lights off")

    # Register HTTP handlers
    http_server.register("on",         _handle_on)
    http_server.register("off",        _handle_off)
    http_server.register("stop",       _handle_stop)
    http_server.register("effect",     _handle_effect)
    http_server.register("brightness", _handle_brightness)
    http_server.register("colour",     _handle_colour)
    http_server.register("status",     _handle_status)
    http_server.register("set",        _handle_set)

    logger.info("Extensions ready",
                data={"effects": list(EFFECTS.keys()),
                      "strips": STRIP_LABELS})

def tick():
    """Advance effect engine one step. Called every main loop iteration."""
    _tick_effect()

def handle_request(parts, method, body, query):
    """
    Legacy compatibility shim.
    http_server.dispatch() calls handlers directly via register(),
    so this is only called if main.py routes here explicitly.
    """
    return http_server.dispatch(parts, method, body, query)

def teardown():
    """
    Clean up before reboot or slot swap.
    Called by main.py before rebooting.
    """
    logger.info("Extensions teardown")
    if _strips is not None:
        _clear_target([0, 1, 2, 3])
    _save_state(_state)

    # Unregister all handlers we registered
    for cmd in ("on", "off", "stop", "effect",
                "brightness", "colour", "status", "set"):
        http_server.unregister(cmd)

# ============================================================
# STATE
# ============================================================

def _default_state():
    return {
        "on":                   False,
        "brightness":           MAX_BRIGHTNESS,
        "brightness_per_strip": [MAX_BRIGHTNESS] * 4,
        "colour":               DEFAULT_COLOUR[:],
        "colour_per_strip":     [DEFAULT_COLOUR[:] for _ in range(4)],
        "colour_per_led":       [[None] * NUM_LEDS for _ in range(4)],
        "twinkle_per_led":      [[None] * NUM_LEDS for _ in range(4)],
        "effect":               "CHASE_SMOOTH",
        "effect_params":        {},
    }

def _load_state():
    try:
        with open(STATE_FILE, "r") as f:
            saved = json.load(f)
        state = _default_state()
        if isinstance(saved.get("on"), bool):
            state["on"] = saved["on"]
        if isinstance(saved.get("brightness"), float):
            state["brightness"] = max(0.0, min(1.0, saved["brightness"]))
        if (isinstance(saved.get("brightness_per_strip"), list) and
                len(saved["brightness_per_strip"]) == 4):
            state["brightness_per_strip"] = [
                max(0.0, min(1.0, b))
                for b in saved["brightness_per_strip"]]
        if saved.get("effect") in EFFECTS:
            state["effect"] = saved["effect"]
        if isinstance(saved.get("effect_params"), dict):
            state["effect_params"] = saved["effect_params"]
        if (isinstance(saved.get("colour"), list) and
                len(saved["colour"]) == 4):
            state["colour"] = [
                max(0, min(255, int(c))) for c in saved["colour"]]
        if (isinstance(saved.get("colour_per_strip"), list) and
                len(saved["colour_per_strip"]) == 4):
            state["colour_per_strip"] = [
                [max(0, min(255, int(c))) for c in col]
                for col in saved["colour_per_strip"]
                if isinstance(col, list) and len(col) == 4
            ]
        if (isinstance(saved.get("colour_per_led"), list) and
                len(saved["colour_per_led"]) == 4):
            validated = []
            for strip_leds in saved["colour_per_led"]:
                if (isinstance(strip_leds, list) and
                        len(strip_leds) == NUM_LEDS):
                    validated.append([
                        [max(0, min(255, int(c))) for c in led]
                        if isinstance(led, list) and len(led) == 4
                        else None
                        for led in strip_leds
                    ])
                else:
                    validated.append([None] * NUM_LEDS)
            state["colour_per_led"] = validated
        if (isinstance(saved.get("twinkle_per_led"), list) and
                len(saved["twinkle_per_led"]) == 4):
            state["twinkle_per_led"] = saved["twinkle_per_led"]
        logger.info("State loaded")
        return state
    except Exception as e:
        logger.warn("State load failed — using defaults",
                    data={"error": str(e)})
        return _default_state()

def _save_state(state):
    if state is None:
        return
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.error("State save failed", data={"error": str(e)})

# ============================================================
# LED HELPERS
# ============================================================

def _make_colour(r, g, b, w, brightness):
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    w = max(0, min(255, int(w)))
    brightness = max(0.0, min(1.0, brightness))
    return (
        int(r * brightness),
        int(g * brightness),
        int(b * brightness),
        int(w * brightness)
    )

def _resolve_led_colour(s, i):
    per_led = _state["colour_per_led"][s][i]
    if per_led is not None:
        return per_led
    return _state["colour_per_strip"][s]

def _clear_target(targets):
    if _strips is None:
        return
    for s in targets:
        try:
            for i in range(NUM_LEDS):
                _strips[s][i] = (0, 0, 0, 0)
            _strips[s].write()
        except Exception as e:
            logger.error("Clear error",
                         data={"strip": STRIP_LABELS[s],
                               "error": str(e)})

def _fill_target(targets):
    if _strips is None:
        return
    for s in targets:
        try:
            brightness = _state["brightness_per_strip"][s]
            for i in range(NUM_LEDS):
                r, g, b, w = _resolve_led_colour(s, i)
                _strips[s][i] = _make_colour(r, g, b, w, brightness)
            _strips[s].write()
        except Exception as e:
            logger.error("Fill error",
                         data={"strip": STRIP_LABELS[s],
                               "error": str(e)})

def _validate_colour(c):
    if isinstance(c, list) and len(c) == 4:
        try:
            return [max(0, min(255, int(v))) for v in c]
        except:
            return None
    return None

def _get_effect_params(effect_key, strip_idx=None):
    base = EFFECTS[effect_key]["params"].copy()
    if strip_idx is not None:
        label     = STRIP_LABELS[strip_idx]
        overrides = _state["effect_params"].get(label, {})
        base.update(overrides)
    return base

def _safe_int(value, min_val=None, max_val=None):
    try:
        v = int(value)
        if min_val is not None and v < min_val:
            return None
        if max_val is not None and v > max_val:
            return None
        return v
    except:
        return None

def _resolve_target(parts, offset):
    if len(parts) > offset:
        key = parts[offset].lower()
        if key in STRIP_MAP:
            return STRIP_MAP[key]
        return None
    return [0, 1, 2, 3]

def _resolve_target_from_str(target_str):
    if target_str is None:
        return [0, 1, 2, 3]
    return STRIP_MAP.get(str(target_str).lower(), None)

# ============================================================
# EFFECT ENGINE
# ============================================================

def _make_engine():
    return {
        "effect":        None,
        "effect_type":   None,
        "targets":       [],
        "running":       False,
        "fading_out":    False,
        "fade_levels":   [],
        "fade_tick":     0,
        "fade_total":    FADE_STEPS,
        "fade_delay":    50,
        "fade_last_ms":  0,
        "pending":       None,
        "state":         {},
        "last_tick_ms":  0,
    }

def _capture_current_levels():
    if _strips is None:
        return []
    levels = []
    for s in _engine["targets"]:
        strip_levels = []
        for i in range(NUM_LEDS):
            pixel   = _strips[s][i]
            max_val = max(pixel) if pixel else 0
            strip_levels.append(max_val / 255.0)
        levels.append(strip_levels)
    return levels

def _start_fade_out(pending=None):
    _engine["fading_out"]   = True
    _engine["running"]      = False
    _engine["fade_tick"]    = 0
    _engine["fade_total"]   = FADE_STEPS
    _engine["fade_delay"]   = 50
    _engine["fade_last_ms"] = time.ticks_ms()
    _engine["fade_levels"]  = _capture_current_levels()
    _engine["pending"]      = pending
    logger.info("Fade-out started",
                data={"pending": pending["effect"] if pending else None})

def _tick_fade_out():
    if not _engine["fading_out"]:
        return
    now = time.ticks_ms()
    if time.ticks_diff(now, _engine["fade_last_ms"]) < _engine["fade_delay"]:
        return
    _engine["fade_last_ms"] = now
    tick  = _engine["fade_tick"]
    total = _engine["fade_total"]
    t     = tick / total
    scale = 1.0 - (t * t * (3 - 2 * t))

    for idx, s in enumerate(_engine["targets"]):
        try:
            for i in range(NUM_LEDS):
                level      = _engine["fade_levels"][idx][i] * scale
                r, g, b, w = _resolve_led_colour(s, i)
                _strips[s][i] = _make_colour(r, g, b, w, level)
            _strips[s].write()
        except Exception as e:
            logger.error("Fade-out error",
                         data={"strip": STRIP_LABELS[s],
                               "error": str(e)})

    _engine["fade_tick"] += 1
    if _engine["fade_tick"] >= _engine["fade_total"]:
        _engine["fading_out"] = False
        _clear_target(_engine["targets"])
        logger.info("Fade-out complete")
        if _engine["pending"]:
            pending            = _engine["pending"]
            _engine["pending"] = None
            _start_effect(pending["effect"], pending["targets"])

def _start_effect(effect_key, targets, mode="in"):
    if _engine["running"] or _engine["fading_out"]:
        pending = (None if mode == "out"
                   else {"effect": effect_key, "targets": targets})
        _start_fade_out(pending)
        return
    if mode == "out":
        _clear_target(targets)
        return
    if effect_key not in EFFECTS:
        logger.error("Unknown effect", data={"effect": effect_key})
        return
    effect_type             = EFFECTS[effect_key]["type"]
    _engine["effect"]       = effect_key
    _engine["effect_type"]  = effect_type
    _engine["targets"]      = targets
    _engine["running"]      = True
    _engine["state"]        = {}
    _engine["last_tick_ms"] = time.ticks_ms()
    logger.info("Effect started",
                data={"effect": effect_key, "type": effect_type,
                      "strips": [STRIP_LABELS[s] for s in targets]})
    if effect_type == "chase":
        _init_chase(targets, effect_key)
    elif effect_type == "twinkle":
        _init_twinkle(targets, effect_key)
    elif effect_type == "pulse":
        _init_pulse(targets, effect_key)
    elif effect_type == "wave":
        _init_wave(targets, effect_key)
    elif effect_type == "solid":
        _init_solid(targets)

def _stop_effect():
    if _engine["running"] or _engine["fading_out"]:
        _start_fade_out(pending=None)
    else:
        _clear_target(_engine["targets"] if _engine["targets"]
                      else [0, 1, 2, 3])
    _engine["running"] = False

def _tick_effect():
    if _engine is None:
        return
    if _engine["fading_out"]:
        _tick_fade_out()
        return
    if not _engine["running"]:
        return
    effect_type = _engine["effect_type"]
    if effect_type == "chase":
        _tick_chase()
    elif effect_type == "twinkle":
        _tick_twinkle()
    elif effect_type == "pulse":
        _tick_pulse()
    elif effect_type == "wave":
        _tick_wave()

# ============================================================
# CHASE
# ============================================================

def _init_chase(targets, effect_key):
    params       = _get_effect_params(effect_key)
    fade_time    = params.get("fade_time", 1000)
    chase_offset = params.get("chase_offset", 80)
    fade_delay   = max(1, fade_time // FADE_STEPS)
    offset_ticks = (max(1, chase_offset // fade_delay)
                    if chase_offset > 0 else 0)
    total_ticks  = FADE_STEPS + (NUM_LEDS * offset_ticks)
    _engine["state"] = {
        "tick":         0,
        "total_ticks":  total_ticks,
        "offset_ticks": offset_ticks,
        "fade_delay":   fade_delay,
        "last_tick_ms": time.ticks_ms(),
        "levels":       [[0.0] * NUM_LEDS for _ in targets],
    }

def _tick_chase():
    es  = _engine["state"]
    now = time.ticks_ms()
    if time.ticks_diff(now, es["last_tick_ms"]) < es["fade_delay"]:
        return
    es["last_tick_ms"] = now
    tick         = es["tick"]
    offset_ticks = es["offset_ticks"]
    levels       = es["levels"]
    for idx, s in enumerate(_engine["targets"]):
        reverse    = STRIP_DIRECTIONS[s]
        brightness = _state["brightness_per_strip"][s]
        for i in range(NUM_LEDS):
            order    = (NUM_LEDS - 1 - i) if reverse else i
            led_tick = tick - (order * offset_ticks)
            if led_tick < 0:
                continue
            elif led_tick <= FADE_STEPS:
                t_    = led_tick / FADE_STEPS
                eased = t_ * t_ * (3 - 2 * t_)
                levels[idx][i] = 0.1 + (brightness - 0.1) * eased
            else:
                levels[idx][i] = brightness
        try:
            for i in range(NUM_LEDS):
                r, g, b, w = _resolve_led_colour(s, i)
                _strips[s][i] = _make_colour(r, g, b, w, levels[idx][i])
            _strips[s].write()
        except Exception as e:
            logger.error("Chase error",
                         data={"strip": STRIP_LABELS[s],
                               "error": str(e)})
    es["tick"] += 1
    if es["tick"] >= es["total_ticks"]:
        _engine["running"] = False
        logger.info("Chase complete")

# ============================================================
# TWINKLE
# ============================================================

def _init_twinkle(targets, effect_key):
    _engine["state"] = {}
    for s in targets:
        params     = _get_effect_params(effect_key, s)
        led_states = []
        for i in range(NUM_LEDS):
            pinned = _state["twinkle_per_led"][s][i]
            led_states.append({
                "pinned": pinned,
                "level":  _state["brightness_per_strip"][s],
                "target": _state["brightness_per_strip"][s],
            })
        _engine["state"][s] = {
            "params":       params,
            "led_states":   led_states,
            "last_tick_ms": time.ticks_ms(),
        }
    _fill_target(targets)

def _tick_twinkle():
    for s in _engine["targets"]:
        es  = _engine["state"][s]
        now = time.ticks_ms()
        if time.ticks_diff(now, es["last_tick_ms"]) < \
                es["params"].get("speed", 80):
            continue
        es["last_tick_ms"] = now
        brightness = _state["brightness_per_strip"][s]
        depth      = es["params"].get("depth", 0.4)
        coverage   = es["params"].get("coverage", 0.3)
        led_states = es["led_states"]
        try:
            for i in range(NUM_LEDS):
                ls = led_states[i]
                if ls["pinned"] is True:
                    should = True
                elif ls["pinned"] is False:
                    should = False
                else:
                    should = random.random() < coverage
                if should:
                    low  = max(0.0, brightness - depth)
                    high = min(1.0, brightness + depth * 0.3)
                    ls["target"] = low + random.random() * (high - low)
                else:
                    ls["target"] = brightness
                diff        = ls["target"] - ls["level"]
                ls["level"] = ls["level"] + diff * 0.3
                r, g, b, w  = _resolve_led_colour(s, i)
                _strips[s][i] = _make_colour(r, g, b, w, ls["level"])
            _strips[s].write()
        except Exception as e:
            logger.error("Twinkle error",
                         data={"strip": STRIP_LABELS[s],
                               "error": str(e)})

# ============================================================
# PULSE
# ============================================================

def _init_pulse(targets, effect_key):
    _engine["state"] = {}
    for s in targets:
        params = _get_effect_params(effect_key, s)
        _engine["state"][s] = {
            "params":       params,
            "phase":        0.0,
            "last_tick_ms": time.ticks_ms(),
            "tick_ms":      20,
        }
    _fill_target(targets)

def _tick_pulse():
    import math
    for s in _engine["targets"]:
        es  = _engine["state"][s]
        now = time.ticks_ms()
        if time.ticks_diff(now, es["last_tick_ms"]) < es["tick_ms"]:
            continue
        es["last_tick_ms"] = now
        params     = es["params"]
        rate       = params.get("rate", 2000)
        min_bright = params.get("min_bright", 0.05)
        max_bright = params.get("max_bright", 1.0)
        step       = es["tick_ms"] / rate
        es["phase"] = (es["phase"] + step) % 1.0
        sine       = math.sin(es["phase"] * 2 * math.pi)
        t_         = (sine + 1.0) / 2.0
        max_b      = min(max_bright, _state["brightness_per_strip"][s])
        brightness = min_bright + t_ * (max_b - min_bright)
        try:
            for i in range(NUM_LEDS):
                r, g, b, w = _resolve_led_colour(s, i)
                _strips[s][i] = _make_colour(r, g, b, w, brightness)
            _strips[s].write()
        except Exception as e:
            logger.error("Pulse error",
                         data={"strip": STRIP_LABELS[s],
                               "error": str(e)})

# ============================================================
# WAVE
# ============================================================

def _init_wave(targets, effect_key):
    _engine["state"] = {}
    for s in targets:
        params    = _get_effect_params(effect_key, s)
        direction = params.get("direction", 1)
        start_pos = (-params.get("width", 6)
                     if direction == 1 else float(NUM_LEDS))
        _engine["state"][s] = {
            "params":       params,
            "position":     start_pos,
            "last_tick_ms": time.ticks_ms(),
        }

def _tick_wave():
    for s in _engine["targets"]:
        es     = _engine["state"][s]
        now    = time.ticks_ms()
        params = es["params"]
        if time.ticks_diff(now, es["last_tick_ms"]) < \
                params.get("speed", 60):
            continue
        es["last_tick_ms"] = now
        width      = params.get("width", 6)
        direction  = params.get("direction", 1)
        falloff    = params.get("falloff", 0.5)
        pos        = es["position"]
        brightness = _state["brightness_per_strip"][s]
        try:
            for i in range(NUM_LEDS):
                dist = abs(i - pos)
                if dist <= width / 2:
                    if falloff > 0:
                        edge_dist = dist / (width / 2)
                        t_        = 1.0 - (edge_dist **
                                          (1.0 / max(falloff, 0.01)))
                        level     = brightness * max(0.0, min(1.0, t_))
                    else:
                        level = brightness
                else:
                    level = 0.0
                r, g, b, w = _resolve_led_colour(s, i)
                _strips[s][i] = _make_colour(r, g, b, w, level)
            _strips[s].write()
        except Exception as e:
            logger.error("Wave error",
                         data={"strip": STRIP_LABELS[s],
                               "error": str(e)})
        es["position"] = pos + direction
        if direction == 1 and pos > NUM_LEDS + width:
            es["position"] = -width
        elif direction == -1 and pos < -width:
            es["position"] = float(NUM_LEDS + width)

# ============================================================
# SOLID
# ============================================================

def _init_solid(targets):
    _fill_target(targets)
    _engine["running"] = False

# ============================================================
# HTTP HANDLERS
# ============================================================

def _handle_on(parts, method, body, query):
    """GET /on, GET /on/<target>"""
    targets = _resolve_target(parts, offset=1)
    if targets is None:
        return 400, {"error": f"Unknown target: {parts[1]}"}
    _state["on"] = True
    _start_effect(_state["effect"], targets, mode="in")
    _save_state(_state)
    return 200, {
        "status": "on",
        "strips": [STRIP_LABELS[s] for s in targets],
        "effect": _state["effect"],
    }

def _handle_off(parts, method, body, query):
    """GET /off, GET /off/<target>"""
    targets = _resolve_target(parts, offset=1)
    if targets is None:
        return 400, {"error": f"Unknown target: {parts[1]}"}
    if sorted(targets) == [0, 1, 2, 3]:
        _state["on"] = False
    _start_effect(_state["effect"], targets, mode="out")
    _save_state(_state)
    return 200, {
        "status": "off",
        "strips": [STRIP_LABELS[s] for s in targets],
        "effect": _state["effect"],
    }

def _handle_stop(parts, method, body, query):
    """GET /stop"""
    _stop_effect()
    logger.info("Effect stopped via HTTP")
    return 200, {"status": "stopped"}

def _handle_effect(parts, method, body, query):
    """GET /effect/<name>, GET /effect/<name>/<target>"""
    if len(parts) < 2:
        return 400, {
            "error": "Effect name required",
            "options": list(EFFECTS.keys())
        }
    key = parts[1].upper()
    if key not in EFFECTS:
        return 400, {
            "error": f"Unknown effect: {key}",
            "options": list(EFFECTS.keys())
        }
    targets = _resolve_target(parts, offset=2)
    if targets is None:
        return 400, {"error": f"Unknown target: {parts[2]}"}
    _state["effect"] = key
    if _state["on"]:
        _start_effect(key, targets, mode="in")
    _save_state(_state)
    logger.info("Effect changed", data={"effect": key})
    return 200, {
        "effect":  key,
        "type":    EFFECTS[key]["type"],
        "params":  EFFECTS[key]["params"],
        "strips":  [STRIP_LABELS[s] for s in targets],
    }

def _handle_brightness(parts, method, body, query):
    """GET /brightness/<0-100>, GET /brightness/<0-100>/<target>"""
    if len(parts) < 2:
        return 400, {"error": "Brightness value required"}
    pct = _safe_int(parts[1], min_val=0, max_val=100)
    if pct is None:
        return 400, {"error": f"Invalid brightness: {parts[1]} — must be 0-100"}
    targets = _resolve_target(parts, offset=2)
    if targets is None:
        return 400, {"error": f"Unknown target: {parts[2]}"}
    brightness = pct / 100
    for s in targets:
        _state["brightness_per_strip"][s] = brightness
    if sorted(targets) == [0, 1, 2, 3]:
        _state["brightness"] = brightness
    if (_state["on"] and
            not _engine["running"] and
            not _engine["fading_out"]):
        _fill_target(targets)
    _save_state(_state)
    return 200, {
        "brightness": pct,
        "strips":     [STRIP_LABELS[s] for s in targets],
    }

def _handle_colour(parts, method, body, query):
    """GET /colour/<r>/<g>/<b>/<w>, GET /colour/<r>/<g>/<b>/<w>/<target>"""
    if len(parts) < 4:
        return 400, {"error": "Colour requires r/g/b/w — e.g. /colour/15/5/0/80"}
    r = _safe_int(parts[1], 0, 255)
    g = _safe_int(parts[2], 0, 255)
    b = _safe_int(parts[3], 0, 255)
    w = (_safe_int(parts[4], 0, 255)
         if len(parts) >= 5 and parts[4].isdigit() else 0)
    if None in (r, g, b):
        return 400, {"error": "Colour values must be integers 0-255"}
    targets = _resolve_target(parts, offset=5)
    if targets is None:
        return 400, {"error": f"Unknown target: {parts[5]}"}
    for s in targets:
        _state["colour_per_strip"][s] = [r, g, b, w]
    if sorted(targets) == [0, 1, 2, 3]:
        _state["colour"] = [r, g, b, w]
    if (_state["on"] and
            not _engine["running"] and
            not _engine["fading_out"]):
        _fill_target(targets)
    _save_state(_state)
    return 200, {
        "colour": [r, g, b, w],
        "strips": [STRIP_LABELS[s] for s in targets],
    }

def _handle_status(parts, method, body, query):
    """GET /status"""
    return 200, {
        "on":                   _state["on"],
        "effect":               _state["effect"],
        "effect_type":          EFFECTS.get(
                                    _state["effect"], {}).get("type"),
        "effect_params":        _state["effect_params"],
        "brightness":           _state["brightness"],
        "brightness_per_strip": {
            STRIP_LABELS[s]: _state["brightness_per_strip"][s]
            for s in range(4)
        },
        "colour":               _state["colour"],
        "colour_per_strip":     {
            STRIP_LABELS[s]: _state["colour_per_strip"][s]
            for s in range(4)
        },
        "strips":               STRIP_LABELS,
        "num_leds":             NUM_LEDS,
        "engine_running":       _engine["running"],
        "engine_fading_out":    _engine["fading_out"],
        "engine_effect":        _engine["effect"],
        "effects":              list(EFFECTS.keys()),
        "ext_version":          EXT_VERSION,
        "ext_slot":             EXT_SLOT,
    }

def _handle_set(parts, method, body, query):
    """
    POST /set — JSON body control.
    {
        "target":        "all"|"left"|"right"|"l1"|"l2"|"r1"|"r2",
        "on":            true|false,
        "effect":        "<effect key>",
        "brightness":    0-100,
        "colour":        [r, g, b, w],
        "effect_params": {"speed": 50, ...},
        "leds": {
            "0": {"colour": [r,g,b,w], "twinkle": true|false|null},
            ...
        },
        "clear_leds": true
    }
    """
    if method != "POST":
        return 405, {"error": "POST required for /set"}
    if not isinstance(body, dict):
        return 400, {"error": "Body must be a JSON object"}

    changes = []
    targets = _resolve_target_from_str(body.get("target"))
    if targets is None:
        return 400, {"error": f"Unknown target: {body.get('target')}"}

    if "effect" in body:
        key = str(body["effect"]).upper()
        if key not in EFFECTS:
            return 400, {"error": f"Unknown effect: {key}"}
        _state["effect"] = key
        changes.append(f"effect={key}")

    if "effect_params" in body:
        if not isinstance(body["effect_params"], dict):
            return 400, {"error": "effect_params must be a JSON object"}
        for s in targets:
            label = STRIP_LABELS[s]
            if label not in _state["effect_params"]:
                _state["effect_params"][label] = {}
            _state["effect_params"][label].update(body["effect_params"])
        changes.append("effect_params updated")

    if "brightness" in body:
        pct = _safe_int(body["brightness"], min_val=0, max_val=100)
        if pct is None:
            return 400, {"error": "brightness must be 0-100"}
        brightness = pct / 100
        for s in targets:
            _state["brightness_per_strip"][s] = brightness
        if sorted(targets) == [0, 1, 2, 3]:
            _state["brightness"] = brightness
        changes.append(f"brightness={pct}%")

    if "colour" in body:
        colour = _validate_colour(body["colour"])
        if colour is None:
            return 400, {"error": "colour must be [r,g,b,w] 0-255"}
        for s in targets:
            _state["colour_per_strip"][s] = colour
        if sorted(targets) == [0, 1, 2, 3]:
            _state["colour"] = colour
        changes.append(f"colour={colour}")

    if body.get("clear_leds"):
        for s in targets:
            _state["colour_per_led"][s]  = [None] * NUM_LEDS
            _state["twinkle_per_led"][s] = [None] * NUM_LEDS
        changes.append("cleared per-LED settings")

    if "leds" in body:
        if not isinstance(body["leds"], dict):
            return 400, {"error": "leds must be a JSON object"}
        errors = []
        count  = 0
        for key, led_data in body["leds"].items():
            idx = _safe_int(key, min_val=0, max_val=NUM_LEDS - 1)
            if idx is None:
                errors.append(f"Invalid LED index: {key}")
                continue
            if not isinstance(led_data, dict):
                errors.append(f"LED {idx} data must be a JSON object")
                continue
            if "colour" in led_data:
                colour = _validate_colour(led_data["colour"])
                if colour is None:
                    errors.append(f"Invalid colour for LED {idx}")
                    continue
                for s in targets:
                    _state["colour_per_led"][s][idx] = colour
            if "twinkle" in led_data:
                twinkle = led_data["twinkle"]
                if twinkle not in (True, False, None):
                    errors.append(
                        f"twinkle for LED {idx} must be true/false/null")
                    continue
                for s in targets:
                    _state["twinkle_per_led"][s][idx] = twinkle
            count += 1
        if errors:
            return 400, {"error": errors}
        changes.append(f"updated {count} LEDs")

    if "on" in body:
        on = body["on"]
        if not isinstance(on, bool):
            return 400, {"error": "on must be true or false"}
        if on:
            _state["on"] = True
            _start_effect(_state["effect"], targets, mode="in")
            changes.append("on")
        else:
            if sorted(targets) == [0, 1, 2, 3]:
                _state["on"] = False
            _start_effect(_state["effect"], targets, mode="out")
            changes.append("off")
    elif (changes and _state["on"] and
          not _engine["running"] and
          not _engine["fading_out"]):
        _fill_target(targets)

    _save_state(_state)
    logger.info("POST /set",
                data={"target": body.get("target", "all"),
                      "changes": changes})
    return 200, {
        "status":  "ok",
        "target":  body.get("target", "all"),
        "changes": changes,
        "effect":  _state["effect"],
    }