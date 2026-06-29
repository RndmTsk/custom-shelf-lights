# http_server_test.py
# Tests for http_server.py

import json
import test_runner as t
import test_fixtures as tf
import logger
import http_server as srv

# ============================================================
# SETUP
# ============================================================

def setup():
    logger.configure(
        log_file="test_http_log.txt",
        max_lines=100,
        min_level=logger.DEBUG,
        echo_console=False,
    )
    srv.unregister_all()
    srv.stop()
    srv.set_socket_factory(None)

def cleanup():
    srv.stop()
    srv.unregister_all()
    import os
    try:
        os.remove("test_http_log.txt")
    except:
        pass

# ============================================================
# MOCK SOCKET
# ============================================================

class _MockConn:
    """Simulates an accepted client connection."""
    def __init__(self, request_str):
        self._data   = request_str.encode() if isinstance(
                           request_str, str) else request_str
        self.sent    = b""
        self.closed  = False
        self._timeout = None

    def settimeout(self, t):
        self._timeout = t

    def recv(self, n):
        return self._data[:n]

    def send(self, data):
        self.sent += data

    def close(self):
        self.closed = True

    def response_str(self):
        return self.sent.decode("utf-8", "ignore")

    def response_body(self):
        raw = self.response_str()
        if "\r\n\r\n" in raw:
            return json.loads(raw.split("\r\n\r\n", 1)[1])
        return None

    def status_line(self):
        return self.response_str().split("\r\n")[0]


class _MockServer:
    """
    Simulates a server socket.
    Feed requests via queue_request().
    """
    def __init__(self):
        self._queue = []
        self.closed = False

    def queue_request(self, request_str, addr=tf.TEST_CLIENT_ADDR):
        self._queue.append((request_str, addr))

    def accept(self):
        if self._queue:
            req, addr = self._queue.pop(0)
            return _MockConn(req), (addr, 9999)
        raise OSError("no connection")   # mimics non-blocking timeout

    def close(self):
        self.closed = True


_mock_server = None

def _install_mock_server():
    global _mock_server
    _mock_server = _MockServer()
    srv.set_socket_factory(lambda: _mock_server)
    srv.start()
    return _mock_server

def _make_get(path):
    return f"GET {path} HTTP/1.1\r\nHost: pico\r\n\r\n"

def _make_post(path, body_dict):
    body = json.dumps(body_dict)
    return (f"POST {path} HTTP/1.1\r\n"
            f"Host: pico\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}")

# ============================================================
# PARSE REQUEST TESTS
# ============================================================

def test_parse_get_simple():
    t.suite("http_server / parse_request GET simple")
    setup()
    method, parts, body, query = srv.parse_request(
        "GET /status HTTP/1.1\r\nHost: pico\r\n\r\n")
    t.expect_eq("method is GET",    method,   "GET")
    t.expect_eq("parts correct",    parts,    ["status"])
    t.expect_none("body is None",   body)
    t.expect_eq("query empty",      query,    {})

def test_parse_get_nested_path():
    t.suite("http_server / parse_request nested path")
    setup()
    method, parts, body, query = srv.parse_request(
        "GET /effect/CHASE_SMOOTH/left HTTP/1.1\r\n\r\n")
    t.expect_eq("method",  method, "GET")
    t.expect_eq("parts",   parts,  ["effect", "CHASE_SMOOTH", "left"])

def test_parse_query_string():
    t.suite("http_server / parse_request query string")
    setup()
    method, parts, body, query = srv.parse_request(
        "GET /log?format=csv&limit=10 HTTP/1.1\r\n\r\n")
    t.expect_eq("parts",          parts,           ["log"])
    t.expect_eq("format param",   query["format"], "csv")
    t.expect_eq("limit param",    query["limit"],  "10")

def test_parse_post_with_body():
    t.suite("http_server / parse_request POST with body")
    setup()
    body_dict = {"on": True, "brightness": 50}
    raw       = _make_post("/set", body_dict)
    method, parts, body, query = srv.parse_request(raw)
    t.expect_eq("method is POST",   method,            "POST")
    t.expect_eq("parts correct",    parts,             ["set"])
    t.expect_not_none("body parsed", body)
    t.expect_eq("on field",         body["on"],        True)
    t.expect_eq("brightness field", body["brightness"], 50)

def test_parse_post_invalid_json():
    t.suite("http_server / parse_request POST invalid JSON body")
    setup()
    raw = ("POST /set HTTP/1.1\r\n"
           "Content-Length: 5\r\n"
           "\r\n"
           "{bad}")
    method, parts, body, query = srv.parse_request(raw)
    t.expect_eq("method is POST",  method, "POST")
    t.expect_none("body is None for bad JSON", body)

def test_parse_empty_request():
    t.suite("http_server / parse_request empty")
    setup()
    method, parts, body, query = srv.parse_request("")
    t.expect_none("method is None", method)
    t.expect_eq("parts empty",      parts, [])

def test_parse_root_path():
    t.suite("http_server / parse_request root path")
    setup()
    method, parts, body, query = srv.parse_request(
        "GET / HTTP/1.1\r\n\r\n")
    t.expect_eq("method is GET", method, "GET")
    t.expect_eq("parts empty",   parts,  [])

def test_parse_url_encoding():
    t.suite("http_server / parse_request URL encoding")
    setup()
    method, parts, body, query = srv.parse_request(
        "GET /colour/15%2F5%2F0 HTTP/1.1\r\n\r\n")
    t.expect_eq("method is GET", method, "GET")
    t.expect_true("path decoded", len(parts) > 0)

def test_parse_bytes_input():
    t.suite("http_server / parse_request bytes input")
    setup()
    raw = b"GET /status HTTP/1.1\r\nHost: pico\r\n\r\n"
    method, parts, body, query = srv.parse_request(raw)
    t.expect_eq("method",  method, "GET")
    t.expect_eq("parts",   parts,  ["status"])

# ============================================================
# FORMAT RESPONSE TESTS
# ============================================================

def test_format_200():
    t.suite("http_server / format_response 200")
    setup()
    resp = srv.format_response(200, {"status": "ok"})
    t.expect_true("starts with HTTP",    resp.startswith("HTTP/1.1 200"))
    t.expect_true("contains JSON",       '"status"' in resp)
    t.expect_true("has content-type",
                  "application/json" in resp)

def test_format_400():
    t.suite("http_server / format_response 400")
    setup()
    resp = srv.format_response(400, {"error": "bad request"})
    t.expect_true("status line correct",
                  "400 Bad Request" in resp)

def test_format_404():
    t.suite("http_server / format_response 404")
    setup()
    resp = srv.format_response(404, {"error": "not found"})
    t.expect_true("status line correct",
                  "404 Not Found" in resp)

def test_format_unknown_code():
    t.suite("http_server / format_response unknown code")
    setup()
    resp = srv.format_response(418, {"error": "teapot"})
    t.expect_true("includes code", "418" in resp)

# ============================================================
# HANDLER REGISTRATION TESTS
# ============================================================

def test_register_and_dispatch():
    t.suite("http_server / register and dispatch")
    setup()

    def my_handler(parts, method, body, query):
        return 200, {"cmd": parts[0]}

    srv.register("hello", my_handler)
    t.expect_in("hello registered",
                "hello", srv.registered_commands())

    status, resp = srv.dispatch(["hello"], "GET", None, {})
    t.expect_eq("status 200",      status,      200)
    t.expect_eq("response correct", resp["cmd"], "hello")

def test_unregister():
    t.suite("http_server / unregister")
    setup()
    srv.register("test", lambda p, m, b, q: (200, {}))
    t.expect_in("registered",       "test", srv.registered_commands())
    srv.unregister("test")
    t.expect_false("unregistered",
                   "test" in srv.registered_commands())

def test_unregister_all():
    t.suite("http_server / unregister_all")
    setup()
    srv.register("a", lambda p, m, b, q: (200, {}))
    srv.register("b", lambda p, m, b, q: (200, {}))
    srv.unregister_all()
    t.expect_eq("all removed", srv.registered_commands(), [])

def test_register_overwrites():
    t.suite("http_server / register overwrites existing")
    setup()
    srv.register("cmd", lambda p, m, b, q: (200, {"v": 1}))
    srv.register("cmd", lambda p, m, b, q: (200, {"v": 2}))
    _, resp = srv.dispatch(["cmd"], "GET", None, {})
    t.expect_eq("second handler used", resp["v"], 2)

# ============================================================
# DISPATCH TESTS
# ============================================================

def test_dispatch_unknown_command():
    t.suite("http_server / dispatch unknown command")
    setup()
    status, resp = srv.dispatch(["unknown"], "GET", None, {})
    t.expect_eq("status 404",         status,          404)
    t.expect_in("error in response",  "error",         resp)
    t.expect_in("available in resp",  "available",     resp)

def test_dispatch_no_parts():
    t.suite("http_server / dispatch no parts")
    setup()
    status, resp = srv.dispatch([], "GET", None, {})
    t.expect_eq("status 400",        status, 400)
    t.expect_in("error in response", "error", resp)

def test_dispatch_unsupported_method():
    t.suite("http_server / dispatch unsupported method")
    setup()
    srv.register("cmd", lambda p, m, b, q: (200, {}))
    status, resp = srv.dispatch(["cmd"], "DELETE", None, {})
    t.expect_eq("status 405",        status, 405)
    t.expect_in("error in response", "error", resp)

def test_dispatch_handler_exception():
    t.suite("http_server / dispatch handler exception")
    setup()

    def broken_handler(parts, method, body, query):
        raise RuntimeError("Something went wrong")

    srv.register("broken", broken_handler)
    status, resp = srv.dispatch(["broken"], "GET", None, {})
    t.expect_eq("status 500",        status, 500)
    t.expect_in("error in response", "error", resp)

def test_dispatch_invalid_return():
    t.suite("http_server / dispatch invalid handler return")
    setup()
    srv.register("bad", lambda p, m, b, q: "not a tuple")
    status, resp = srv.dispatch(["bad"], "GET", None, {})
    t.expect_eq("status 500",        status, 500)
    t.expect_in("error in response", "error", resp)

def test_dispatch_passes_all_args():
    t.suite("http_server / dispatch passes all args to handler")
    setup()
    received = {}

    def capturing_handler(parts, method, body, query):
        received["parts"]  = parts
        received["method"] = method
        received["body"]   = body
        received["query"]  = query
        return 200, {}

    srv.register("capture", capturing_handler)
    srv.dispatch(["capture", "arg1"], "POST",
                 {"key": "val"}, {"q": "1"})

    t.expect_eq("parts passed",  received["parts"],  ["capture", "arg1"])
    t.expect_eq("method passed", received["method"], "POST")
    t.expect_eq("body passed",   received["body"],   {"key": "val"})
    t.expect_eq("query passed",  received["query"],  {"q": "1"})

# ============================================================
# SERVER LIFECYCLE TESTS
# ============================================================

def test_start_and_stop():
    t.suite("http_server / start and stop")
    setup()
    mock = _install_mock_server()
    t.expect_true("is_running after start", srv.is_running())
    srv.stop()
    t.expect_false("not running after stop", srv.is_running())
    t.expect_true("mock socket closed",      mock.closed)

def test_tick_no_requests():
    t.suite("http_server / tick with no requests")
    setup()
    _install_mock_server()
    result = srv.tick()
    t.expect_false("tick returns False when no request", result)

def test_tick_handles_get():
    t.suite("http_server / tick handles GET request")
    setup()
    mock = _install_mock_server()

    srv.register("ping", lambda p, m, b, q: (200, {"pong": True}))
    mock.queue_request(_make_get("/ping"))

    result = srv.tick()
    t.expect_true("tick returns True when request handled", result)

def test_tick_response_content():
    t.suite("http_server / tick response content")
    setup()
    mock = _install_mock_server()

    srv.register("hello",
                 lambda p, m, b, q: (200, {"msg": "world"}))

    conn = _MockConn(_make_get("/hello"))
    mock._queue.append((conn._data.decode(), tf.TEST_CLIENT_ADDR))

    srv.tick()

def test_tick_unknown_route_returns_404():
    t.suite("http_server / tick unknown route returns 404")
    setup()
    mock = _install_mock_server()
    mock.queue_request(_make_get("/doesnotexist"))

    srv.tick()
    # tick should complete without error
    t.expect_true("tick completed without error", True)

def test_tick_post_request():
    t.suite("http_server / tick handles POST request")
    setup()
    mock     = _install_mock_server()
    received = {}

    def post_handler(parts, method, body, query):
        received["method"] = method
        received["body"]   = body
        return 200, {"ok": True}

    srv.register("set", post_handler)
    mock.queue_request(_make_post("/set", {"brightness": 75}))

    srv.tick()
    t.expect_eq("method is POST",    received.get("method"), "POST")
    t.expect_not_none("body parsed", received.get("body"))
    t.expect_eq("brightness field",
                received["body"]["brightness"], 75)

def test_tick_not_running():
    t.suite("http_server / tick when server not running")
    setup()
    # Don't start server
    result = srv.tick()
    t.expect_false("tick returns False when not running", result)

def test_configure():
    t.suite("http_server / configure")
    setup()
    srv.configure(host="127.0.0.1", port=8080,
                  timeout_ms=5000, recv_bytes=4096)
    t.expect_eq("host set",        srv._host,       "127.0.0.1")
    t.expect_eq("port set",        srv._port,       8080)
    t.expect_eq("timeout_ms set",  srv._timeout_ms, 5000)
    t.expect_eq("recv_bytes set",  srv._recv_bytes, 4096)

# ============================================================
# RUN
# ============================================================

def run():
    t.reset()
    test_parse_get_simple()
    test_parse_get_nested_path()
    test_parse_query_string()
    test_parse_post_with_body()
    test_parse_post_invalid_json()
    test_parse_empty_request()
    test_parse_root_path()
    test_parse_url_encoding()
    test_parse_bytes_input()
    test_format_200()
    test_format_400()
    test_format_404()
    test_format_unknown_code()
    test_register_and_dispatch()
    test_unregister()
    test_unregister_all()
    test_register_overwrites()
    test_dispatch_unknown_command()
    test_dispatch_no_parts()
    test_dispatch_unsupported_method()
    test_dispatch_handler_exception()
    test_dispatch_invalid_return()
    test_dispatch_passes_all_args()
    test_start_and_stop()
    test_tick_no_requests()
    test_tick_handles_get()
    test_tick_response_content()
    test_tick_unknown_route_returns_404()
    test_tick_post_request()
    test_tick_not_running()
    test_configure()
    cleanup()
    return t.summary()

run()