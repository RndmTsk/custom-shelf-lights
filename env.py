# env.py
# Loads KEY=VALUE pairs from a .env file.
# No dependencies — safe to import anywhere.

# ============================================================
# GLOBALS
# ============================================================

_env = {}

# ============================================================
# CAPABILITIES
# ============================================================

def load(path=".env"):
    """
    Parse .env file into internal dict.
    Lines starting with # are comments.
    Blank lines are ignored.
    Whitespace around keys and values is stripped.
    Returns number of keys loaded.
    """
    global _env
    _env = {}
    try:
        with open(path, "r") as f:
            for line in f.readlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                _env[key.strip()] = value.strip()
        return len(_env)
    except OSError:
        return 0

def get(key, default=""):
    """Get a value by key, with optional default."""
    return _env.get(key, default)

def get_int(key, default=0):
    """Get a value as int, returning default if missing or invalid."""
    try:
        return int(_env.get(key, default))
    except (ValueError, TypeError):
        return default

def get_float(key, default=0.0):
    """Get a value as float, returning default if missing or invalid."""
    try:
        return float(_env.get(key, default))
    except (ValueError, TypeError):
        return default

def get_bool(key, default=False):
    """
    Get a value as bool.
    True values: "true", "1", "yes"
    False values: "false", "0", "no"
    """
    val = _env.get(key, "").lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default

def all_keys():
    """Return list of all loaded keys."""
    return list(_env.keys())

def has(key):
    """Return True if key exists."""
    return key in _env