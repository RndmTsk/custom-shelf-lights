# test_runner.py
# Minimal test framework for MicroPython.
# No dependencies — runs on Pico without any external libraries.

_results = []
_current_suite = ""

def suite(name):
    """Start a named test suite."""
    global _current_suite
    _current_suite = name
    print(f"\n{'=' * 40}")
    print(f"Suite: {name}")
    print(f"{'=' * 40}")

def expect_eq(label, actual, expected):
    """Assert actual == expected."""
    _assert(label, actual == expected,
            f"expected {repr(expected)}, got {repr(actual)}")

def expect_true(label, value):
    """Assert value is truthy."""
    _assert(label, bool(value),
            f"expected truthy, got {repr(value)}")

def expect_false(label, value):
    """Assert value is falsy."""
    _assert(label, not bool(value),
            f"expected falsy, got {repr(value)}")

def expect_none(label, value):
    """Assert value is None."""
    _assert(label, value is None,
            f"expected None, got {repr(value)}")

def expect_not_none(label, value):
    """Assert value is not None."""
    _assert(label, value is not None,
            f"expected not None, got None")

def expect_in(label, item, collection):
    """Assert item in collection."""
    _assert(label, item in collection,
            f"expected {repr(item)} in {repr(collection)}")

def expect_type(label, value, expected_type):
    """Assert isinstance(value, expected_type)."""
    _assert(label, isinstance(value, expected_type),
            f"expected type {expected_type.__name__}, "
            f"got {type(value).__name__}")

def expect_raises(label, fn, exception_type=Exception):
    """Assert fn() raises exception_type."""
    try:
        fn()
        _assert(label, False,
                f"expected {exception_type.__name__} to be raised, "
                f"but no exception was raised")
    except exception_type:
        _assert(label, True, "")
    except Exception as e:
        _assert(label, False,
                f"expected {exception_type.__name__}, "
                f"got {type(e).__name__}: {e}")

def expect_gt(label, value, threshold):
    """Assert value > threshold."""
    _assert(label, value > threshold,
            f"expected {repr(value)} > {repr(threshold)}")

def expect_gte(label, value, threshold):
    """Assert value >= threshold."""
    _assert(label, value >= threshold,
            f"expected {repr(value)} >= {repr(threshold)}")

def expect_lt(label, value, threshold):
    """Assert value < threshold."""
    _assert(label, value < threshold,
            f"expected {repr(value)} < {repr(threshold)}")

def _assert(label, passed, reason):
    full_label = f"{_current_suite} / {label}" if _current_suite else label
    if passed:
        print(f"  ✓ {label}")
        _results.append(("PASS", full_label, None))
    else:
        print(f"  ✗ {label}")
        print(f"    {reason}")
        _results.append(("FAIL", full_label, reason))

def summary():
    """Print final summary and return True if all passed."""
    passed = [r for r in _results if r[0] == "PASS"]
    failed = [r for r in _results if r[0] == "FAIL"]
    print(f"\n{'=' * 40}")
    print(f"Results: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("\nFailed tests:")
        for _, label, reason in failed:
            print(f"  ✗ {label}")
            print(f"    {reason}")
    print("=" * 40)
    return len(failed) == 0

def reset():
    """Clear results — use between independent test runs."""
    global _results, _current_suite
    _results      = []
    _current_suite = ""