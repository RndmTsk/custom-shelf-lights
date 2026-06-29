# main.py
# Entry point — permanent, never replaced via OTA.
# Owns: env loading, watchdog, WiFi, HTTP server,
#       slot management, OTA, built-in endpoints.
# Delegates: LED control, effects → extensions slot.

import time
import json
import machine

# ============================================================
# VERSION
# ============================================================

MAIN_VERSION = "1.0.0"

# ============================================================
# CORE IMPORTS
# ============================================================

import env
import logger
import watchdog
import wifi
import slots
import ota
import http_server

# ============================================================
# STARTUP
# ============================================================

# Load env first — everything depends on it
_env_count = env.load()

# Configure logger before anything else logs
logger.configure(
    log_file="shelf_log.txt",
    max_lines=200,
    min_level=logger.INFO,
    echo_console=True,
)

logger.print_previous_session()

logger.info("=== Shelf Lights Starting ===",
            data={"main_version": MAIN_VERSION,
                  "env_keys": _env_count})

def _feed():
    """Feed watchdog during startup (main loop feeds every iteration)."""
    if watchdog.is_started():
        watchdog.feed()

# Start watchdog — cannot be stopped after this point.
# Pico hardware max is ~8388 ms; feed() during startup until main loop runs.
watchdog.start(timeout_ms=8388)
_feed()

# ============================================================
# CONFIGURE MODULES FROM ENV
# ============================================================

wifi.configure(
    ssid=env.get("WIFI_SSID"),
    password=env.get("WIFI_PASSWORD"),
    static_ip=env.get("STATIC_IP"),
    subnet=env.get("SUBNET",  "255.255.255.0"),
    gateway=env.get("GATEWAY"),
    dns=env.get("DNS", "8.8.8.8"),
)

ota.configure(
    github_user=env.get("GITHUB_USER"),
    github_repo=env.get("GITHUB_REPO"),
    github_branch=env.get("GITHUB_BRANCH", "main"),
    max_fails=env.get_int("OTA_MAX_FAILS", 3),
    backoff_secs=env.get_int("OTA_BACKOFF_SECS", 86400),
)

http_server.configure(
    port=env.get_int("HTTP_PORT", 80),
    timeout_ms=env.get_int("HTTP_TIMEOUT_MS", 3000),
    recv_bytes=env.get_int("HTTP_RECV_BYTES", 2048),
)

# ============================================================
# SLOT SELECTION
# ============================================================

_feed()
_slot = slots.read_slot()
logger.info("Slot selected", data={"slot": _slot})

if not slots.is_slot_healthy(_slot):
    _fallback = slots.other_slot(_slot)
    logger.warn("Slot unhealthy — trying fallback",
                data={"from": _slot, "to": _fallback})
    _slot = _fallback
    slots.write_slot(_slot)

# ============================================================
# LOAD EXTENSIONS
# ============================================================

_ext = None

def _load_ext(slot):
    """
    Load and exec an extensions slot.
    Returns module proxy or None on failure.
    """
    filename = slots.extension_filename(slot)
    logger.info("Loading extensions", data={"file": filename})
    try:
        with open(filename, "r") as f:
            code = f.read()
        _feed()
        ns = {}
        exec(code, ns)
        _feed()

        class _Proxy:
            pass
        mod = _Proxy()
        for k, v in ns.items():
            if not k.startswith("__"):
                setattr(mod, k, v)

        # Quick interface check
        for fn in ("setup", "tick", "handle_request", "teardown"):
            if not hasattr(mod, fn) or not callable(getattr(mod, fn)):
                raise ValueError(f"Missing interface function: {fn}()")

        logger.info("Extensions loaded",
                    data={"slot": slot,
                          "version": getattr(mod, "EXT_VERSION", "?")})
        return mod
    except Exception as e:
        logger.error("Extensions load failed",
                     data={"slot": slot, "error": str(e)})
        return None

_feed()
_ext = _load_ext(_slot)
_feed()

if _ext is None:
    _fallback = slots.other_slot(_slot)
    logger.warn("Trying fallback slot",
                data={"from": _slot, "to": _fallback})
    slots.mark_slot_crashed(_slot)
    _ext = _load_ext(_fallback)
    if _ext is not None:
        _slot = _fallback
        slots.write_slot(_slot)
    else:
        logger.error("Both extension slots failed")

_feed()

# ============================================================
# WIFI + NTP
# ============================================================

_wifi_ok = wifi.connect(timeout_ms=20000)
_feed()

if _wifi_ok:
    wifi.sync_time()
    slots.write_heartbeat(_slot,
                          version=getattr(_ext, "EXT_VERSION", None),
                          booted=True)
else:
    logger.warn("Starting without WiFi")

# ============================================================
# SETUP EXTENSIONS
# ============================================================

if _ext is not None:
    try:
        _feed()
        _ext.setup(env._env)
        _feed()
        logger.info("Extensions setup complete")
    except Exception as e:
        logger.error("Extensions setup failed",
                     data={"error": str(e)})
        _ext = None

_feed()

# ============================================================
# BUILT-IN HTTP HANDLERS
# ============================================================

_reboot_pending    = False
_reboot_pending_at = 0

def _handle_ping(parts, method, body, query):
    """GET /ping — liveness check."""
    return 200, {
        "status":        "ok",
        "main_version":  MAIN_VERSION,
        "ext_version":   getattr(_ext, "EXT_VERSION", None),
        "slot":          _slot,
        "wifi":          wifi.is_connected(),
        "ip":            wifi.ip(),
        "ts":            time.time(),
    }

def _handle_log(parts, method, body, query):
    """GET /log?format=json|csv|text&limit=N"""
    fmt   = query.get("format", "json").lower()
    limit = None
    if "limit" in query:
        try:
            limit = int(query["limit"])
        except:
            pass
    if fmt not in ("json", "csv", "text"):
        return 400, {"error": f"Unknown format: {fmt} — options: json, csv, text"}
    raw = logger.read_formatted(fmt=fmt, limit=limit)
    if fmt == "json":
        try:
            return 200, json.loads(raw)
        except:
            return 200, {"log": [], "error": "parse error"}
    return 200, {"log": raw, "format": fmt}

def _handle_update(parts, method, body, query):
    """
    GET /update/check   — check GitHub and apply if newer
    GET /update/status  — show OTA metadata
    GET /update/rollback — force switch to other slot
    """
    global _reboot_pending, _reboot_pending_at

    if len(parts) < 2:
        return 400, {"error": "Try: /update/check, /update/status, /update/rollback"}

    sub = parts[1].lower()

    if sub == "check":
        if not wifi.is_connected():
            return 503, {"error": "WiFi not connected"}
        logger.info("OTA check triggered via HTTP")
        result  = ota.check(_slot)
        updated = result.get("updated", False)
        if updated:
            logger.info("Update applied — scheduling reboot")
            _reboot_pending    = True
            _reboot_pending_at = time.time() + 2
        return 200, {
            "status":  "updated" if updated else "checked",
            "result":  result,
            "message": "Rebooting in 2s" if updated else "No update available",
            "reboot":  updated,
        }

    elif sub == "status":
        meta = ota.load_meta()
        return 200, {
            "main_version":      MAIN_VERSION,
            "ext_slot":          _slot,
            "ext_version":       getattr(_ext, "EXT_VERSION", None),
            "ota_ext_version":   meta.get("ext_version", 0),
            "fail_count":        meta.get("fail_count", 0),
            "backoff_until":     meta.get("backoff_until", 0),
            "backoff_remaining": ota.remaining_backoff(meta),
            "github_configured": bool(env.get("GITHUB_USER") and
                                      env.get("GITHUB_REPO")),
        }

    elif sub == "rollback":
        other = slots.other_slot(_slot)
        if slots.write_slot(other):
            logger.info("Rollback triggered",
                        data={"from": _slot, "to": other})
            _reboot_pending    = True
            _reboot_pending_at = time.time() + 2
            return 200, {
                "status":  "rollback",
                "from":    _slot,
                "to":      other,
                "message": "Rebooting in 2s",
                "reboot":  True,
            }
        return 500, {"error": "Could not write slot file"}

    return 400, {"error": f"Unknown sub-command: {sub}"}

def _handle_wifi(parts, method, body, query):
    """GET /wifi — WiFi connection stats."""
    return 200, wifi.stats()

# Register built-in handlers
http_server.register("ping",   _handle_ping)
http_server.register("log",    _handle_log)
http_server.register("update", _handle_update)
http_server.register("wifi",   _handle_wifi)

# ============================================================
# START HTTP SERVER
# ============================================================

_server_ok = False
if _wifi_ok:
    _server_ok = http_server.start()
    if _server_ok:
        logger.info("HTTP server ready",
                    data={"ip": wifi.ip(),
                          "port": env.get_int("HTTP_PORT", 80)})
    else:
        logger.warn("HTTP server failed to start")
else:
    logger.warn("HTTP server not started — no WiFi")

_feed()

# ============================================================
# PRINT STARTUP SUMMARY
# ============================================================

print("=" * 40)
print(f"Shelf Lights — main.py {MAIN_VERSION}")
print(f"Slot     : {_slot}")
print(f"Ext ver  : {getattr(_ext, 'EXT_VERSION', 'none')}")
print(f"WiFi     : {'connected' if _wifi_ok else 'offline'}")
print(f"IP       : {wifi.ip() or 'n/a'}")
print(f"Server   : {'running' if _server_ok else 'stopped'}")
print("=" * 40)
print("Built-in endpoints:")
print(f"  GET /ping")
print(f"  GET /log?format=json|csv|text&limit=N")
print(f"  GET /update/check")
print(f"  GET /update/status")
print(f"  GET /update/rollback")
print(f"  GET /wifi")
if _ext is not None:
    effects = getattr(_ext, "EFFECTS", {})
    print("Extension endpoints:")
    print(f"  GET /on, /on/<target>")
    print(f"  GET /off, /off/<target>")
    print(f"  GET /stop")
    print(f"  GET /effect/<name>/<target>")
    print(f"  GET /brightness/<0-100>/<target>")
    print(f"  GET /colour/<r>/<g>/<b>/<w>/<target>")
    print(f"  GET /status")
    print(f"  POST /set")
    print(f"  Effects: {', '.join(effects.keys())}")
print(f"Targets: l1 l2 r1 r2 left right all")
print("=" * 40)

# ============================================================
# MAIN LOOP
# ============================================================

logger.info("Main loop running")

while True:
    watchdog.feed()

    # --- Pending reboot ---
    if _reboot_pending and time.time() >= _reboot_pending_at:
        logger.info("Rebooting now")
        if _ext is not None:
            try:
                _ext.teardown()
            except:
                pass
        machine.reset()

    # --- Tick extensions ---
    if _ext is not None:
        try:
            _ext.tick()
        except Exception as e:
            logger.error("Extensions tick error",
                         data={"error": str(e)})

    # --- WiFi health check ---
    if not wifi.is_connected():
        if wifi.check_and_reconnect():
            if not _server_ok:
                _server_ok = http_server.start()
                if _server_ok:
                    logger.info("HTTP server restarted after WiFi recovery")

    # --- Handle HTTP requests ---
    http_server.tick()

    time.sleep_ms(5)