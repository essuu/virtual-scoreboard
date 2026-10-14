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
    for path in ("/", "/?layout=classicboard", "/status", "/testcard?end=right"):
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


def test_match_controls(server):
    d = ecs_receiver.DIRECTOR
    status, body = get(server + "/api/home-first")
    assert json.loads(body)["batting"] == "home"
    assert json.loads(get(server + "/state")[1])["match"]["batting"] == "home"
    get(server + "/api/batting-first?team=away")
    assert d.batting_first == "away"
    st = json.loads(get(server + "/api/right")[1])
    assert st["bowling_end"] == "right" and st["target_scene"] == "Camera Right"
    req = urllib.request.Request(server + "/api/auto?on=0", method="POST")
    assert json.loads(urllib.request.urlopen(req, timeout=5).read())["auto"] is False
    get(server + "/api/auto?on=toggle")
    assert d.auto is True
    with pytest.raises(urllib.error.HTTPError) as e:
        get(server + "/api/bowling?end=middle")
    assert e.value.code == 400
    # Clear scoreboard (new match) also clears the match settings
    urllib.request.urlopen(urllib.request.Request(server + "/reset", method="POST"), timeout=5).read()
    assert d.batting_first == "" and d.start_end == ""


def test_second_innings_swaps_batting_side():
    d = ecs_receiver.DIRECTOR
    d.set_batting_first("home")
    ecs_receiver.BOARD.apply(11, "212", 10)          # end-of-innings refresh sets the 1st innings total
    assert ecs_receiver.BOARD.snapshot()["match"]["batting"] == "away"
