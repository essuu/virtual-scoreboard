# ECS scoreboard radio protocol

Reverse-engineered in October 2026 from an ECS Electronic Cricket Scoreboards controller. The
captures were taken with a logic analyser on the transmitter's data pin and confirmed over the air
with an RTL-SDR.

## Hardware

- Controller: a 40-pin PIC microcontroller at 5 V.
- Transmitter: **Radiometrix TX2-433-40-5V** FM module, 433.92 MHz. The controller only powers the TX2
  while it is sending, so the carrier appears just for the length of a burst.
- The controller's wired serial outputs aren't populated on the board examined, so radio is the
  only usable interface.

## Physical layer

| | |
|---|---|
| Frequency | 433.92 MHz, FM (binary FSK via the TX2's data input) |
| Line code | Manchester, half-bit ≈ 531 µs (≈ 940 bit/s) |
| Idle level | TXD low |

## Burst structure

```
[preamble: 20 × "10"] [frame] [frame] … [frame]        (10 identical frames)
```

Each frame:

```
sync:  4 half-bits high, then 1 half-bit low
data:  32 bits, Manchester, MSB first.  At the TXD pin "01" = 1 and "10" = 0
gap:   a short low gap before the next frame
```

A receiver should take a majority vote across the copies. This one accepts a message when
at least two frames agree.

## Frame payload

32 bits = 4 groups of 8 bits:

```
 7   6   5   4   3   2   1   0
[ group index ][  BCD digit  ][spare]
```

| Group index | Digit meaning |
|---|---|
| 3 | field ID (0–15, all in use) |
| 2 | hundreds |
| 1 | tens |
| 0 | units |

- Digit `0xF` means **blank**. The controller suppresses leading zeros, so 55 is sent as
  `blank, 5, 5`, and a cleared field is sent as `blank, blank, blank`.
- The group indexes are always 3, 2, 1, 0, which makes a good validity check.
- The spare bit is 0 in groups 3–1. In group 0 it copies the units digit's lowest bit, and its
  purpose is unknown. Ignore it.

Example: total = 55 → field 5, digits `F 5 5`:
`011 0101 0 | 010 1111 0 | 001 0101 0 | 000 0101 1`

## Fields

Fields 0–13 match the "category" numbers in ECS's PCS Pro software config (names in brackets),
and the console's Category key uses the same numbers. PCS Pro lists 14 as `DlsParScore` and has no
15, but the ECS console has no DLS par; it uses 14 and 15 for the bowler numbers.

| ID | Field | Notes |
|---|---|---|
| 0 | Umpire light (`UmpireLight`) | received live; on/off values to be documented |
| 1 | Left-hand batter number | blanked when the batter is out |
| 2 | Right-hand batter number | |
| 3 | Left-hand batter runs | |
| 4 | Right-hand batter runs | |
| 5 | Total | |
| 6 | Wickets | |
| 7 | Overs | |
| 8 | Extras | |
| 9 | Last batter's score | |
| 10 | Total at last wicket | |
| 11 | First-innings total | set at the end of the innings |
| 12 | Runs required to win (`RunsRequiredToWin`) | first-innings total + 1 at the end of the 1st innings; counts down in the 2nd |
| 13 | Overs remaining (`OversRemaining`) | blank in the 1st innings |
| 14 | Bowler 1 number | confirmed over the air (bowler 1 = 8, bowler 2 = 9, 12 Oct 2026); set from the console's bowler-number config option. PCS Pro calls this field `DlsParScore` |
| 15 | Bowler 2 number | not in the PCS Pro list |

## Behaviour

- **One burst per changed field.** For example, a run to a batter sends that batter's runs and then
  the total, about 0.9 s apart.
- Values are **absolute**, not increments. The controller waits briefly after key presses and sends
  only the latest value, so quick presses are batched together.
- **End of innings** sends every field 1–14 in order, about 0.9 s apart. Fields 1–10 are blank,
  11 and 12 are set.

## Still to confirm

- The umpire light's (field 0) on/off values still need writing down.
- Whether the end-of-innings refresh also sends field 15 (the one capture of it stops during 14).
- In one capture, a total entered as 994 was sent as 996.
