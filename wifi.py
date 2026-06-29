# wifi.py
# WiFi connection management.
# Depends on: logger, watchdog

# ============================================================
# IMPORTS
# ============================================================

import network
import time
import logger
import watchdog

# ============================================================
# GLOBALS
# ============================================================

_wlan          = None
_ssid          = ""
_password      = ""
_static_ip     = None
_subnet        = None
_gateway       = None
_dns           = None
_ip            = ""
_connected_at  = 0
_connect_count = 0
_fail_count    = 0
_wlan_factory  = None   # injectable for testing

# ============================================================
# CAPABILITIES
# ============================================================

def configure(ssid, password, static_ip=None, subnet=None,
              gateway=None, dns=None):
    """
    Configure WiFi credentials and optional static IP.
    Call before connect().
    """
    global _ssid, _password, _static_ip, _subnet, _gateway, _dns
    _ssid      = ssid
    _password  = password
    _static_ip = static_ip
    _subnet    = subnet
    _gateway   = gateway
    _dns       = dns

def set_wlan_factory(factory):
    """
    Override the WLAN constructor. Used in tests to inject mocks.
    Pass None to restore default (network.WLAN).
    """
    global _wlan_factory
    _wlan_factory = factory

def _make_wlan():
    """Create a WLAN instance using factory or default."""
    if _wlan_factory is not None:
        return _wlan_factory(network.STA_IF)
    return network.WLAN(network.STA_IF)

def connect(timeout_ms=20000, interval_ms=500):
    """
    Connect to WiFi using configured credentials.
    Returns True on success, False on failure.
    Feeds watchdog while waiting.
    """
    global _wlan, _ip, _connected_at, _connect_count, _fail_count

    _wlan = _make_wlan()
    _wlan.active(True)

    if _static_ip and _subnet and _gateway and _dns:
        try:
            _wlan.ifconfig((_static_ip, _subnet, _gateway, _dns))
        except Exception as e:
            logger.warn("Static IP config failed — using DHCP",
                        data={"error": str(e)})

    logger.info("Connecting to WiFi",
                data={"ssid": _ssid, "static_ip": _static_ip})

    _wlan.connect(_ssid, _password)
    _connect_count += 1

    connected = watchdog.feed_while(
        lambda: not _wlan.isconnected(),
        timeout_ms=timeout_ms,
        interval_ms=interval_ms,
    )

    if connected:
        cfg           = _wlan.ifconfig()
        _ip           = cfg[0]
        _connected_at = time.time()
        logger.info("WiFi connected",
                    data={"ip": _ip, "ssid": _ssid})
        return True
    else:
        _fail_count += 1
        logger.warn("WiFi connection failed",
                    data={"ssid": _ssid, "status": status()})
        return False

def disconnect():
    """Disconnect from WiFi."""
    global _ip
    if _wlan is not None:
        try:
            _wlan.disconnect()
            _wlan.active(False)
        except Exception as e:
            logger.warn("WiFi disconnect error", data={"error": str(e)})
        _ip = ""
    logger.info("WiFi disconnected")

def is_connected():
    """Return True if currently connected."""
    if _wlan is None:
        return False
    return _wlan.isconnected()

def check_and_reconnect(timeout_ms=20000):
    """
    Check connection and reconnect if dropped.
    Call periodically from main loop.
    Returns True if connected after check.
    """
    if is_connected():
        return True
    logger.warn("WiFi dropped — reconnecting")
    return connect(timeout_ms=timeout_ms)

def ip():
    """Return current IP address string, empty if not connected."""
    return _ip

def ssid():
    """Return configured SSID."""
    return _ssid

def status():
    """
    Return raw wlan status code.
    0=link down, 1=joining, 2=no IP, 3=connected,
    -1=failed, -2=no network, -3=bad password
    """
    if _wlan is None:
        return -1
    return _wlan.status()

def stats():
    """Return connection statistics dict."""
    return {
        "ssid":          _ssid,
        "ip":            _ip,
        "connected":     is_connected(),
        "status":        status(),
        "connect_count": _connect_count,
        "fail_count":    _fail_count,
        "connected_at":  _connected_at,
    }

def sync_time():
    """
    Sync Pico RTC via NTP.
    Call after successful connect().
    Returns True on success.
    """
    if not is_connected():
        logger.warn("NTP sync skipped — not connected")
        return False
    try:
        import ntptime
        watchdog.feed()
        ntptime.settime()
        watchdog.feed()
        logger.info("NTP sync successful", data={"ts": time.time()})
        return True
    except Exception as e:
        logger.warn("NTP sync failed", data={"error": str(e)})
        return False