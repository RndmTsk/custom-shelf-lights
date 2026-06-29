# slots_test.py
# Tests for slots.py

import os
import json
import time
import test_runner as t
import logger
import slots

# ============================================================
# HELPERS
# ============================================================

def setup():
    """Suppress logger output and clean up any leftover files."""
    logger.configure(
        log_file="test_slots_log.txt",
        max_lines=50,
        min_level=logger.DEBUG,
        echo_console=False,
    )
    cleanup_files()

def cleanup_files():
    for f in (slots.SLOT_FILE, slots.HEARTBEAT_FILE,
              "test_slots_log.txt"):
        try:
            os.remove(f)
        except:
            pass

def write_raw_slot(content):
    """Write raw content to slot file for edge case testing."""
    with open(slots.SLOT_FILE, "w") as f:
        f.write(content)

def write_raw_heartbeat(data):
    """Write a heartbeat dict directly for test setup."""
    with open(slots.HEARTBEAT_FILE, "w") as f:
        json.dump(data, f)

# ============================================================
# SLOT TESTS
# ============================================================

def test_read_slot_missing_file():
    t.suite("slots / read_slot missing file")
    setup()
    t.expect_eq("defaults to a when no file", slots.read_slot(), "a")

def test_read_slot_valid():
    t.suite("slots / read_slot valid values")
    setup()
    write_raw_slot("a")
    t.expect_eq("reads slot a", slots.read_slot(), "a")

    write_raw_slot("b")
    t.expect_eq("reads slot b", slots.read_slot(), "b")

def test_read_slot_invalid():
    t.suite("slots / read_slot invalid value")
    setup()
    write_raw_slot("c")
    t.expect_eq("invalid slot defaults to a", slots.read_slot(), "a")

def test_read_slot_whitespace():
    t.suite("slots / read_slot with whitespace")
    setup()
    write_raw_slot("  b  \n")
    t.expect_eq("strips whitespace", slots.read_slot(), "b")

def test_write_slot_valid():
    t.suite("slots / write_slot valid")
    setup()
    result = slots.write_slot("a")
    t.expect_true("returns True for slot a", result)
    t.expect_eq("slot a persists", slots.read_slot(), "a")

    result = slots.write_slot("b")
    t.expect_true("returns True for slot b", result)
    t.expect_eq("slot b persists", slots.read_slot(), "b")

def test_write_slot_invalid():
    t.suite("slots / write_slot invalid")
    setup()
    result = slots.write_slot("c")
    t.expect_false("returns False for invalid slot", result)

    result = slots.write_slot("")
    t.expect_false("returns False for empty string", result)

def test_other_slot():
    t.suite("slots / other_slot")
    setup()
    t.expect_eq("other of a is b", slots.other_slot("a"), "b")
    t.expect_eq("other of b is a", slots.other_slot("b"), "a")
    t.expect_eq("other of invalid defaults to a",
                slots.other_slot("x"), "a")

def test_extension_filename():
    t.suite("slots / extension_filename")
    setup()
    t.expect_eq("slot a filename",
                slots.extension_filename("a"), "extensions_a.py")
    t.expect_eq("slot b filename",
                slots.extension_filename("b"), "extensions_b.py")

def test_switch_to_other():
    t.suite("slots / switch_to_other")
    setup()
    slots.write_slot("a")
    new_slot = slots.switch_to_other("a")
    t.expect_eq("switches from a to b",    new_slot,          "b")
    t.expect_eq("slot file updated to b",  slots.read_slot(), "b")

    new_slot = slots.switch_to_other("b")
    t.expect_eq("switches from b to a",    new_slot,          "a")
    t.expect_eq("slot file updated to a",  slots.read_slot(), "a")

# ============================================================
# HEARTBEAT TESTS
# ============================================================

def test_write_heartbeat():
    t.suite("slots / write_heartbeat")
    setup()
    result = slots.write_heartbeat("a", version="1.0", booted=True)
    t.expect_true("returns True on success", result)

    hb = slots.read_heartbeat()
    t.expect_not_none("heartbeat is readable",        hb)
    t.expect_eq("slot matches",     hb["slot"],    "a")
    t.expect_eq("version matches",  hb["version"], "1.0")
    t.expect_true("booted is True",  hb["booted"])
    t.expect_false("crashed is False", hb["crashed"])
    t.expect_gt("ts is set",         hb["ts"], 0)

def test_write_heartbeat_no_version():
    t.suite("slots / write_heartbeat without version")
    setup()
    slots.write_heartbeat("b", booted=True)
    hb = slots.read_heartbeat()
    t.expect_not_none("heartbeat written",    hb)
    t.expect_eq("slot is b",  hb["slot"],   "b")
    t.expect_false("version key absent",
                   "version" in hb)

def test_read_heartbeat_missing():
    t.suite("slots / read_heartbeat missing file")
    setup()
    t.expect_none("returns None when missing", slots.read_heartbeat())

def test_read_heartbeat_corrupt():
    t.suite("slots / read_heartbeat corrupt file")
    setup()
    with open(slots.HEARTBEAT_FILE, "w") as f:
        f.write("not valid json {{{{")
    t.expect_none("returns None for corrupt file",
                  slots.read_heartbeat())

def test_is_slot_healthy_no_heartbeat():
    t.suite("slots / is_slot_healthy — no heartbeat")
    setup()
    t.expect_true("healthy when no heartbeat exists",
                  slots.is_slot_healthy("a"))

def test_is_slot_healthy_different_slot():
    t.suite("slots / is_slot_healthy — different slot")
    setup()
    write_raw_heartbeat({"slot": "b", "booted": False, "crashed": True})
    t.expect_true("healthy when heartbeat is for other slot",
                  slots.is_slot_healthy("a"))

def test_is_slot_healthy_good_heartbeat():
    t.suite("slots / is_slot_healthy — good heartbeat")
    setup()
    slots.write_heartbeat("a", booted=True, crashed=False)
    t.expect_true("healthy with good heartbeat",
                  slots.is_slot_healthy("a"))

def test_is_slot_healthy_crashed():
    t.suite("slots / is_slot_healthy — crashed")
    setup()
    write_raw_heartbeat({"slot": "a", "booted": False, "crashed": True})
    t.expect_false("unhealthy when crashed=True",
                   slots.is_slot_healthy("a"))

def test_is_slot_healthy_not_booted():
    t.suite("slots / is_slot_healthy — not booted")
    setup()
    write_raw_heartbeat({"slot": "a", "booted": False, "crashed": False})
    t.expect_false("unhealthy when booted=False",
                   slots.is_slot_healthy("a"))

def test_mark_slot_crashed():
    t.suite("slots / mark_slot_crashed")
    setup()
    result = slots.mark_slot_crashed("a")
    t.expect_true("returns True", result)

    hb = slots.read_heartbeat()
    t.expect_not_none("heartbeat written",       hb)
    t.expect_false("booted is False",  hb["booted"])
    t.expect_true("crashed is True",   hb["crashed"])
    t.expect_eq("slot matches",        hb["slot"], "a")
    t.expect_false("is_slot_healthy returns False",
                   slots.is_slot_healthy("a"))

def test_clear_heartbeat():
    t.suite("slots / clear_heartbeat")
    setup()
    slots.write_heartbeat("a")
    t.expect_not_none("heartbeat exists before clear",
                      slots.read_heartbeat())
    slots.clear_heartbeat()
    t.expect_none("heartbeat gone after clear",
                  slots.read_heartbeat())

def test_roundtrip_slot_switch():
    t.suite("slots / roundtrip slot switch")
    setup()
    slots.write_slot("a")
    slots.write_heartbeat("a", booted=True)
    t.expect_true("slot a healthy", slots.is_slot_healthy("a"))

    slots.mark_slot_crashed("a")
    t.expect_false("slot a now unhealthy", slots.is_slot_healthy("a"))

    new_slot = slots.switch_to_other("a")
    t.expect_eq("switched to b",     new_slot,          "b")
    t.expect_eq("slot file is b",    slots.read_slot(), "b")
    t.expect_true("slot b healthy",  slots.is_slot_healthy("b"))

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_read_slot_missing_file()
    test_read_slot_valid()
    test_read_slot_invalid()
    test_read_slot_whitespace()
    test_write_slot_valid()
    test_write_slot_invalid()
    test_other_slot()
    test_extension_filename()
    test_switch_to_other()
    test_write_heartbeat()
    test_write_heartbeat_no_version()
    test_read_heartbeat_missing()
    test_read_heartbeat_corrupt()
    test_is_slot_healthy_no_heartbeat()
    test_is_slot_healthy_different_slot()
    test_is_slot_healthy_good_heartbeat()
    test_is_slot_healthy_crashed()
    test_is_slot_healthy_not_booted()
    test_mark_slot_crashed()
    test_clear_heartbeat()
    test_roundtrip_slot_switch()
    cleanup_files()
    return t.summary()

run()