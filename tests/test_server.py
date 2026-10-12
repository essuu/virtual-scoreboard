"""Check the web server serves the pages and the current state."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import ecs_receiver


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ecs_receiver.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode()


def test_pages(server):
    for path in ("/", "/?layout=classicboard", "/status"):
        status, body = get(server + path)
        assert status == 200 and "<html" in body.lower()


def test_state_and_reset(server):
    ecs_receiver.BOARD.apply(5, "123", 10)
    status, body = get(server + "/state")
    assert json.loads(body)["values"]["total"] == "123"
    req = urllib.request.Request(server + "/reset", method="POST")
    urllib.request.urlopen(req, timeout=5).read()
    assert json.loads(get(server + "/state")[1])["values"]["total"] == ""


def test_unknown_path(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(server + "/nope")
    assert e.value.code == 404
