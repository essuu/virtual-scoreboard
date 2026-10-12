# Virtual Scoreboard

A live cricket scoreboard for OBS, fed straight from the radio link of an **ECS Electronic Cricket
Scoreboards** controller.

An RTL-SDR dongle listens to the controller's 433.92 MHz transmissions. `ecs_receiver.py` decodes them
and serves a scoreboard page that OBS shows as a Browser Source. Nothing is connected to the
controller, and the physical scoreboard works as normal.

```
ECS controller ──433.92 MHz──▶ RTL-SDR ──▶ ecs_receiver.py ──http://127.0.0.1:8765/──▶ OBS
```

## What you need

- An ECS scoreboard controller (Radiometrix TX2 433 MHz transmitter inside).
- An RTL-SDR dongle. Tested with the **RTL-SDR Blog V4**.
- A Windows PC with OBS. The receiver is plain Python and should also run on Linux and macOS with
  the `rtl_sdr` tool from your package manager, but only Windows has been tested.

## One-time setup (Windows)

1. **Python 3.10 or later** from python.org. On the first installer screen, tick **"Add python.exe to PATH"**.
2. **Download this project**: either `git clone https://github.com/essuu/virtual-scoreboard.git`,
   or download the zip from the Releases page and unzip it.
3. **Install numpy**: open Command Prompt in the project folder and run
   `pip install -r requirements.txt`
4. **RTL-SDR tools**: download `Release.zip` from the
   [RTL-SDR Blog releases](https://github.com/rtlsdrblog/rtl-sdr-blog/releases) (v1.3.4 or later is
   needed for the V4). From its `x64` folder, copy `rtl_sdr.exe` and all the `.dll` files into the
   `receiver` folder. (They aren't included here.)
5. **USB driver**: if SDR#, SDR++ or similar already works with the dongle, skip this step.
   Otherwise run [Zadig](https://zadig.akeo.ie), choose *Options > List All Devices*, pick
   "Bulk-In, Interface (Interface 0)", select **WinUSB** and click *Replace Driver*.

## Every match

1. Plug in the RTL-SDR with its antenna. For the supplied dipole, extend each element to about 16 cm.
2. Double-click **`receiver\start_receiver.bat`** and leave the window open.
3. In OBS: *Sources > + > Browser*, URL `http://127.0.0.1:8765/`, width 1920, height 1080.
4. Open `http://127.0.0.1:8765/status` in a browser to check messages are arriving.

The receiver remembers the last values if it is restarted. To start a new match, use the
**Clear scoreboard** button on the status page. (The controller also blanks most fields at the end
of an innings.)

## Scoreboard layouts (add to the OBS URL)

| Option | Effect |
|---|---|
| *(none)* | score bar along the bottom of the screen |
| `?layout=board` | compact full scoreboard panel |
| `?layout=classic` | laid out like a traditional ground scoreboard, with the umpire light beside the title |
| `?layout=classicboard` | full-board tiles, arranged like the ground scoreboard, with the umpire light beside the title |
| `&title=Home%20CC` | text in the title cell (hidden if not set) |
| `&scale=1.3` | bigger or smaller |
| `&pos=top` | score bar at the top of the screen |
| `&bg=1` | solid background (handy for previewing in a browser) |

Example: `http://127.0.0.1:8765/?layout=classicboard&title=Home%20CC&scale=1.2`

## Receiver options

Add these after `python ecs_receiver.py` in `start_receiver.bat`.

| Option | Use |
|---|---|
| `--gain 30` | fixed RTL-SDR gain if auto gain struggles (try 20–40; go lower if the controller is very close) |
| `--device 1` | which RTL-SDR to use if more than one is plugged in |
| `--ppm N` | frequency correction (rarely needed: the receiver finds the carrier itself within ±300 kHz) |
| `--freq 433.92e6` | transmitter frequency in Hz |
| `--port 8090` | use a different web port |
| `--lan` | let other computers on the network open the pages (Windows will ask about the firewall) |
| `--record test.cu8` | also save the raw radio signal, for troubleshooting |
| `--iq FILE.cu8` | decode a saved radio recording instead of the live radio |
| `--sr FILE.sr --realtime` | replay a PulseView logic capture (no radio needed) |
| `--version` | show the version |

Run `python ecs_receiver.py --help` for the full list.

## Web endpoints

| Path | Returns |
|---|---|
| `/` | the scoreboard page (OBS) |
| `/status` | status page: signal level, recent messages, *Clear scoreboard* |
| `/state` | current values as JSON |
| `/events` | server-sent events stream of every update |
| `POST /reset` | clears all values |

## Recording a test session

`receiver\record_test.bat` runs the receiver as usual, opens the status page, and also saves the raw
radio signal to `receiver\recordings\test_<date>_<time>.cu8` (about 2 MB a second). The status page
shows every message with its field number, including field numbers the receiver doesn't know yet.
To decode a recording again later: `python ecs_receiver.py --iq recordings\test_….cu8 --no-server`.

## Testing without the radio

`receiver\test_replay.bat` replays one of the logic-analyser recordings in `captures/` in real time
and opens the status page.

To run the automated tests:

```
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

The tests replay every capture through the decoder and check each message. They also push
simulated FM radio signals (including off-frequency ones) through the radio decoder and check the
web server.

## Project layout

```
receiver/   ecs_receiver.py   radio receiver, decoder and web server
            ecs_protocol.py   the ECS message format
            scoreboard.html   OBS scoreboard page
            status.html       status page
            *.bat             Windows launchers
tools/      ecs_decode.py     command-line decoder for PulseView .sr captures
captures/                     logic-analyser recordings of the controller's TX2 data pin
docs/       PROTOCOL.md       how the radio protocol works
tests/                        pytest suite
```

## How it works

[docs/PROTOCOL.md](docs/PROTOCOL.md) describes the reverse-engineered radio protocol: Manchester-coded
FM at about 940 bit/s, carrying one 32-bit frame per changed field, repeated 10 times.

## Disclaimer

This is an independent project. It is not affiliated with or endorsed by ECS or Radiometrix.
It only receives; it never transmits.

## Licence

MIT. See [LICENSE](LICENSE).
