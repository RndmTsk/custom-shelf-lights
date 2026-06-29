# ota.py
# Over-the-air update management.
# Fetches extensions and config updates from GitHub.
# Depends on: logger, slots
#
# Files on GitHub:
#   version_ext.txt    — integer version of extensions.py
#   extensions.py      — always has EXT_SLOT = "a"
#                        OTA patches it for the inactive slot
#
# Files on Pico:
#   extensions_a.py    — slot a
#   extensions_b.py    — slot b
#   ota_meta.json      — tracks versions and fail state

# ============================================================
# IMPORTS
# ============================================================

import json
import time
import logger
import slots

# ============================================================
# GLOBALS
# ============================================================

_github_raw    = ""
_max_fails     = 3
_backoff_secs  = 86400   # 24 hours

# --- State ---
_fetch_fn      = None    # injectable for testing

META_FILE      = "ota_meta.json"

# ============================================================
# CONFIGURE
# ============================================================

def configure(github_user, github_repo, github_branch="main",
              max_fails=3, backoff_secs=86400):
    """
    Set GitHub source and fail policy.
    Call once at startup before any update checks.
    """
    global _github_raw, _max_fails, _backoff_secs
    _github_raw   = (f"https://raw.githubusercontent.com/"
                     f"{github_user}/{github_repo}/{github_branch}")
    _max_fails    = max_fails
    _backoff_secs = backoff_secs
    logger.info("OTA configured",
                data={"raw": _github_raw, "max_fails": max_fails})

def set_fetch_fn(fn):
    """
    Override the HTTP fetch function. Used in tests.
    fn(url) should return response text or None on failure.
    Pass None to restore default (urequests).
    """
    global _fetch_fn
    _fetch_fn = fn

# ============================================================
# META
# ============================================================

def _default_meta():
    return {
        "ext_version":   0,
        "fail_count":    0,
        "backoff_until": 0,
    }

def load_meta():
    """Load OTA metadata from disk. Returns defaults if missing."""
    try:
        with open(META_FILE, "r") as f:
            saved = json.load(f)
        meta = _default_meta()
        if isinstance(saved.get("ext_version"), int):
            meta["ext_version"] = saved["ext_version"]
        if isinstance(saved.get("fail_count"), int):
            meta["fail_count"] = saved["fail_count"]
        if isinstance(saved.get("backoff_until"), (int, float)):
            meta["backoff_until"] = saved["backoff_until"]
        return meta
    except:
        return _default_meta()

def save_meta(meta):
    """Persist OTA metadata to disk."""
    try:
        with open(META_FILE, "w") as f:
            json.dump(meta, f)
        return True
    except Exception as e:
        logger.error("OTA meta save failed", data={"error": str(e)})
        return False

def clear_meta():
    """Reset OTA metadata to defaults."""
    return save_meta(_default_meta())

# ============================================================
# FETCH
# ============================================================

def _fetch(path):
    """
    Fetch a file from GitHub raw.
    Returns text content or None on failure.
    Uses injected _fetch_fn if set, otherwise urequests.
    """
    url = f"{_github_raw}/{path}"
    if _fetch_fn is not None:
        return _fetch_fn(url)
    try:
        import urequests
        logger.info("Fetching", data={"url": url})
        r = urequests.get(url, headers={"User-Agent": "Pico"})
        if r.status_code == 200:
            text = r.text
            r.close()
            return text
        else:
            logger.warn("Fetch failed",
                        data={"url": url, "status": r.status_code})
            r.close()
            return None
    except Exception as e:
        logger.error("Fetch error",
                     data={"url": url, "error": str(e)})
        return None

# ============================================================
# FAIL HANDLING
# ============================================================

def _handle_fail(meta, reason):
    """
    Increment fail count.
    Apply backoff if max_fails threshold reached.
    """
    meta["fail_count"] += 1
    if meta["fail_count"] >= _max_fails:
        meta["backoff_until"] = time.time() + _backoff_secs
        logger.warn("OTA fail threshold reached — backing off",
                    data={
                        "fails":        meta["fail_count"],
                        "backoff_secs": _backoff_secs,
                    })
    else:
        logger.warn("OTA fail recorded",
                    data={
                        "fails":     meta["fail_count"],
                        "max_fails": _max_fails,
                        "reason":    reason,
                    })
    save_meta(meta)

def _in_backoff(meta):
    """Return True if currently in backoff period."""
    return time.time() < meta.get("backoff_until", 0)

def remaining_backoff(meta=None):
    """Return seconds remaining in backoff, 0 if not in backoff."""
    if meta is None:
        meta = load_meta()
    remaining = meta.get("backoff_until", 0) - time.time()
    return max(0, remaining)

# ============================================================
# CANARY VALIDATION
# ============================================================

def _exec_module(code):
    """
    Execute Python code and return a namespace proxy object.
    Returns proxy on success, None on syntax/runtime error.
    """
    try:
        ns = {}
        exec(code, ns)

        class _Proxy:
            pass
        proxy = _Proxy()
        for k, v in ns.items():
            if not k.startswith("__"):
                setattr(proxy, k, v)
        return proxy
    except Exception as e:
        return None

def validate_ext(code, target_slot):
    """
    Validate extension code before promoting.
    Returns (True, None) on pass, (False, reason) on fail.

    Checks:
      Layer 0 — syntax: code executes without error
      Layer 1 — interface: required functions present
      Layer 2 — identity: EXT_SLOT matches target slot
      Layer 3 — schema: required fields present and typed correctly
    """
    # Layer 0 — syntax
    mod = _exec_module(code)
    if mod is None:
        return False, "syntax: failed to execute"

    # Layer 1 — interface
    for fn in ("setup", "tick", "handle_request", "teardown"):
        if not hasattr(mod, fn) or not callable(getattr(mod, fn)):
            return False, f"interface: missing callable '{fn}'"

    # Layer 2 — identity
    if not hasattr(mod, "EXT_SLOT"):
        return False, "identity: missing EXT_SLOT"
    if mod.EXT_SLOT != target_slot:
        return False, (f"identity: EXT_SLOT is '{mod.EXT_SLOT}' "
                       f"but expected '{target_slot}'")

    # Layer 3 — schema
    schema = {
        "EXT_VERSION":    int,
        "NUM_LEDS":       int,
        "MAX_BRIGHTNESS": float,
        "PIN_L1":         int,
        "PIN_L2":         int,
        "PIN_R1":         int,
        "PIN_R2":         int,
    }
    for field, expected_type in schema.items():
        if not hasattr(mod, field):
            return False, f"schema: missing field '{field}'"
        val = getattr(mod, field)
        if not isinstance(val, expected_type):
            return False, (f"schema: '{field}' expected "
                           f"{expected_type.__name__}, "
                           f"got {type(val).__name__}")

    # Value range checks
    if not (1 <= mod.NUM_LEDS <= 500):
        return False, f"values: NUM_LEDS {mod.NUM_LEDS} out of range 1-500"
    if not (0.0 <= mod.MAX_BRIGHTNESS <= 1.0):
        return False, (f"values: MAX_BRIGHTNESS {mod.MAX_BRIGHTNESS} "
                       f"out of range 0.0-1.0")
    for pin in ("PIN_L1", "PIN_L2", "PIN_R1", "PIN_R2"):
        val = getattr(mod, pin)
        if not (0 <= val <= 29):
            return False, f"values: {pin}={val} out of range 0-29"

    return True, None

# ============================================================
# UPDATE
# ============================================================

def _patch_slot(code, target_slot):
    """
    Patch EXT_SLOT in downloaded code for the target slot.
    GitHub always has EXT_SLOT = "a" as canonical.
    Handles any whitespace around the = sign.
    """
    import re
    patched = re.sub(
        r'EXT_SLOT\s*=\s*"a"',
        f'EXT_SLOT = "{target_slot}"',
        code
    )
    return patched

def _write_file(path, content):
    """Write content to a file. Returns True on success."""
    try:
        with open(path, "w") as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error("File write failed",
                     data={"path": path, "error": str(e)})
        return False

def _remove_file(path):
    """Remove a file, ignoring errors."""
    try:
        import os
        os.remove(path)
    except:
        pass

def check(current_slot):
    """
    Check GitHub for an extension update.
    Downloads, validates and promotes if newer version found.

    Returns result dict:
    {
        "checked":         bool,
        "updated":         bool,
        "current_version": int,
        "remote_version":  int or None,
        "new_slot":        str or None,
        "error":           str or None,
        "rollback":        bool,
        "rollback_reason": str or None,
        "in_backoff":      bool,
        "backoff_remaining": float,
    }
    """
    meta = load_meta()

    result = {
        "checked":           False,
        "updated":           False,
        "current_version":   meta["ext_version"],
        "remote_version":    None,
        "new_slot":          None,
        "error":             None,
        "rollback":          False,
        "rollback_reason":   None,
        "in_backoff":        False,
        "backoff_remaining": 0,
    }

    # --- Backoff check ---
    if _in_backoff(meta):
        remaining              = remaining_backoff(meta)
        result["in_backoff"]        = True
        result["backoff_remaining"] = remaining
        result["error"]             = f"In backoff for {remaining:.0f}s"
        logger.warn("OTA check skipped — in backoff",
                    data={"remaining_s": remaining})
        return result

    # --- GitHub not configured ---
    if not _github_raw:
        result["error"] = "OTA not configured — call configure() first"
        logger.warn("OTA check skipped — not configured")
        return result

    result["checked"] = True

    # --- Fetch remote version ---
    remote_ver_str = _fetch("version_ext.txt")
    if remote_ver_str is None:
        result["error"] = "Could not fetch version_ext.txt"
        _handle_fail(meta, result["error"])
        return result

    try:
        remote_ver = int(remote_ver_str.strip())
    except:
        result["error"] = f"Invalid version_ext.txt: {remote_ver_str!r}"
        _handle_fail(meta, result["error"])
        return result

    result["remote_version"] = remote_ver
    logger.info("Version check",
                data={"local": meta["ext_version"], "remote": remote_ver})

    if remote_ver <= meta["ext_version"]:
        logger.info("Extensions up to date",
                    data={"version": meta["ext_version"]})
        return result

    # --- Fetch extension code ---
    logger.info("New version available", data={"version": remote_ver})
    ext_code = _fetch("extensions.py")
    if ext_code is None:
        result["error"] = "Could not fetch extensions.py"
        _handle_fail(meta, result["error"])
        return result

    # --- Determine inactive slot and patch ---
    inactive = slots.other_slot(current_slot)
    patched  = _patch_slot(ext_code, inactive)

    # --- Validate (canary) ---
    ok, reason = validate_ext(patched, inactive)
    if not ok:
        result["rollback"]        = True
        result["rollback_reason"] = reason
        result["error"]           = f"Canary failed: {reason}"
        _handle_fail(meta, reason)
        logger.warn("Canary failed — not promoting",
                    data={"version": remote_ver, "reason": reason})
        return result

    # --- Write to inactive slot ---
    target_file = slots.extension_filename(inactive)
    if not _write_file(target_file, patched):
        result["error"] = f"Could not write {target_file}"
        _handle_fail(meta, result["error"])
        return result

    # --- Switch boot slot ---
    if not slots.write_slot(inactive):
        result["error"] = "Could not switch boot slot"
        _handle_fail(meta, result["error"])
        return result

    # --- Commit ---
    meta["ext_version"] = remote_ver
    meta["fail_count"]  = 0
    save_meta(meta)

    result["updated"]  = True
    result["new_slot"] = inactive
    logger.info("Extension update applied",
                data={"version": remote_ver, "slot": inactive})

    return result