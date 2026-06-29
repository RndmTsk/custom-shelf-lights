# logger.py
# Structured JSON logging with console output.
# Writes to a rotating log file on the Pico's flash.
# Depends on nothing — safe to import anywhere.

# ============================================================
# IMPORTS
# ============================================================

import time
import json

# ============================================================
# CONSTANTS
# ============================================================

DEBUG = "DEBUG"
INFO  = "INFO"
WARN  = "WARN"
ERROR = "ERROR"

# ============================================================
# GLOBALS
# ============================================================

_log_file     = "shelf_log.txt"
_max_lines    = 200
_min_level    = INFO
_echo_console = True

_LEVEL_ORDER = {DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3}

# ============================================================
# CAPABILITIES
# ============================================================

def configure(log_file="shelf_log.txt", max_lines=200,
              min_level=INFO, echo_console=True):
    """
    Configure logger before first use.
    Call this once at startup before importing other modules.

    log_file     — filename on Pico flash
    max_lines    — maximum log entries to keep (oldest are dropped)
    min_level    — minimum level to record: DEBUG, INFO, WARN, ERROR
    echo_console — also print to Thonny console
    """
    global _log_file, _max_lines, _min_level, _echo_console
    _log_file     = log_file
    _max_lines    = max_lines
    _min_level    = min_level
    _echo_console = echo_console

def _should_log(level):
    return _LEVEL_ORDER.get(level, 1) >= _LEVEL_ORDER.get(_min_level, 1)

def _write(entry):
    """Append a JSON entry to the log file, trimming if over max_lines."""
    try:
        try:
            with open(_log_file, "r") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        if len(lines) >= _max_lines:
            lines = lines[-(max(_max_lines - 1, 0)):]
        lines.append(json.dumps(entry) + "\n")
        with open(_log_file, "w") as f:
            f.write("".join(lines))
    except Exception as e:
        print(f"[logger] write failed: {e}")

def _log(level, message, data=None):
    if not _should_log(level):
        return
    entry = {"ts": time.time(), "level": level, "msg": message}
    if data is not None:
        entry["data"] = data
    if _echo_console:
        suffix = f" — {data}" if data is not None else ""
        print(f"[{entry['ts']}] [{level:5}] {message}{suffix}")
    _write(entry)

# --- Public logging functions ---

def debug(message, data=None):
    _log(DEBUG, message, data)

def info(message, data=None):
    _log(INFO, message, data)

def warn(message, data=None):
    _log(WARN, message, data)

def error(message, data=None):
    _log(ERROR, message, data)

# --- Log reading ---

def read(limit=None):
    """
    Read log entries as list of dicts, newest last.
    limit — max entries to return, None for all.
    """
    try:
        with open(_log_file, "r") as f:
            lines = f.readlines()
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except:
                entries.append({"ts": 0, "level": INFO,
                                "msg": line, "data": None})
        if limit is not None:
            entries = entries[-limit:]
        return entries
    except OSError:
        return []

def read_formatted(fmt="text", limit=None):
    """
    Read log as formatted string.
    fmt — "text", "csv", or "json"
    """
    entries = read(limit=limit)

    if fmt == "json":
        return json.dumps({"log": entries, "count": len(entries)})

    elif fmt == "csv":
        rows = ["ts,level,message,data"]
        for e in entries:
            data_str = json.dumps(e.get("data", "")).replace(",", ";")
            rows.append(
                f"{e.get('ts', 0)},"
                f"{e.get('level', INFO)},"
                f"{e.get('msg', '')},"
                f"{data_str}"
            )
        return "\n".join(rows)

    else:  # text
        lines = []
        for e in entries:
            ts    = e.get("ts", 0)
            level = e.get("level", INFO)
            msg   = e.get("msg", "")
            data  = e.get("data", None)
            line  = f"[{ts}] [{level:5}] {msg}"
            if data is not None:
                line += f" — {data}"
            lines.append(line)
        return "\n".join(lines)

def print_previous_session():
    """Print previous session log to console on startup."""
    print("=" * 40)
    print("PREVIOUS SESSION LOG:")
    print("=" * 40)
    entries = read()
    if entries:
        for e in entries:
            ts    = e.get("ts", 0)
            level = e.get("level", INFO)
            msg   = e.get("msg", "")
            data  = e.get("data", None)
            suffix = f" — {data}" if data is not None else ""
            print(f"[{ts}] [{level:5}] {msg}{suffix}")
    else:
        print("No previous log entries")
    print("=" * 40)

def clear():
    """Delete the log file."""
    try:
        import os
        os.remove(_log_file)
    except:
        pass