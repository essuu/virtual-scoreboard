# Changelog

## 1.0.0 (unreleased)

First public release.

- RTL-SDR receiver for the ECS controller's 433.92 MHz link. It finds the carrier automatically
  within ±300 kHz.
- OBS scoreboard page with four layouts (bar, board, classic, classicboard) and a status page.
- Live updates via server-sent events. The last values are saved across restarts.
- Replay of `.cu8` IQ recordings and PulseView `.sr` logic captures.
- Field names follow ECS's PCS Pro category list: 12 is runs required, 13 is overs remaining,
  14 is DLS par score (never set by the ECS console), and 0 is the umpire light. Earlier builds
  guessed target, DLS par and runs remaining for 12–14.
- Unknown field IDs (e.g. 15) are kept and shown on the status page with their number instead of being
  dropped. The status page and console now show each message's field number.
- Fields 14 and 15 are bowler 1 and bowler 2 numbers on the ECS console (confirmed live). PCS Pro's
  DLS par isn't used.
- Faster updates: a message is shown as soon as two matching copies arrive (about 0.1 s after the
  burst starts instead of about 0.43 s), then confirmed when the burst ends.
- Umpire light (field 0) shown as a circle to the right of the title on the classic and
  classicboard layouts, lit in the number colour while the light key is held (centred in the
  header if there's no title).
- The board, classic and classicboard layouts scale to fit the window or OBS browser source and
  re-fit on resize, so nothing is cut off. `&scale` is now a fraction of the window for these;
  `&fit=0` restores the fixed size. The score bar shrinks if it's wider than the window.
- `record_test.bat`: run the receiver and save the radio signal to a timestamped recording.
- Fix: replaying a `.sr` capture could split a burst in two and log a message twice.
- `--version` option, tests, and CI on Windows and Linux.
- Automatic OBS cameras: cuts to the camera at the bowling end each over, shows the full board for
  10 s after a wicket and holds it at the end of an innings. Uses OBS's built-in WebSocket server
  (no extra Python packages). Leaves break scenes alone until "Back to play".
- OBS scene set-up on connect: the score bar is added on top of both camera scenes (one shared
  "Score Overlay" scene) and kept above a camera feed added later; the Full Board scene gets the
  classicboard scoreboard; missing scenes are created. Only adds what's missing, never edits.
  "Set up OBS scenes" button, `--bar-options`, `--board-options`, `--no-obs-setup`.
- Match controls for a Stream Deck or the status page: which end is bowling now, swap ends, who
  batted first, auto on/off, board, back to play, any scene. Stream Deck Mini layout and key
  images in `streamdeck/`.
- Batting side ("Home batting" / "Away batting", or names with `&home=` / `&away=`) on every
  layout, swapped automatically for the second innings. Classicboard shows BATTING – HOME in the
  top bar after the umpire light; classic shows BATTING over HOME/AWAY at the bottom of the middle
  column.
- Test cameras for trying the switching at home: `/testcard?end=left|right` is a moving, clearly
  labelled stand-in picture (blue LEFT END / amber RIGHT END, live clock). **Add test cameras** on
  the status page (or `/api/test-cameras?on=1`) puts one at the bottom of each camera scene;
  **Remove test cameras** (`?on=0`) takes them out again.
