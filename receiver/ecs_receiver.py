"""ECS cricket scoreboard receiver -> live OBS scoreboard.

Sources
  (default)        RTL-SDR via rtl_sdr.exe (RTL-SDR Blog build, V4 compatible), piped raw IQ
  --iq FILE.cu8    replay a raw unsigned-8-bit IQ recording (same rate/offset settings)
  --sr FILE.sr     replay a PulseView logic capture of the TX2 data pin (no radio needed)

Then open http://localhost:8765/ in OBS as a Browser Source.
"""
import argparse, json, os, queue, subprocess, sys, threading, time, zipfile, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import numpy as np

import ecs_protocol as proto
from director import Director
from obs_ws import OBSClient

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
MATCH_FILE = os.path.join(HERE, "match.json")      # batting side, bowling end, auto on/off


# ----------------------------------------------------------------------------- state
class Scoreboard:
    def __init__(self):
        self.lock = threading.Lock()
        self.values = {name: "" for name in proto.FIELDS.values()}
        self.updated = 0.0
        self.log = []          # recent messages for the status page
        self.listeners = []    # queues for server-sent events
        self.stats = {"bursts": 0, "frames_ok": 0, "last_level_db": None, "noise_db": None,
                      "source": "", "started": time.time()}
        self._load()

    def _load(self):
        try:
            with open(STATE_FILE) as f:
                saved = json.load(f)
            self.values.update({k: v for k, v in saved.get("values", {}).items()
                                if k in self.values or k.startswith("field_")})
            self.updated = saved.get("updated", 0.0)
        except Exception:
            pass

    def _save(self):
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"values": self.values, "updated": self.updated}, f)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            print("warning: could not save state:", e)

    def _snap(self):
        # call with self.lock held
        return {"values": dict(self.values), "updated": self.updated, "match": DIRECTOR.match_info()}

    def snapshot(self):
        with self.lock:
            return self._snap()

    def broadcast(self):
        """Push the current state to every open scoreboard (e.g. after the match settings change)."""
        with self.lock:
            snap = self._snap()
            for q in list(self.listeners):
                try:
                    q.put_nowait(snap)
                except queue.Full:
                    pass

    def apply(self, field, value, copies, level_db=None):
        name = proto.field_name(field)
        now = time.time()
        with self.lock:
            old = self.values.get(name)
            changed = old != value
            self.values[name] = value
            self.updated = now
            self.stats["frames_ok"] += copies
            entry = {"t": now, "field": field, "label": proto.field_label(field),
                     "value": value, "copies": copies, "level_db": level_db}
            self.log.append(entry)
            self.log = self.log[-200:]
            self._save()
            snap = self._snap()
            for q in list(self.listeners):
                try:
                    q.put_nowait(snap)
                except queue.Full:
                    pass
        lvl = "" if level_db is None else "  level %.0f dB" % level_db
        print("%s  %2d %-32s = %-4s (%d/10 copies)%s%s" % (
            time.strftime("%H:%M:%S"), field, proto.field_label(field), value if value else "(blank)",
            copies, lvl, "" if changed else "  [repeat]"), flush=True)
        if changed:
            DIRECTOR.notify(name, old, value)       # outside our lock: it may talk to OBS
        return entry

    def confirm(self, entry, copies):
        """A value applied early (from the first copies of a burst) is confirmed by the whole
        burst: record the final copy count without logging the message again."""
        with self.lock:
            self.stats["frames_ok"] += max(0, copies - entry["copies"])
            entry["copies"] = copies

    def reset(self):
        """Clear every value and the match settings (batting side, bowling end) for a new match."""
        with self.lock:
            for k in self.values:
                self.values[k] = ""
            self.updated = time.time()
            self._save()
        DIRECTOR.sync(self.values)
        DIRECTOR.reset_match()          # also broadcasts the cleared board


DIRECTOR = Director(state_file=MATCH_FILE)
BOARD = Scoreboard()
DIRECTOR.sync(BOARD.values)
DIRECTOR.on_change = lambda: BOARD.broadcast()


# ----------------------------------------------------------------------------- radio DSP
class RadioDecoder:
    """uint8 IQ at fs, signal near +offset Hz -> bursts -> FM demod -> sliced bits -> frames.

    Burst detection scans the spectrum every 1 ms (64 kHz-wide bands) so the carrier is found
    wherever it is within +/-search Hz of the expected frequency. Each burst is then mixed to
    0 Hz at its measured carrier, filtered, FM-demodulated, sliced with its own threshold and
    decoded in both polarities."""

    NFFT = 1024

    def __init__(self, fs, offset, squelch_db=6.0, search=300e3):
        self.fs = fs
        self.offset = offset
        self.squelch_db = squelch_db
        self.phase = 0.0
        n = self.NFFT
        self.freqs = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
        bw_bins = max(4, int(round(64e3 / (fs / n))))
        self.kernel = np.ones(bw_bins) / bw_bins
        self.search_mask = np.abs(self.freqs) <= search
        self.window = np.hanning(n).astype(np.float32)
        self.noise = None
        self.noise_n = 0
        self.carry = np.zeros(0, np.complex64)
        self.raw_carry = np.zeros(0, np.uint8)
        self.in_burst = False
        self.quiet = 0
        self.burst_iq = []
        self.burst_spec = []
        self.burst_excess = []
        self.burst_early = None    # (field, value, log entry) applied before the burst ended
        self.burst_t0 = 0          # block count at burst start (1 block = NFFT samples)
        self.blocks = 0
        self.last_early_ms = None  # burst start -> early update, for tests and the status page
        # demod chain
        self.dec1 = max(1, int(round(fs / 256000)))
        self.fs1 = fs / self.dec1
        self.dec2 = 8
        self.fs2 = self.fs1 / self.dec2
        self.lpf = self._design_lpf(80e3, fs, 95)

    @staticmethod
    def _design_lpf(cutoff, fs, taps):
        m = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(2 * cutoff / fs * m) * np.hamming(taps)
        return (h / h.sum()).astype(np.float32)

    def _band(self, spec):
        """64 kHz moving-average across frequency (rows = blocks), centred."""
        k = self.kernel.size
        c = np.cumsum(np.pad(spec, ((0, 0), (k // 2 + 1, k - k // 2 - 1)), mode="edge"), axis=1)
        return (c[:, k:] - c[:, :-k]) / k

    def feed(self, raw):
        # reads from the pipe can split an I/Q pair; keep any odd byte for next time
        if self.raw_carry.size:
            raw = np.concatenate((self.raw_carry, raw))
        if raw.size % 2:
            self.raw_carry = raw[-1:].copy()
            raw = raw[:-1]
        else:
            self.raw_carry = np.zeros(0, np.uint8)
        iq = (raw.astype(np.float32) - 127.4) / 128.0
        x = iq[0::2] + 1j * iq[1::2]
        n = x.size
        if n == 0:
            return
        w = -2 * np.pi * self.offset / self.fs
        ph = self.phase + w * np.arange(n)
        self.phase = float((self.phase + w * n) % (2 * np.pi))
        x = (x * np.exp(1j * ph)).astype(np.complex64)
        x = np.concatenate((self.carry, x))
        nb = x.size // self.NFFT
        self.carry = x[nb * self.NFFT:]
        if nb == 0:
            return
        blocks = x[:nb * self.NFFT].reshape(nb, self.NFFT)
        spec = np.fft.fftshift(np.abs(np.fft.fft(blocks * self.window, axis=1)) ** 2, axes=1)
        band = self._band(spec)
        for k in range(nb):
            self._block(blocks[k], spec[k], band[k])

    def _block(self, blk, spec, band):
        self.blocks += 1
        if self.noise is None or self.noise_n < 50:
            # learn the noise floor during the first 50 ms
            self.noise = band.copy() if self.noise is None else self.noise * 0.9 + band * 0.1
            self.noise_n += 1
            return
        ratio = band[self.search_mask] / (self.noise[self.search_mask] + 1e-20)
        excess_db = 10 * np.log10(ratio.max() + 1e-20)
        active = excess_db > self.squelch_db
        if active:
            if not self.in_burst:
                self.in_burst = True
                self.burst_iq, self.burst_spec, self.burst_excess = [], [], []
                self.burst_early = None
                self.burst_t0 = self.blocks
            self.quiet = 0
        elif self.in_burst:
            self.quiet += 1
        if self.in_burst:
            self.burst_iq.append(blk)
            if active:
                self.burst_spec.append(spec)
                self.burst_excess.append(excess_db)
            # Early update: the controller sends each message 10 times (~0.41 s), but 2 matching
            # copies are enough, and they are in after ~0.1 s. Try every ~10 ms from 60 ms on
            # until something decodes, so the scoreboard (and the umpire light) updates sooner.
            n = len(self.burst_spec)
            if active and self.burst_early is None and n >= 60 and n % 10 == 0:
                self._try_early()
            if self.quiet >= 15:
                self.in_burst = False
                self._decode_burst()
        else:
            self.noise = self.noise * 0.995 + band * 0.005
        BOARD.stats["noise_db"] = round(float(10 * np.log10(np.median(self.noise) + 1e-20)), 1)

    def _try_early(self):
        snr = float(np.median(self.burst_excess))
        best = self._demod()
        if len(best) == 1:
            field, value, copies = best[0]
            entry = BOARD.apply(field, value, copies, level_db=round(snr, 1))
            self.burst_early = (field, value, entry)
            self.last_early_ms = (self.blocks - self.burst_t0 + 1) * self.NFFT * 1000.0 / self.fs
            BOARD.stats["early_ms"] = round(self.last_early_ms)

    def _decode_burst(self):
        if len(self.burst_spec) < 50:            # shorter than 50 ms: not ours
            return
        BOARD.stats["bursts"] += 1
        snr = float(np.median(self.burst_excess))
        BOARD.stats["last_level_db"] = round(snr, 1)
        best = self._demod()
        early = self.burst_early
        for field, value, copies in best:
            if early and (field, value) == early[:2]:
                BOARD.confirm(early[2], copies)
            else:
                BOARD.apply(field, value, copies, level_db=round(snr, 1))

    def _demod(self):
        """Demodulate the burst so far. Returns [(field, value, copies)]."""
        # carrier = power-weighted centroid of the excess spectrum near the peak
        mean_spec = np.mean(self.burst_spec, axis=0)
        excess = np.clip(mean_spec - self.noise, 0, None)
        excess[~self.search_mask] = 0
        sm = np.convolve(excess, self.kernel, mode="same")
        pk = int(np.argmax(sm))
        win = np.abs(self.freqs - self.freqs[pk]) <= 100e3
        fc = float(np.sum(self.freqs[win] * excess[win]) / (np.sum(excess[win]) + 1e-20))
        BOARD.stats["carrier_offset_khz"] = round(fc / 1e3, 1)
        x = np.concatenate(self.burst_iq)
        x = x * np.exp(-2j * np.pi * fc / self.fs * np.arange(x.size)).astype(np.complex64)
        y = np.convolve(x, self.lpf, mode="same")[::self.dec1]
        fm = np.angle(y[1:] * np.conj(y[:-1])).astype(np.float32)
        m = (fm.size // self.dec2) * self.dec2
        s = fm[:m].reshape(-1, self.dec2).mean(axis=1)
        s = np.convolve(s, np.ones(3) / 3, mode="same")
        lo, hi = np.percentile(s, [10, 90])
        bits = (s > (lo + hi) / 2).astype(np.int8)
        best = []
        for lv in (bits, 1 - bits):
            r = proto.decode_levels(lv, self.fs2)
            if len(r) > len(best):
                best = r
        return best


def run_rtl(args):
    tune = int(args.freq - args.offset)
    exe = args.rtl_sdr
    cmd = [exe, "-f", str(tune), "-s", str(args.rate)]
    if args.gain is not None:
        cmd += ["-g", str(args.gain)]
    if args.ppm:
        cmd += ["-p", str(args.ppm)]
    if args.device is not None:
        cmd += ["-d", str(args.device)]
    cmd += ["-"]
    BOARD.stats["source"] = "RTL-SDR %.3f MHz (tuned %.3f), %d S/s, gain %s" % (
        args.freq / 1e6, tune / 1e6, args.rate, args.gain if args.gain is not None else "auto")
    dec = RadioDecoder(args.rate, args.offset, args.squelch)
    rec = open(args.record, "wb") if args.record else None
    while True:
        print("Starting:", " ".join(cmd), flush=True)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=1 << 20)
        except FileNotFoundError:
            print("ERROR: could not run '%s'. Put rtl_sdr.exe (RTL-SDR Blog release) next to this "
                  "script or pass --rtl-sdr PATH." % exe, flush=True)
            time.sleep(10)
            continue
        chunk = args.rate * 2 // 10                 # 100 ms of IQ
        while True:
            data = p.stdout.read(chunk)
            if not data:
                break
            if rec:
                rec.write(data)
            dec.feed(np.frombuffer(data, dtype=np.uint8))
        p.wait()
        print("rtl_sdr stopped (exit %s); restarting in 3 s" % p.returncode, flush=True)
        time.sleep(3)


def run_iq_file(args):
    BOARD.stats["source"] = "IQ file %s" % os.path.basename(args.iq)
    dec = RadioDecoder(args.rate, args.offset, args.squelch)
    chunk = args.rate * 2 // 10
    with open(args.iq, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            dec.feed(np.frombuffer(data, dtype=np.uint8))
            if args.realtime:
                time.sleep(0.1)
    print("IQ file finished.", flush=True)


def run_sr_file(args):
    BOARD.stats["source"] = "Logic capture %s" % os.path.basename(args.sr)
    z = zipfile.ZipFile(args.sr)
    meta = z.read("metadata").decode()
    m = re.search(r"samplerate=([\d.]+) (\w?)Hz", meta)
    fs = float(m.group(1)) * {"": 1, "k": 1e3, "M": 1e6}[m.group(2)]
    names = sorted([n for n in z.namelist() if n.startswith("logic-1-")], key=lambda n: int(n.split("-")[-1]))
    d = np.frombuffer(b"".join(z.read(n) for n in names), dtype=np.uint8) & 1
    # split into bursts so the replay is paced like the real thing
    step = int(fs * 0.5)
    quiet = int(fs * 0.05)          # bursts have gaps of a few ms between frames; 50 ms is clear of them
    pos = 0
    while pos < d.size:
        end = min(d.size, pos + step)
        # extend to the next quiet point so a burst is never cut in half
        while end < d.size and d[max(pos, end - quiet):end].any():
            end = min(d.size, end + quiet // 10)
        for field, value, copies in proto.decode_levels(d[pos:end], fs):
            BOARD.apply(field, value, copies)
        if args.realtime:
            time.sleep((end - pos) / fs)
        pos = end
    print("Logic capture finished.", flush=True)


# ----------------------------------------------------------------------------- web server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _api(self):
        """Match controls for the Stream Deck ("Website" action with "GET request in background")
        and the status page. GET and POST both work."""
        from urllib.parse import urlsplit, parse_qs
        u = urlsplit(self.path)
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        cmd = u.path[len("/api/"):].strip("/")
        try:
            if cmd in ("", "director", "status"):
                pass
            elif cmd == "bowling":
                DIRECTOR.set_bowling(q.get("end", "").lower())
            elif cmd in ("left", "right"):                       # short forms: /api/left, /api/right
                DIRECTOR.set_bowling(cmd)
            elif cmd == "swap":
                DIRECTOR.swap_ends()
            elif cmd == "batting-first":
                t = q.get("team", "").lower()
                DIRECTOR.set_batting_first("" if t in ("", "none", "clear") else t)
            elif cmd in ("home-first", "away-first"):
                DIRECTOR.set_batting_first(cmd.split("-")[0])
            elif cmd == "auto":
                v = q.get("on", "toggle").lower()
                DIRECTOR.set_auto("toggle" if v == "toggle" else v in ("1", "on", "true", "yes"))
            elif cmd == "live":
                DIRECTOR.go_live()
            elif cmd == "scene":
                DIRECTOR.cut_to(q.get("name", ""))
            elif cmd == "board":
                hold = q.get("hold", "") in ("1", "true", "yes")
                secs = float(q["seconds"]) if q.get("seconds") else None
                DIRECTOR.show_board(secs, hold=hold)
            else:
                return self._send(404, json.dumps({"error": "unknown command " + cmd}), "application/json")
        except (ValueError, KeyError) as e:
            return self._send(400, json.dumps({"error": str(e)}), "application/json")
        return self._send(200, json.dumps(DIRECTOR.status()), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api" or path.startswith("/api/"):
            return self._api()
        if path in ("/", "/scoreboard", "/index.html"):
            with open(os.path.join(HERE, "scoreboard.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/status":
            with open(os.path.join(HERE, "status.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/state":
            return self._send(200, json.dumps(BOARD.snapshot()), "application/json")
        if path == "/log":
            with BOARD.lock:
                body = json.dumps({"log": BOARD.log[-60:], "stats": BOARD.stats, "now": time.time()})
            return self._send(200, body, "application/json")
        if path == "/events":
            q = queue.Queue(maxsize=20)
            with BOARD.lock:
                BOARD.listeners.append(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(("data: %s\n\n" % json.dumps(BOARD.snapshot())).encode())
                self.wfile.flush()
                while True:
                    try:
                        snap = q.get(timeout=15)
                        self.wfile.write(("data: %s\n\n" % json.dumps(snap)).encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                with BOARD.lock:
                    if q in BOARD.listeners:
                        BOARD.listeners.remove(q)
            return
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path == "/api" or self.path.startswith("/api/"):
            return self._api()
        if self.path == "/reset":
            BOARD.reset()
            return self._send(200, "ok", "text/plain")
        self._send(404, "not found", "text/plain")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version="%(prog)s " + proto.__version__)
    ap.add_argument("--port", type=int, default=8765, help="web server port (default 8765)")
    ap.add_argument("--freq", type=float, default=433.92e6, help="transmitter frequency in Hz")
    ap.add_argument("--offset", type=float, default=200e3,
                    help="tune this far below the signal to avoid the RTL-SDR centre spike (Hz)")
    ap.add_argument("--rate", type=int, default=1024000, help="RTL-SDR sample rate (S/s)")
    ap.add_argument("--gain", type=float, default=None, help="RTL-SDR gain in dB (default: auto)")
    ap.add_argument("--ppm", type=int, default=0, help="RTL-SDR frequency correction")
    ap.add_argument("--device", type=int, default=None, help="RTL-SDR device index")
    ap.add_argument("--squelch", type=float, default=6.0, help="burst detect threshold above noise (dB)")
    ap.add_argument("--rtl-sdr", default=None, help="path to rtl_sdr.exe")
    ap.add_argument("--record", default=None, help="also save the raw IQ to this .cu8 file")
    ap.add_argument("--iq", help="decode a raw .cu8 IQ recording instead of the live radio")
    ap.add_argument("--sr", help="replay a PulseView .sr logic capture of the TX2 data pin")
    ap.add_argument("--realtime", action="store_true", help="replay files at real speed")
    ap.add_argument("--lan", action="store_true", help="let other computers on the network open the pages")
    ap.add_argument("--no-server", action="store_true", help="decode only, no web server")
    g = ap.add_argument_group("OBS control (automatic camera ends and full board on a wicket)")
    g.add_argument("--no-obs", action="store_true", help="don't connect to OBS")
    g.add_argument("--obs-host", default="127.0.0.1", help="OBS WebSocket host (default 127.0.0.1)")
    g.add_argument("--obs-port", type=int, default=4455, help="OBS WebSocket port (default 4455)")
    g.add_argument("--obs-password", default=os.environ.get("OBS_PASSWORD", ""),
                   help="OBS WebSocket password (or set OBS_PASSWORD)")
    g.add_argument("--scene-left", default="Camera Left", help='scene for the left-end camera (default "Camera Left")')
    g.add_argument("--scene-right", default="Camera Right", help='scene for the right-end camera (default "Camera Right")')
    g.add_argument("--scene-board", default="Full Board", help='full-scoreboard scene (default "Full Board")')
    g.add_argument("--board-seconds", type=float, default=10, help="how long the board stays up after a wicket (default 10)")
    args = ap.parse_args()
    if args.rtl_sdr is None:
        local = os.path.join(HERE, "rtl_sdr.exe")
        args.rtl_sdr = local if os.path.exists(local) else "rtl_sdr"

    DIRECTOR.scenes.update({"left": args.scene_left, "right": args.scene_right, "board": args.scene_board})
    DIRECTOR.board_seconds = args.board_seconds
    if not args.no_obs:
        DIRECTOR.obs = OBSClient(args.obs_host, args.obs_port, args.obs_password,
                                 on_event=DIRECTOR.on_obs_event, on_connect=DIRECTOR.on_obs_connect,
                                 log=lambda m: print(time.strftime("%H:%M:%S"), " ", m, flush=True)).start()
    DIRECTOR.start()

    if not args.no_server:
        class Server(ThreadingHTTPServer):
            allow_reuse_address = False      # on Windows, reuse would let us silently share a busy port
            daemon_threads = True
        try:
            srv = Server(("0.0.0.0" if args.lan else "127.0.0.1", args.port), Handler)
        except OSError as e:
            print("ERROR: port %d is already in use by another program (%s).\n"
                  "Close that program, or start the receiver with a different port, e.g.\n"
                  "    python ecs_receiver.py --port 8090\n"
                  "and use http://127.0.0.1:8090/ instead." % (args.port, e), flush=True)
            sys.exit(1)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("Scoreboard:  http://127.0.0.1:%d/        (add this in OBS as a Browser Source)" % args.port)
        print("Status page: http://127.0.0.1:%d/status" % args.port, flush=True)

    try:
        if args.sr:
            run_sr_file(args)
        elif args.iq:
            run_iq_file(args)
        else:
            run_rtl(args)
        if not args.no_server:
            print("Source finished; web server still running (Ctrl+C to quit).", flush=True)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
