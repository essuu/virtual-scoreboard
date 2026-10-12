# Changelog

## 1.0.0 (unreleased)

First public release.

- RTL-SDR receiver for the ECS controller's 433.92 MHz link. It finds the carrier automatically
  within ±300 kHz.
- OBS scoreboard page with four layouts (bar, board, classic, classicboard) and a status page.
- Live updates via server-sent events. The last values are saved across restarts.
- Replay of `.cu8` IQ recordings and PulseView `.sr` logic captures.
- Fields 13 and 14 are named DLS par score and runs remaining. This is likely but not yet
  confirmed.
- Fix: replaying a `.sr` capture could split a burst in two and log a message twice.
- `--version` option, tests, and CI on Windows and Linux.
