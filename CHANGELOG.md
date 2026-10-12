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
- `record_test.bat`: run the receiver and save the radio signal to a timestamped recording.
- Fix: replaying a `.sr` capture could split a burst in two and log a message twice.
- `--version` option, tests, and CI on Windows and Linux.
