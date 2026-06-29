# test_env.py
# Tests for env.py

import os
import test_runner as t
import test_fixtures as tf
import env

# ============================================================
# HELPERS
# ============================================================

TEST_ENV_FILE = "test.env"

def write_env(content):
    with open(TEST_ENV_FILE, "w") as f:
        f.write(content)

def cleanup():
    try:
        os.remove(TEST_ENV_FILE)
    except:
        pass

# ============================================================
# TESTS
# ============================================================

def test_basic_load():
    t.suite("env / basic load")
    write_env(
        "WIFI_SSID=MyNetwork\n"
        "WIFI_PASSWORD=Secret123\n"
        f"STATIC_IP={tf.TEST_STATIC_IP}\n"
    )
    count = env.load(TEST_ENV_FILE)
    t.expect_eq("loads correct count",       count,                    3)
    t.expect_eq("reads string value",        env.get("WIFI_SSID"),     "MyNetwork")
    t.expect_eq("reads second value",        env.get("WIFI_PASSWORD"), "Secret123")
    t.expect_eq("reads third value",         env.get("STATIC_IP"),     tf.TEST_STATIC_IP)

def test_comments_and_blanks():
    t.suite("env / comments and blank lines")
    write_env(
        "# This is a comment\n"
        "\n"
        "KEY=value\n"
        "# Another comment\n"
        "\n"
        "KEY2=value2\n"
    )
    count = env.load(TEST_ENV_FILE)
    t.expect_eq("ignores comments and blanks", count,            2)
    t.expect_eq("reads KEY",                  env.get("KEY"),   "value")
    t.expect_eq("reads KEY2",                 env.get("KEY2"),  "value2")

def test_whitespace_stripping():
    t.suite("env / whitespace stripping")
    write_env(
        "  KEY  =  value with spaces  \n"
        "KEY2=nospaces\n"
    )
    env.load(TEST_ENV_FILE)
    t.expect_eq("strips key whitespace",   env.get("KEY"),  "value with spaces")
    t.expect_eq("no stripping needed",     env.get("KEY2"), "nospaces")

def test_defaults():
    t.suite("env / defaults")
    write_env("KEY=value\n")
    env.load(TEST_ENV_FILE)
    t.expect_eq("missing key returns default",     env.get("MISSING", "fallback"), "fallback")
    t.expect_eq("missing key returns empty str",   env.get("MISSING"),             "")
    t.expect_eq("get_int missing returns default", env.get_int("MISSING", 42),     42)
    t.expect_eq("get_float missing returns 0.0",   env.get_float("MISSING"),       0.0)
    t.expect_eq("get_bool missing returns False",  env.get_bool("MISSING"),        False)

def test_typed_getters():
    t.suite("env / typed getters")
    write_env(
        "INT_VAL=22\n"
        "FLOAT_VAL=0.3\n"
        "BOOL_TRUE=true\n"
        "BOOL_ONE=1\n"
        "BOOL_YES=yes\n"
        "BOOL_FALSE=false\n"
        "BOOL_ZERO=0\n"
        "BOOL_NO=no\n"
        "BAD_INT=notanumber\n"
        "BAD_FLOAT=notafloat\n"
    )
    env.load(TEST_ENV_FILE)
    t.expect_eq("get_int",              env.get_int("INT_VAL"),      22)
    t.expect_eq("get_float",            env.get_float("FLOAT_VAL"),  0.3)
    t.expect_eq("get_bool true",        env.get_bool("BOOL_TRUE"),   True)
    t.expect_eq("get_bool 1",           env.get_bool("BOOL_ONE"),    True)
    t.expect_eq("get_bool yes",         env.get_bool("BOOL_YES"),    True)
    t.expect_eq("get_bool false",       env.get_bool("BOOL_FALSE"),  False)
    t.expect_eq("get_bool 0",           env.get_bool("BOOL_ZERO"),   False)
    t.expect_eq("get_bool no",          env.get_bool("BOOL_NO"),     False)
    t.expect_eq("bad int returns 0",    env.get_int("BAD_INT"),      0)
    t.expect_eq("bad float returns 0",  env.get_float("BAD_FLOAT"),  0.0)

def test_has_and_keys():
    t.suite("env / has and all_keys")
    write_env(
        "A=1\n"
        "B=2\n"
        "C=3\n"
    )
    env.load(TEST_ENV_FILE)
    t.expect_true("has existing key",      env.has("A"))
    t.expect_false("has missing key",      env.has("MISSING"))
    keys = env.all_keys()
    t.expect_eq("all_keys count",          len(keys), 3)
    t.expect_in("A in all_keys",           "A", keys)
    t.expect_in("B in all_keys",           "B", keys)
    t.expect_in("C in all_keys",           "C", keys)

def test_equals_in_value():
    t.suite("env / equals sign in value")
    write_env("URL=http://example.com?foo=bar&baz=qux\n")
    env.load(TEST_ENV_FILE)
    t.expect_eq("value with equals signs",
                env.get("URL"), "http://example.com?foo=bar&baz=qux")

def test_missing_file():
    t.suite("env / missing file")
    count = env.load("does_not_exist.env")
    t.expect_eq("returns 0 for missing file", count, 0)
    t.expect_eq("get returns default",
                env.get("ANYTHING", "default"), "default")

def test_reload_clears_previous():
    t.suite("env / reload clears previous values")
    write_env("FIRST=yes\n")
    env.load(TEST_ENV_FILE)
    t.expect_eq("first load has FIRST", env.get("FIRST"), "yes")
    write_env("SECOND=yes\n")
    env.load(TEST_ENV_FILE)
    t.expect_eq("second load has SECOND",   env.get("SECOND"), "yes")
    t.expect_eq("second load cleared FIRST", env.get("FIRST"),  "")

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_basic_load()
    test_comments_and_blanks()
    test_whitespace_stripping()
    test_defaults()
    test_typed_getters()
    test_has_and_keys()
    test_equals_in_value()
    test_missing_file()
    test_reload_clears_previous()
    cleanup()
    return t.summary()

run()