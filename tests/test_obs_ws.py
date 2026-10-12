"""The OBS WebSocket client against a small fake obs-websocket v5 server."""
import json
import socket
import threading
import time

import obs_ws

PASSWORD = "secret123"


class FakeOBSServer:
    def __init__(self, password=PASSWORD):
        self.password = password
        self.program = "Camera Left"
        self.requests = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.conn = None
        threading.Thread(target=self._serve, daemon=True).start()

    def send(self, obj):
        self.conn.sendall(obs_ws.ws_encode(json.dumps(obj), mask=False))

    def _serve(self):
        conn, _ = self.sock.accept()
        self.conn = conn
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(4096)
        key = [l.split(":", 1)[1].strip() for l in head.decode().split("\r\n")
               if l.lower().startswith("sec-websocket-key")][0]
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Accept: %s\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n"
                      % obs_ws.ws_accept_key(key)).encode())
        hello = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"challenge": "chal", "salt": "salty"}
        self.send({"op": 0, "d": hello})
        op, data = obs_ws.ws_read(conn)
        ident = json.loads(data)["d"]
        if self.password and ident.get("authentication") != obs_ws.auth_string(self.password, "salty", "chal"):
            conn.sendall(obs_ws.ws_encode(b"\x0f\xa9bad auth", opcode=8, mask=False))   # 4009
            conn.close()
            return
        self.send({"op": 2, "d": {"negotiatedRpcVersion": 1}})
        while True:
            try:
                op, data = obs_ws.ws_read(conn)
            except Exception:
                return
            req = json.loads(data)["d"]
            self.requests.append(req)
            rt, rd = req["requestType"], {}
            if rt == "GetCurrentProgramScene":
                rd = {"sceneName": self.program}
            elif rt == "GetSceneList":
                rd = {"scenes": [{"sceneName": n} for n in ("Camera Left", "Camera Right", "Full Board", "Break")]}
            elif rt == "SetCurrentProgramScene":
                self.program = req["requestData"]["sceneName"]
            self.send({"op": 7, "d": {"requestType": rt, "requestId": req["requestId"],
                                      "requestStatus": {"result": True, "code": 100}, "responseData": rd}})
            if rt == "SetCurrentProgramScene":
                self.send({"op": 5, "d": {"eventType": "CurrentProgramSceneChanged", "eventIntent": 4,
                                          "eventData": {"sceneName": self.program}}})


def wait_for(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_connect_auth_request_and_event():
    srv = FakeOBSServer()
    events = []
    c = obs_ws.OBSClient("127.0.0.1", srv.port, PASSWORD, on_event=lambda t, d: events.append((t, d)),
                         log=lambda m: None).start()
    try:
        assert wait_for(lambda: c.connected)
        assert c.request("GetCurrentProgramScene")["sceneName"] == "Camera Left"
        c.request("SetCurrentProgramScene", {"sceneName": "Full Board"})
        assert srv.program == "Full Board"
        assert wait_for(lambda: events)
        assert events[0] == ("CurrentProgramSceneChanged", {"sceneName": "Full Board"})
    finally:
        c.stop()


def test_wrong_password_reported():
    srv = FakeOBSServer()
    c = obs_ws.OBSClient("127.0.0.1", srv.port, "wrong", log=lambda m: None, retry_s=60).start()
    try:
        assert wait_for(lambda: "password" in c.error), c.error
        assert not c.connected
    finally:
        c.stop()


def test_no_obs_running():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    c = obs_ws.OBSClient("127.0.0.1", port, log=lambda m: None, retry_s=60).start()
    try:
        assert wait_for(lambda: "OBS" in c.error, timeout=12)   # Windows takes ~2 s to refuse
        assert not c.connected
    finally:
        c.stop()


def test_large_frame_roundtrip():
    a, b = socket.socketpair()
    payload = "x" * 70000
    a.sendall(obs_ws.ws_encode(payload))
    op, data = obs_ws.ws_read(b)
    assert op == 1 and data.decode() == payload
