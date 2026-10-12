"""Minimal OBS WebSocket (protocol v5, built into OBS 28+) client using only the standard library.

Only what the director needs: connect (with or without a password), send requests, and receive
events. It reconnects by itself, so OBS can be started before or after the receiver.
"""
import base64, hashlib, json, os, queue, socket, struct, threading, time, uuid

EVENT_SCENES = 1 << 2          # obs-websocket EventSubscription.Scenes


# ----------------------------------------------------------------------------- websocket framing
def ws_accept_key(key):
    return base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode())
                            .digest()).decode()


def ws_encode(payload, opcode=1, mask=True):
    """One complete websocket frame. Clients must mask; servers must not."""
    if isinstance(payload, str):
        payload = payload.encode()
    head = bytes([0x80 | opcode])
    n = len(payload)
    mbit = 0x80 if mask else 0
    if n < 126:
        head += bytes([mbit | n])
    elif n < 65536:
        head += bytes([mbit | 126]) + struct.pack(">H", n)
    else:
        head += bytes([mbit | 127]) + struct.pack(">Q", n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return buf


class _Buffered:
    """A socket with some bytes already read (OBS may send its Hello in the same packet as the
    handshake reply)."""

    def __init__(self, sock, pending=b""):
        self.sock, self.pending = sock, pending

    def recv(self, n):
        if self.pending:
            out, self.pending = self.pending[:n], self.pending[n:]
            return out
        return self.sock.recv(n)

    def sendall(self, data):
        return self.sock.sendall(data)

    def close(self):
        return self.sock.close()


def ws_read(sock):
    """Read one message. Returns (opcode, payload bytes); fragments are joined."""
    parts, first_op = [], None
    while True:
        b0, b1 = _recv_exact(sock, 2)
        fin, op = b0 & 0x80, b0 & 0x0F
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", _recv_exact(sock, 2))[0]
        elif n == 127:
            n = struct.unpack(">Q", _recv_exact(sock, 8))[0]
        key = _recv_exact(sock, 4) if b1 & 0x80 else None
        data = _recv_exact(sock, n)
        if key:
            data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
        if op >= 8:                      # control frames can arrive between fragments
            return op, data
        if first_op is None:
            first_op = op
        parts.append(data)
        if fin:
            return first_op, b"".join(parts)


def auth_string(password, salt, challenge):
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


# ----------------------------------------------------------------------------- client
class OBSError(Exception):
    pass


class OBSClient:
    """Keeps a connection to OBS open in the background.

    on_event(event_type, data) and on_connect() run on a separate thread from the socket reader,
    so they may call request() without deadlocking."""

    def __init__(self, host="127.0.0.1", port=4455, password="", on_event=None, on_connect=None,
                 retry_s=3.0, log=print):
        self.host, self.port, self.password = host, port, password or ""
        self.on_event, self.on_connect = on_event, on_connect
        self.retry_s = retry_s
        self.log = log
        self.connected = False
        self.error = "not connected yet"
        self.version = ""
        self._sock = None
        self._send_lock = threading.Lock()
        self._pending = {}
        self._events = queue.Queue()
        self._stop = threading.Event()
        self._logged_error = None

    # -- public
    def start(self):
        threading.Thread(target=self._run, daemon=True, name="obs-ws").start()
        threading.Thread(target=self._dispatch, daemon=True, name="obs-events").start()
        return self

    def stop(self):
        self._stop.set()
        self._close()

    def request(self, request_type, data=None, timeout=3.0):
        if not self.connected:
            raise OBSError("OBS not connected (%s)" % self.error)
        rid = uuid.uuid4().hex
        slot = {"ev": threading.Event(), "resp": None}
        self._pending[rid] = slot
        try:
            msg = {"op": 6, "d": {"requestType": request_type, "requestId": rid}}
            if data is not None:
                msg["d"]["requestData"] = data
            self._send(msg)
            if not slot["ev"].wait(timeout):
                raise OBSError("OBS did not answer %s" % request_type)
        finally:
            self._pending.pop(rid, None)
        resp = slot["resp"]
        if resp is None:
            raise OBSError("connection lost during %s" % request_type)
        st = resp.get("requestStatus", {})
        if not st.get("result"):
            raise OBSError("%s failed: %s" % (request_type, st.get("comment") or st.get("code")))
        return resp.get("responseData") or {}

    # -- internals
    def _send(self, obj):
        with self._send_lock:
            if self._sock is None:
                raise OBSError("OBS not connected")
            self._sock.sendall(ws_encode(json.dumps(obj)))

    def _close(self):
        s, self._sock = self._sock, None
        self.connected = False
        if s:
            try:
                s.close()
            except OSError:
                pass
        for slot in list(self._pending.values()):     # wake anyone waiting
            slot["ev"].set()

    def _note_error(self, msg):
        self.error = msg
        if msg != self._logged_error:                  # don't repeat the same complaint every 3 s
            self.log("OBS: %s" % msg)
            self._logged_error = msg

    def _run(self):
        while not self._stop.is_set():
            try:
                self._session()
            except Exception as e:
                text = str(e) or e.__class__.__name__
                if isinstance(e, (ConnectionRefusedError, socket.timeout, TimeoutError)) or "refused" in text:
                    text = "can't reach OBS at %s:%d - is OBS running with its WebSocket server on?" % (
                        self.host, self.port)
                self._note_error(text)
            was = self.connected
            self._close()
            if was:
                self.log("OBS: disconnected")
            self._stop.wait(self.retry_s)

    def _session(self):
        sock = socket.create_connection((self.host, self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(("GET / HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
                      "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n" % (self.host, self.port, key)).encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("OBS closed the connection during the handshake")
            resp += chunk
        head, rest = resp.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError("OBS refused the WebSocket upgrade: %s" % head.split(b"\r\n")[0].decode(errors="replace"))
        sock.settimeout(None)
        sock = _Buffered(sock, rest)
        self._sock = sock

        op, data = ws_read(sock)
        hello = json.loads(data)
        if hello.get("op") != 0:
            raise ConnectionError("expected Hello from OBS")
        hd = hello["d"]
        ident = {"rpcVersion": 1, "eventSubscriptions": EVENT_SCENES}
        if "authentication" in hd:
            if not self.password:
                raise ConnectionError("OBS wants a password: add --obs-password ... (OBS: Tools > "
                                      "WebSocket Server Settings > Show Connect Info)")
            a = hd["authentication"]
            ident["authentication"] = auth_string(self.password, a["salt"], a["challenge"])
        self._send({"op": 1, "d": ident})
        while True:
            op, data = ws_read(sock)
            if op == 8:
                code = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 0
                if code == 4009:
                    raise ConnectionError("OBS rejected the password (check --obs-password)")
                raise ConnectionError("OBS closed the connection (code %d %s)" % (code, data[2:].decode(errors="replace")))
            if op == 9:
                with self._send_lock:
                    sock.sendall(ws_encode(data, opcode=10))
                continue
            if op != 1:
                continue
            msg = json.loads(data)
            if msg.get("op") == 2:
                break
        self.version = hd.get("obsWebSocketVersion", "")
        self.connected = True
        self.error = ""
        self._logged_error = None
        self.log("OBS: connected (obs-websocket %s)" % self.version)
        self._events.put(("__connected__", None))

        while True:
            op, data = ws_read(sock)
            if op == 8:
                raise ConnectionError("OBS closed the connection")
            if op == 9:
                with self._send_lock:
                    sock.sendall(ws_encode(data, opcode=10))
                continue
            if op != 1:
                continue
            msg = json.loads(data)
            if msg.get("op") == 7:
                slot = self._pending.get(msg["d"].get("requestId"))
                if slot:
                    slot["resp"] = msg["d"]
                    slot["ev"].set()
            elif msg.get("op") == 5:
                self._events.put((msg["d"].get("eventType"), msg["d"].get("eventData") or {}))

    def _dispatch(self):
        while not self._stop.is_set():
            try:
                etype, data = self._events.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if etype == "__connected__":
                    if self.on_connect:
                        self.on_connect()
                elif self.on_event:
                    self.on_event(etype, data)
            except Exception as e:
                self.log("OBS: error handling %s: %s" % (etype, e))
