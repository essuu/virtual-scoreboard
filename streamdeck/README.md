# Stream Deck Mini set-up

Every key is Stream Deck's built-in **Website** action pointed at the receiver, with
**"GET request in background"** ticked so no browser window opens. No plugins are needed.
Key images are in [`icons/`](icons) (drag a PNG onto the key's icon in the Stream Deck app).

The receiver must be running on the same PC (`http://127.0.0.1:8765`). If you changed the port
with `--port`, use that number instead.

## Quick set-up: import the ready-made profile

[`Virtual-Scoreboard-Mini.streamDeckProfile`](Virtual-Scoreboard-Mini.streamDeckProfile) has the
whole layout below (main page, Setup and Breaks folders) with every URL and icon already in place.

1. Install the Elgato Stream Deck app and plug in the Stream Deck Mini. The profile was exported
   from Stream Deck 7.6; older versions may not open it.
2. Double-click the `.streamDeckProfile` file. Stream Deck adds a profile called **OBS Automation**.
3. Choose **OBS Automation** in the profile list at the top of the Stream Deck window.

The profile is linked to OBS (`C:\Program Files\obs-studio\bin\64bit\obs64.exe`), so Stream Deck
switches to it whenever OBS is the window in front. To choose it by hand instead, remove the linked
app in the profile's settings.

It was made on a Stream Deck **Mini** (6 keys). On a bigger Stream Deck it imports, but you'll need
to rearrange the keys. If your receiver uses a different port, or your OBS break scenes have
different names, edit those keys' URLs after importing.

To build it yourself instead, follow the tables below.

## Main page

| | | |
|---|---|---|
| **Left end bowling** `left_end.png`<br>`http://127.0.0.1:8765/api/left` | **Board** `board.png`<br>`http://127.0.0.1:8765/api/board` | **Right end bowling** `right_end.png`<br>`http://127.0.0.1:8765/api/right` |
| **Setup** folder `setup.png` | **Live** `live.png`<br>`http://127.0.0.1:8765/api/live` | **Breaks** folder `breaks.png` |

## Setup folder (before the first ball)

Stream Deck puts its own *back* key in the top-left of a folder.

| | | |
|---|---|---|
| *(back)* | **Home bat first** `home_first.png`<br>`http://127.0.0.1:8765/api/home-first` | **Away bat first** `away_first.png`<br>`http://127.0.0.1:8765/api/away-first` |
| **Swap ends** `swap_ends.png`<br>`http://127.0.0.1:8765/api/swap` | **Auto on/off** `auto.png`<br>`http://127.0.0.1:8765/api/auto` | *(spare)* |

## Breaks folder

| | | |
|---|---|---|
| *(back)* | **Starting soon** `starting_soon.png`<br>`http://127.0.0.1:8765/api/scene?name=Starting%20Soon` | **Drinks / tea** `break_scene.png`<br>`http://127.0.0.1:8765/api/scene?name=Break` |
| **Technical** `technical.png`<br>`http://127.0.0.1:8765/api/scene?name=Technical%20Difficulties` | **Board (hold)** `board.png`<br>`http://127.0.0.1:8765/api/board?hold=1` | **Live** `live.png`<br>`http://127.0.0.1:8765/api/live` |

Scene names in the URL must match OBS exactly; a space is written `%20`. The receiver's OBS
set-up creates these three scenes, each with a holding picture in the scoreboard's style (see the
main README); put your own picture in one instead and it's left alone.

## What each key does

| Key | Effect |
|---|---|
| Left / Right end bowling | "This end is bowling **now**." Cuts to that camera and sets the ends for the rest of the innings. Press it before the first ball of each innings. Pressing it later also corrects the ends if they've got out of step. |
| Board | Full-board scene for 6 s (`--board-seconds`), then back to the bowling-end camera. |
| Board (hold) | Full-board scene until you press another key. |
| Live | Back to the bowling-end camera (after a break, or after a manual cut). |
| Home / Away bat first | Sets who batted first; the scoreboard shows "Home batting" or "Away batting" and swaps it automatically in the second innings. |
| Swap ends | Swaps left and right if the cameras have been following the wrong end. |
| Auto on/off | Stops (or restarts) all automatic switching. Manual keys still work. |
| Scene keys | Cut to that scene. Automatic switching leaves non-camera scenes alone until you press Live. |

## Match routine

1. Start the receiver, then OBS. The status page (`/status`) shows "OBS connected".
2. New match: **Clear scoreboard** on the status page (this also clears the batting side and ends).
3. *Setup → Home / Away bat first.*
4. When the first over starts: **Left end** or **Right end**.
5. From then on the cameras swap each over and the board appears after each wicket by themselves.
6. At the end of the innings the board comes up and stays. When the second innings starts,
   press **Left end** or **Right end** again.

## Trying it at home (no cameras)

On the status page press **Add test cameras**. Each camera scene gets a test card under the score
bar: blue **LEFT END** or amber **RIGHT END**, with a running clock so you
can see it's live. Press the Stream Deck keys and watch which card goes on air. Score changes come
from the controller as normal, or replay a capture with `test_replay.bat`. **Remove test cameras**
takes them out again before match day (they'd sit hidden under the real camera otherwise).
