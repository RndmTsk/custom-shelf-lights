# slots.py
# Manages the active extension slot (a/b dual boot).
# Tracks heartbeats to detect crashed slots and fall back.
# Depends on: logger

# ============================================================
# IMPORTS
# ============================================================

import time
import json
import logger

# ============================================================
# CONSTANTS
# ============================================================

SLOT_FILE      = "slot.txt"
HEARTBEAT_FILE = "heartbeat.json"
SLOTS = ("a", "b")

# ============================================================
# SLOT MANAGEMENT
# ============================================================

def read_slot():
    """
    Read the active slot from disk.
    Returns "a" if file missing or invalid.
    """
    try:
        with open(SLOT_FILE, "r") as f:
            slot = f.read().strip().lower()
        if slot in SLOTS:
            return slot
        logger.warn("Invalid slot value — defaulting to a",
                    data={"value": slot})
        return "a"
    except OSError:
        logger.info("No slot file found — defaulting to a")
        return "a"

def write_slot(slot):
    """
    Write the active slot to disk.
    Returns True on success, False on failure.
    """
    if slot not in SLOTS:
        logger.error("Invalid slot — must be 'a' or 'b'",
                     data={"slot": slot})
        return False
    try:
        with open(SLOT_FILE, "w") as f:
            f.write(slot)
        logger.info("Slot written", data={"slot": slot})
        return True
    except OSError as e:
        logger.error("Failed to write slot file",
                     data={"slot": slot, "error": str(e)})
        return False

def other_slot(slot):
    """Return the other slot — 'a' → 'b', 'b' → 'a'."""
    if slot == "a":
        return "b"
    if slot == "b":
        return "a"
    return "a"

def extension_filename(slot):
    """Return the extensions filename for a given slot."""
    return f"extensions_{slot}.py"

def switch_to_other(current_slot):
    """
    Switch to the other slot.
    Returns the new slot on success, current slot on failure.
    """
    target = other_slot(current_slot)
    if write_slot(target):
        logger.info("Switched slot",
                    data={"from": current_slot, "to": target})
        return target
    logger.error("Slot switch failed — staying on current",
                 data={"current": current_slot})
    return current_slot

# ============================================================
# HEARTBEAT
# ============================================================

def write_heartbeat(slot, version=None, booted=True, crashed=False):
    """
    Write a heartbeat entry for the given slot.
    Call after successful boot and WiFi connect.

    slot    — active slot ("a" or "b")
    version — extension version string (optional)
    booted  — True if boot succeeded
    crashed — True if slot is known bad
    """
    entry = {
        "slot":    slot,
        "booted":  booted,
        "crashed": crashed,
        "ts":      time.time(),
    }
    if version is not None:
        entry["version"] = version
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump(entry, f)
        logger.info("Heartbeat written",
                    data={"slot": slot, "booted": booted})
        return True
    except OSError as e:
        logger.error("Heartbeat write failed",
                     data={"error": str(e)})
        return False

def read_heartbeat():
    """
    Read the last heartbeat entry.
    Returns dict or None if missing/invalid.
    """
    try:
        with open(HEARTBEAT_FILE, "r") as f:
            return json.load(f)
    except:
        return None

def is_slot_healthy(slot):
    """
    Check if the given slot has a healthy heartbeat.
    Returns True if:
    - No heartbeat exists yet (first boot — give it a chance)
    - Heartbeat is for a different slot (fresh start)
    - Heartbeat shows booted=True and crashed=False
    Returns False if heartbeat shows crashed=True or booted=False
    for this specific slot.
    """
    hb = read_heartbeat()
    if hb is None:
        logger.info("No heartbeat found — assuming healthy")
        return True
    if hb.get("slot") != slot:
        logger.info("Heartbeat is for different slot — assuming healthy",
                    data={"hb_slot": hb.get("slot"), "check_slot": slot})
        return True
    if hb.get("crashed", False):
        logger.warn("Slot marked as crashed",
                    data={"slot": slot})
        return False
    if not hb.get("booted", False):
        logger.warn("Slot did not complete boot",
                    data={"slot": slot})
        return False
    return True

def mark_slot_crashed(slot):
    """
    Mark the current slot as crashed.
    Called by bootloader when a slot fails to import.
    """
    logger.error("Marking slot as crashed", data={"slot": slot})
    return write_heartbeat(slot, booted=False, crashed=True)

def clear_heartbeat():
    """Remove the heartbeat file."""
    try:
        import os
        os.remove(HEARTBEAT_FILE)
        return True
    except:
        return False