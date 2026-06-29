# test_logger.py
# Tests for logger.py

import os
import json
import test_runner as t
import logger

# ============================================================
# HELPERS
# ============================================================

TEST_LOG_FILE = "test_logger.txt"

def setup():
    logger.configure(
        log_file=TEST_LOG_FILE,
        max_lines=20,
        min_level=logger.DEBUG,
        echo_console=False,   # suppress console during tests
    )

def cleanup():
    logger.clear()
    try:
        os.remove(TEST_LOG_FILE)
    except:
        pass

def entry_count():
    return len(logger.read())

def last_entry():
    entries = logger.read()
    return entries[-1] if entries else None

# ============================================================
# TESTS
# ============================================================

def test_basic_logging():
    t.suite("logger / basic logging")
    setup()
    logger.clear()

    logger.info("Test message")
    t.expect_eq("one entry after info",    entry_count(), 1)

    e = last_entry()
    t.expect_not_none("entry is not None",              e)
    t.expect_eq("level is INFO",           e["level"],  logger.INFO)
    t.expect_eq("message matches",         e["msg"],    "Test message")
    t.expect_none("no data when omitted",  e.get("data"))
    t.expect_gt("timestamp is set",        e["ts"],     0)

def test_all_levels():
    t.suite("logger / all levels")
    setup()
    logger.clear()

    logger.debug("debug msg")
    logger.info("info msg")
    logger.warn("warn msg")
    logger.error("error msg")

    entries = logger.read()
    t.expect_eq("four entries",             len(entries), 4)
    t.expect_eq("first is DEBUG",          entries[0]["level"], logger.DEBUG)
    t.expect_eq("second is INFO",          entries[1]["level"], logger.INFO)
    t.expect_eq("third is WARN",           entries[2]["level"], logger.WARN)
    t.expect_eq("fourth is ERROR",         entries[3]["level"], logger.ERROR)

def test_data_field():
    t.suite("logger / data field")
    setup()
    logger.clear()

    logger.info("With data", data={"key": "value", "num": 42})
    e = last_entry()
    t.expect_not_none("data is present",            e.get("data"))
    t.expect_eq("data key matches",  e["data"]["key"], "value")
    t.expect_eq("data num matches",  e["data"]["num"], 42)

    logger.info("No data")
    e = last_entry()
    t.expect_none("data absent when not passed", e.get("data"))

def test_min_level_filtering():
    t.suite("logger / min_level filtering")

    logger.configure(log_file=TEST_LOG_FILE, max_lines=20,
                     min_level=logger.WARN, echo_console=False)
    logger.clear()

    logger.debug("filtered out")
    logger.info("filtered out")
    logger.warn("passes through")
    logger.error("passes through")

    entries = logger.read()
    t.expect_eq("only 2 entries pass WARN filter", len(entries), 2)
    t.expect_eq("first passing is WARN",  entries[0]["level"], logger.WARN)
    t.expect_eq("second passing is ERROR", entries[1]["level"], logger.ERROR)

    # Reset to DEBUG for remaining tests
    setup()

def test_max_lines_rotation():
    t.suite("logger / max_lines rotation")
    logger.configure(log_file=TEST_LOG_FILE, max_lines=5,
                     min_level=logger.DEBUG, echo_console=False)
    logger.clear()

    for i in range(8):
        logger.info(f"Message {i}")

    entries = logger.read()
    t.expect_eq("capped at max_lines",        len(entries),        5)
    t.expect_eq("oldest entries dropped",     entries[0]["msg"],   "Message 3")
    t.expect_eq("newest entry preserved",     entries[-1]["msg"],  "Message 7")

    setup()   # restore default config

def test_read_limit():
    t.suite("logger / read limit")
    setup()
    logger.clear()

    for i in range(10):
        logger.info(f"Msg {i}")

    t.expect_eq("read all",        len(logger.read()),          10)
    t.expect_eq("read limit 3",    len(logger.read(limit=3)),   3)
    t.expect_eq("read limit 1",    len(logger.read(limit=1)),   1)
    t.expect_eq("limit returns newest",
                logger.read(limit=1)[0]["msg"], "Msg 9")

def test_read_formatted_text():
    t.suite("logger / read_formatted text")
    setup()
    logger.clear()

    logger.info("Hello", data={"x": 1})
    logger.warn("World")

    text = logger.read_formatted(fmt="text")
    t.expect_true("text contains INFO",    "INFO"  in text)
    t.expect_true("text contains WARN",    "WARN"  in text)
    t.expect_true("text contains Hello",   "Hello" in text)
    t.expect_true("text contains World",   "World" in text)
    t.expect_true("text contains data",    "{'x': 1}" in text or
                                           '{"x": 1}' in text)

def test_read_formatted_csv():
    t.suite("logger / read_formatted csv")
    setup()
    logger.clear()

    logger.info("CSV test")

    csv = logger.read_formatted(fmt="csv")
    lines = csv.split("\n")
    t.expect_eq("csv has header row",      lines[0], "ts,level,message,data")
    t.expect_eq("csv has data row",        len(lines), 2)
    t.expect_true("csv row contains INFO", "INFO"     in lines[1])
    t.expect_true("csv row contains msg",  "CSV test" in lines[1])

def test_read_formatted_json():
    t.suite("logger / read_formatted json")
    setup()
    logger.clear()

    logger.info("JSON test", data={"val": 99})

    raw  = logger.read_formatted(fmt="json")
    parsed = json.loads(raw)
    t.expect_in("log key present",         "log",   parsed)
    t.expect_in("count key present",        "count", parsed)
    t.expect_eq("count matches",           parsed["count"], 1)
    t.expect_eq("entry msg matches",
                parsed["log"][0]["msg"],   "JSON test")
    t.expect_eq("entry data matches",
                parsed["log"][0]["data"]["val"], 99)

def test_clear():
    t.suite("logger / clear")
    setup()
    logger.clear()

    logger.info("Before clear")
    t.expect_eq("has entries before clear", entry_count(), 1)
    logger.clear()
    t.expect_eq("empty after clear",        entry_count(), 0)

def test_missing_log_file():
    t.suite("logger / missing log file")
    logger.configure(log_file="nonexistent_log.txt", max_lines=20,
                     min_level=logger.DEBUG, echo_console=False)
    # reading a missing file should return empty list not crash
    entries = logger.read()
    t.expect_eq("returns empty list for missing file", entries, [])
    setup()   # restore

def test_print_previous_session():
    t.suite("logger / print_previous_session")
    setup()
    logger.clear()
    logger.info("Session message")
    # Just verify it doesn't crash — output goes to console
    try:
        logger.configure(log_file=TEST_LOG_FILE, max_lines=20,
                         min_level=logger.DEBUG, echo_console=True)
        logger.print_previous_session()
        t.expect_true("print_previous_session ran without error", True)
    except Exception as e:
        t.expect_true(f"print_previous_session raised: {e}", False)
    finally:
        setup()

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_basic_logging()
    test_all_levels()
    test_data_field()
    test_min_level_filtering()
    test_max_lines_rotation()
    test_read_limit()
    test_read_formatted_text()
    test_read_formatted_csv()
    test_read_formatted_json()
    test_clear()
    test_missing_log_file()
    test_print_previous_session()
    cleanup()
    return t.summary()

run()