# http_server.py
# Minimal HTTP server that accepts requests and delegates
# to registered handler functions.
# Depends on: logger, watchdog
#
# Design:
#   - Handlers are registered per command prefix
#   - main.py registers built-in handlers (ping, log, update)
#   - extensions.py registers its own handlers via register()
#   - Unknown routes return 404
#   - All handlers receive (parts, method, body, query)
#     and return (status_code, response_dict)

# ============================================================
# IMPORTS
# ============================================================

import socket
import json
import logger
import watchdog

# ============================================================
# GLOBALS
# ============================================================

_host            = "0.0.0.0"
_port            = 80
_timeout_ms      = 3000
_recv_bytes      = 2048

# --- State ---
_server          = None
_handlers        = {}   # cmd -> fn(parts, method, body, query)
_socket_factory  = None # injectable for testing

# ============================================================
# CONFIGURE
# ============================================================

def configure(host="0.0.0.0", port=80,
              timeout_ms=3000, recv_bytes=2048):
    """
    Configure server parameters.
    Call before start().
    """
    global _host, _port, _timeout_ms, _recv_bytes
    _host       = host
    _port       = port
    _timeout_ms = timeout_ms
    _recv_bytes = recv_bytes

def set_socket_factory(fn):
    """
    Override socket creation. Used in tests.
    fn() should return a socket-like object.
    Pass None to restore default.
    """
    global _socket_factory
    _socket_factory = fn

# ============================================================
# HANDLERS
# ============================================================

def register(cmd, handler_fn):
    """
    Register a handler for a command prefix.
    cmd        — first URL path segment e.g. "on", "status"
    handler_fn — fn(parts, method, body, query)
                 returns (status_code, response_dict)
    Overwrites any existing handler for that cmd.
    """
    _handlers[cmd.lower()] = handler_fn
    logger.info("Handler registered", data={"cmd": cmd})

def unregister(cmd):
    """Remove a handler. Silent if not registered."""
    _handlers.pop(cmd.lower(), None)

def unregister_all():
    """Remove all registered handlers."""
    _handlers.clear()

def registered_commands():
    """Return list of registered command names."""
    return list(_handlers.keys())

# ============================================================
# REQUEST PARSING
# ============================================================

def parse_request(raw):
    """
    Parse raw HTTP request bytes/string.
    Returns (method, parts, body, query) or
            (None, [], None, {}) on failure.

    parts — URL path split on "/" with empty segments removed
    body  — parsed JSON dict for POST requests, None otherwise
    query — dict of query string key=value pairs
    """
    try:
        if not raw:
            return None, [], None, {}

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "ignore")

        lines = raw.split("\r\n")
        if not lines:
            return None, [], None, {}

        first = lines[0].split(" ")
        if len(first) < 2:
            return None, [], None, {}

        method    = first[0].upper()
        full_path = first[1] if len(first) > 1 else "/"

        # Split path and query string
        if "?" in full_path:
            path_str, query_str = full_path.split("?", 1)
        else:
            path_str, query_str = full_path, ""

        # URL decode common encodings
        path_str = (path_str
                    .replace("%20", " ")
                    .replace("%2F", "/")
                    .replace("%2B", "+"))

        parts = [p for p in path_str.split("/") if p]

        # Parse query string
        query = {}
        for param in query_str.split("&"):
            if "=" in param:
                k, v = param.split("=", 1)
                query[k.lower().strip()] = v.strip()

        # Parse body for POST
        body = None
        if method == "POST":
            try:
                sep = raw.index("\r\n\r\n")
                raw_body = raw[sep + 4:].strip()
                if raw_body:
                    body = json.loads(raw_body)
            except (ValueError, Exception) as e:
                logger.warn("Body parse error",
                            data={"error": str(e)})

        return method, parts, body, query

    except Exception as e:
        logger.error("Request parse error",
                     data={"error": str(e)})
        return None, [], None, {}

# ============================================================
# RESPONSE FORMATTING
# ============================================================

def format_response(status_code, body_dict):
    """
    Format a response dict into an HTTP response string.
    status_code — integer e.g. 200, 400, 404, 500
    body_dict   — dict to serialise as JSON
    """
    status_text = {
        200: "200 OK",
        400: "400 Bad Request",
        404: "404 Not Found",
        405: "405 Method Not Allowed",
        500: "500 Internal Server Error",
        503: "503 Service Unavailable",
    }.get(status_code, f"{status_code} Unknown")

    try:
        body = json.dumps(body_dict)
    except Exception as e:
        body = json.dumps({"error": "Response serialisation failed",
                           "detail": str(e)})

    return (
        f"HTTP/1.1 {status_text}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{body}"
    )

# ============================================================
# ROUTING
# ============================================================

def dispatch(parts, method, body, query):
    """
    Route a parsed request to the correct handler.
    Returns (status_code, response_dict).
    """
    if not parts:
        return 400, {"error": "No command provided"}

    cmd = parts[0].lower()

    if method not in ("GET", "POST"):
        return 405, {"error": f"Method {method} not supported"}

    handler = _handlers.get(cmd)
    if handler is None:
        return 404, {"error": f"Unknown command: {cmd}",
                     "available": registered_commands()}

    try:
        result = handler(parts, method, body, query)
        # Validate handler return value
        if (not isinstance(result, tuple) or
                len(result) != 2 or
                not isinstance(result[0], int)):
            logger.error("Handler returned invalid result",
                         data={"cmd": cmd, "result": str(result)})
            return 500, {"error": "Handler returned invalid result"}
        return result
    except Exception as e:
        logger.error("Handler raised exception",
                     data={"cmd": cmd, "error": str(e)})
        return 500, {"error": f"Handler error: {str(e)}"}

# ============================================================
# SERVER LIFECYCLE
# ============================================================

def start():
    """
    Start the HTTP server.
    Returns True on success, False on failure.
    """
    global _server
    try:
        if _socket_factory is not None:
            _server = _socket_factory()
        else:
            addr    = socket.getaddrinfo(_host, _port)[0][-1]
            _server = socket.socket()
            _server.setsockopt(socket.SOL_SOCKET,
                               socket.SO_REUSEADDR, 1)
            _server.bind(addr)
            _server.listen(1)
            _server.settimeout(0.05)

        logger.info("HTTP server started",
                    data={"host": _host, "port": _port})
        return True
    except Exception as e:
        logger.error("HTTP server start failed",
                     data={"error": str(e)})
        _server = None
        return False

def stop():
    """Stop the HTTP server and close the socket."""
    global _server
    if _server is not None:
        try:
            _server.close()
        except:
            pass
        _server = None
        logger.info("HTTP server stopped")

def is_running():
    """Return True if server socket is open."""
    return _server is not None

def tick():
    """
    Accept and handle one pending request if available.
    Non-blocking — returns immediately if no request waiting.
    Call this every main loop iteration.
    Returns True if a request was handled, False otherwise.
    """
    if _server is None:
        return False

    try:
        conn, addr = _server.accept()
    except OSError:
        return False   # no connection waiting — normal

    try:
        conn.settimeout(_timeout_ms / 1000)
        raw     = conn.recv(_recv_bytes)
        method, parts, body, query = parse_request(raw)

        if method is None:
            status, response = 400, {"error": "Malformed request"}
        else:
            status, response = dispatch(parts, method, body, query)

        conn.send(format_response(status, response).encode())
        logger.info("Request handled", data={
            "from":   addr[0],
            "method": method,
            "path":   "/" + "/".join(parts) if parts else "/",
            "status": status,
        })
        return True

    except OSError as e:
        logger.warn("Request timeout or connection error",
                    data={"from": addr[0], "error": str(e)})
        return False
    except Exception as e:
        logger.error("Unexpected error handling request",
                     data={"error": str(e)})
        return False
    finally:
        try:
            conn.close()
        except:
            pass