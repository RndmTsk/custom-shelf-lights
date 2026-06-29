# ota_test.py
# Tests for ota.py

import os
import json
import time
import test_runner as t
import logger
import slots
import ota

# ============================================================
# HELPERS
# ============================================================

# Minimal valid extension code — used as base for tests
# EXT_SLOT is always "a" as it would be on GitHub
_VALID_EXT_A = """\
EXT_SLOT = "a"
EXT_VERSION = 1
NUM_LEDS = 22
MAX_BRIGHTNESS = 0.3
PIN_L1 = 0
PIN_L2 = 1
PIN_R1 = 2
PIN_R2 = 3

def setup(env): pass
def tick(): pass
def handle_request(parts, method, body, query): return 200, {}
def teardown(): pass
"""

def _make_ext(slot="a", version=1, num_leds=22,
              brightness=0.3, missing=None, bad_type=None,
              extra=""):
    lines = [
        f'EXT_SLOT = "{slot}"',
        f'EXT_VERSION = {version}',
        f'NUM_LEDS = {num_leds}',
        f'MAX_BRIGHTNESS = {brightness}',
        f'PIN_L1 = 0',
        f'PIN_L2 = 1',
        f'PIN_R1 = 2',
        f'PIN_R2 = 3',
        '',
        'def setup(env): pass',
        'def tick(): pass',
        'def handle_request(parts, method, body, query): return 200, {}',
        'def teardown(): pass',
    ]
    if missing:
        lines = [l for l in lines if not l.startswith(missing)]
    if bad_type:
        field, val = bad_type
        lines = [f'{field} = {val}' if l.startswith(field) else l
                 for l in lines]
    if extra:
        lines.append(extra)
    return "\n".join(lines)

def setup():
    logger.configure(
        log_file="test_ota_log.txt",
        max_lines=100,
        min_level=logger.DEBUG,
        echo_console=False,
    )
    ota.configure(
        github_user="testuser",
        github_repo="testrepo",
        github_branch="main",
        max_fails=3,
        backoff_secs=3600,
    )
    ota.set_fetch_fn(None)
    cleanup_files()

def cleanup_files():
    for f in (ota.META_FILE, slots.SLOT_FILE, slots.HEARTBEAT_FILE,
              "extensions_a.py", "extensions_b.py",
              "test_ota_log.txt"):
        try:
            os.remove(f)
        except:
            pass

def make_fetch_fn(responses):
    """
    Build a mock fetch function.
    responses — dict mapping URL suffix to response text or None.
    e.g. {"version_ext.txt": "2", "extensions.py": code}
    """
    def fetch(url):
        for suffix, response in responses.items():
            if url.endswith(suffix):
                return response
        return None
    return fetch

# ============================================================
# META TESTS
# ============================================================

def test_meta_defaults():
    t.suite("ota / meta defaults")
    setup()
    meta = ota.load_meta()
    t.expect_eq("ext_version default",   meta["ext_version"],   0)
    t.expect_eq("fail_count default",    meta["fail_count"],    0)
    t.expect_eq("backoff_until default", meta["backoff_until"], 0)

def test_meta_roundtrip():
    t.suite("ota / meta roundtrip")
    setup()
    meta = {"ext_version": 5, "fail_count": 2, "backoff_until": 9999}
    ota.save_meta(meta)
    loaded = ota.load_meta()
    t.expect_eq("ext_version",   loaded["ext_version"],   5)
    t.expect_eq("fail_count",    loaded["fail_count"],    2)
    t.expect_eq("backoff_until", loaded["backoff_until"], 9999)

def test_meta_missing_file():
    t.suite("ota / meta missing file")
    setup()
    meta = ota.load_meta()
    t.expect_eq("returns defaults", meta, ota._default_meta())

def test_clear_meta():
    t.suite("ota / clear_meta")
    setup()
    ota.save_meta({"ext_version": 99, "fail_count": 5,
                   "backoff_until": 9999})
    ota.clear_meta()
    meta = ota.load_meta()
    t.expect_eq("ext_version reset",   meta["ext_version"],   0)
    t.expect_eq("fail_count reset",    meta["fail_count"],    0)
    t.expect_eq("backoff_until reset", meta["backoff_until"], 0)

# ============================================================
# VALIDATE_EXT TESTS
# ============================================================

def test_validate_valid():
    t.suite("ota / validate_ext valid code")
    setup()
    ok, reason = ota.validate_ext(_make_ext(slot="b"), "b")
    t.expect_true("valid code passes",   ok)
    t.expect_none("no reason on pass",   reason)

def test_validate_syntax_error():
    t.suite("ota / validate_ext syntax error")
    setup()
    ok, reason = ota.validate_ext("def (((broken:", "a")
    t.expect_false("syntax error fails", ok)
    t.expect_true("reason mentions syntax",
                  "syntax" in reason)

def test_validate_missing_function():
    t.suite("ota / validate_ext missing function")
    setup()
    code = _make_ext(slot="a").replace("def setup(env): pass", "")
    ok, reason = ota.validate_ext(code, "a")
    t.expect_false("missing function fails", ok)
    t.expect_true("reason mentions interface",
                  "interface" in reason)

def test_validate_wrong_slot():
    t.suite("ota / validate_ext wrong slot")
    setup()
    code = _make_ext(slot="a")
    ok, reason = ota.validate_ext(code, "b")
    t.expect_false("wrong slot fails",        ok)
    t.expect_true("reason mentions identity",
                  "identity" in reason)

def test_validate_missing_field():
    t.suite("ota / validate_ext missing field")
    setup()
    code = _make_ext(slot="a", missing="NUM_LEDS")
    ok, reason = ota.validate_ext(code, "a")
    t.expect_false("missing field fails",   ok)
    t.expect_true("reason mentions schema",
                  "schema" in reason)

def test_validate_wrong_type():
    t.suite("ota / validate_ext wrong type")
    setup()
    code = _make_ext(slot="a", bad_type=("NUM_LEDS", '"notanint"'))
    ok, reason = ota.validate_ext(code, "a")
    t.expect_false("wrong type fails",      ok)
    t.expect_true("reason mentions schema",
                  "schema" in reason)

def test_validate_out_of_range():
    t.suite("ota / validate_ext out of range values")
    setup()
    code = _make_ext(slot="a", num_leds=9999)
    ok, reason = ota.validate_ext(code, "a")
    t.expect_false("out of range NUM_LEDS fails", ok)
    t.expect_true("reason mentions values",
                  "values" in reason)

    code = _make_ext(slot="a", brightness=2.0)
    ok, reason = ota.validate_ext(code, "a")
    t.expect_false("out of range brightness fails", ok)
    t.expect_true("reason mentions values",
                  "values" in reason)

# ============================================================
# PATCH SLOT TESTS
# ============================================================

def test_patch_slot():
    t.suite("ota / _patch_slot")
    setup()
    code    = 'EXT_SLOT = "a"\nEXT_VERSION = 1\n'
    patched = ota._patch_slot(code, "b")
    t.expect_true("patches slot a to b",
                  'EXT_SLOT = "b"' in patched)
    t.expect_false("removes slot a",
                   'EXT_SLOT = "a"' in patched)

def test_patch_slot_already_correct():
    t.suite("ota / _patch_slot already target slot")
    setup()
    code    = 'EXT_SLOT = "a"\n'
    patched = ota._patch_slot(code, "a")
    t.expect_true("slot a unchanged",
                  'EXT_SLOT = "a"' in patched)

def test_patch_slot_regex():
    t.suite("ota / _patch_slot handles spacing variants")
    setup()
    variants = [
        'EXT_SLOT = "a"',
        'EXT_SLOT  =  "a"',
        'EXT_SLOT="a"',
        'EXT_SLOT =  "a"',
    ]
    for variant in variants:
        code    = f'{variant}\nEXT_VERSION = 1\n'
        patched = ota._patch_slot(code, "b")
        t.expect_true(f'patches variant: {variant!r}',
                      'EXT_SLOT = "b"' in patched)
        t.expect_false(f'removes a variant: {variant!r}',
                       '"a"' in patched.split("\n")[0])

# ============================================================
# BACKOFF TESTS
# ============================================================

def test_backoff_not_active():
    t.suite("ota / backoff not active")
    setup()
    meta = ota._default_meta()
    t.expect_false("not in backoff initially",
                   ota._in_backoff(meta))
    t.expect_eq("remaining is 0",
                ota.remaining_backoff(meta), 0)

def test_backoff_active():
    t.suite("ota / backoff active")
    setup()
    meta = {"ext_version": 0, "fail_count": 3,
            "backoff_until": time.time() + 3600}
    t.expect_true("in backoff when backoff_until in future",
                  ota._in_backoff(meta))
    t.expect_gt("remaining > 0",
                ota.remaining_backoff(meta), 0)

def test_handle_fail_increments():
    t.suite("ota / _handle_fail increments count")
    setup()
    meta = ota._default_meta()
    ota._handle_fail(meta, "test reason")
    t.expect_eq("fail_count incremented", meta["fail_count"], 1)
    t.expect_eq("no backoff yet",         meta["backoff_until"], 0)

def test_handle_fail_triggers_backoff():
    t.suite("ota / _handle_fail triggers backoff at threshold")
    setup()
    meta = ota._default_meta()
    for _ in range(ota._max_fails):
        ota._handle_fail(meta, "repeated fail")
    t.expect_eq("fail_count at threshold",
                meta["fail_count"], ota._max_fails)
    t.expect_gt("backoff_until set",
                meta["backoff_until"], time.time())

# ============================================================
# CHECK TESTS
# ============================================================

def test_check_not_configured():
    t.suite("ota / check — not configured")
    setup()
    ota._github_raw = ""   # clear configuration
    slots.write_slot("a")
    result = ota.check("a")
    t.expect_false("not checked",          result["checked"])
    t.expect_not_none("error set",         result["error"])
    t.expect_false("not updated",          result["updated"])

def test_check_up_to_date():
    t.suite("ota / check — already up to date")
    setup()
    ota.save_meta({"ext_version": 5, "fail_count": 0,
                   "backoff_until": 0})
    ota.set_fetch_fn(make_fetch_fn({"version_ext.txt": "5"}))

    result = ota.check("a")
    t.expect_true("checked",              result["checked"])
    t.expect_false("not updated",         result["updated"])
    t.expect_eq("remote version correct", result["remote_version"], 5)
    t.expect_none("no error",             result["error"])

def test_check_version_fetch_fails():
    t.suite("ota / check — version fetch fails")
    setup()
    ota.set_fetch_fn(make_fetch_fn({}))  # returns None for everything

    result = ota.check("a")
    t.expect_true("checked",      result["checked"])
    t.expect_false("not updated", result["updated"])
    t.expect_not_none("error",    result["error"])

    meta = ota.load_meta()
    t.expect_eq("fail_count incremented", meta["fail_count"], 1)

def test_check_invalid_version():
    t.suite("ota / check — invalid version number")
    setup()
    ota.set_fetch_fn(make_fetch_fn({"version_ext.txt": "notanumber"}))

    result = ota.check("a")
    t.expect_false("not updated",  result["updated"])
    t.expect_not_none("error set", result["error"])

def test_check_ext_fetch_fails():
    t.suite("ota / check — extension fetch fails")
    setup()
    ota.set_fetch_fn(make_fetch_fn({
        "version_ext.txt": "2",
        # extensions.py intentionally missing
    }))

    result = ota.check("a")
    t.expect_true("checked",              result["checked"])
    t.expect_false("not updated",         result["updated"])
    t.expect_not_none("error set",        result["error"])

    meta = ota.load_meta()
    t.expect_eq("fail_count incremented", meta["fail_count"], 1)

def test_check_canary_fails():
    t.suite("ota / check — canary validation fails")
    setup()
    bad_code = "this is not valid python ((("
    ota.set_fetch_fn(make_fetch_fn({
        "version_ext.txt": "2",
        "extensions.py":   bad_code,
    }))

    result = ota.check("a")
    t.expect_true("checked",              result["checked"])
    t.expect_false("not updated",         result["updated"])
    t.expect_true("rollback flagged",     result["rollback"])
    t.expect_not_none("rollback reason",  result["rollback_reason"])

    meta = ota.load_meta()
    t.expect_eq("fail_count incremented", meta["fail_count"], 1)

def test_check_successful_update():
    t.suite("ota / check — successful update")
    setup()
    slots.write_slot("a")

    # GitHub has version 2, valid code for slot a
    # OTA will patch it to slot b (the inactive slot)
    ota.set_fetch_fn(make_fetch_fn({
        "version_ext.txt": "2",
        "extensions.py":   _VALID_EXT_A,
    }))

    result = ota.check("a")
    t.expect_true("checked",              result["checked"])
    t.expect_true("updated",              result["updated"])
    t.expect_eq("new slot is b",          result["new_slot"], "b")
    t.expect_eq("remote version",         result["remote_version"], 2)
    t.expect_none("no error",             result["error"])
    t.expect_false("no rollback",         result["rollback"])

    # Verify file was written
    try:
        with open("extensions_b.py", "r") as f:
            content = f.read()
        t.expect_true("extensions_b.py written",
                      len(content) > 0)
        t.expect_true("slot patched to b",
                      'EXT_SLOT = "b"' in content)
    except OSError:
        t.expect_true("extensions_b.py should exist", False)

    # Verify boot slot switched
    t.expect_eq("boot slot switched to b",
                slots.read_slot(), "b")

    # Verify meta updated
    meta = ota.load_meta()
    t.expect_eq("ext_version updated",  meta["ext_version"],  2)
    t.expect_eq("fail_count reset",     meta["fail_count"],   0)

def test_check_in_backoff():
    t.suite("ota / check — in backoff")
    setup()
    ota.save_meta({
        "ext_version":   1,
        "fail_count":    3,
        "backoff_until": time.time() + 3600,
    })

    result = ota.check("a")
    t.expect_false("not checked during backoff",  result["checked"])
    t.expect_true("in_backoff flagged",           result["in_backoff"])
    t.expect_gt("backoff_remaining > 0",
                result["backoff_remaining"], 0)

def test_check_fail_then_recover():
    t.suite("ota / check — fail then recover")
    setup()

    # First attempt fails
    ota.set_fetch_fn(make_fetch_fn({}))
    ota.check("a")
    meta = ota.load_meta()
    t.expect_eq("one fail recorded", meta["fail_count"], 1)

    # Second attempt succeeds
    ota.set_fetch_fn(make_fetch_fn({
        "version_ext.txt": "2",
        "extensions.py":   _VALID_EXT_A,
    }))
    result = ota.check("a")
    t.expect_true("updated on second attempt", result["updated"])

    meta = ota.load_meta()
    t.expect_eq("fail_count reset after success",
                meta["fail_count"], 0)

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_meta_defaults()
    test_meta_roundtrip()
    test_meta_missing_file()
    test_clear_meta()
    test_validate_valid()
    test_validate_syntax_error()
    test_validate_missing_function()
    test_validate_wrong_slot()
    test_validate_missing_field()
    test_validate_wrong_type()
    test_validate_out_of_range()
    test_patch_slot()
    test_patch_slot_already_correct()
    test_patch_slot_regex()
    test_backoff_not_active()
    test_backoff_active()
    test_handle_fail_increments()
    test_handle_fail_triggers_backoff()
    test_check_not_configured()
    test_check_up_to_date()
    test_check_version_fetch_fails()
    test_check_invalid_version()
    test_check_ext_fetch_fails()
    test_check_canary_fails()
    test_check_successful_update()
    test_check_in_backoff()
    test_check_fail_then_recover()
    cleanup_files()
    return t.summary()

run()