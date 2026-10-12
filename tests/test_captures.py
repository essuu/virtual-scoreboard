"""Replay the real logic-analyser captures through the receiver and check every decoded message."""
import argparse
import os

import pytest

import ecs_receiver
from conftest import CAPTURES

EXPECTED = {
    "4_runs.sr": [(5, "4"), (8, "4")],
    "55_runs.sr": [(5, "55")],
    "1 - 5 runs.sr": [(5, "1"), (8, "1"), (5, "2"), (8, "2"), (5, "3"), (8, "3"), (5, "4"), (8, "4")],
    "10-12_runs.sr": [(5, "10"), (8, "10"), (5, "11"), (8, "11"), (5, "12"), (8, "12")],
    "wicket correction, 2 overs.sr": [(6, "2"), (7, "2"), (7, "3")],
    "set - runs - wicket - runs.sr": [
        (1, "1"), (2, "2"), (3, "1"), (5, "1"), (4, "3"), (5, "4"), (3, "2"), (5, "5"),
        (7, "1"),
        (1, ""), (3, ""), (6, "1"), (9, "2"), (10, "5"),
        (1, "3"), (4, "5"), (5, "7"), (14, ""),
    ],
    # The capture stops part-way through field 14, so only fields up to 13 are complete.
    "994 runs - end of innings.sr": [(5, "996")] + [(f, "") for f in range(1, 11)]
    + [(11, "996"), (12, "997"), (13, "")],
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_capture_replay(name):
    args = argparse.Namespace(sr=os.path.join(CAPTURES, name), realtime=False)
    ecs_receiver.run_sr_file(args)
    got = [(e["field"], e["value"]) for e in ecs_receiver.BOARD.log]
    assert got == EXPECTED[name]


def test_board_state_after_dismissal():
    args = argparse.Namespace(sr=os.path.join(CAPTURES, "set - runs - wicket - runs.sr"), realtime=False)
    ecs_receiver.run_sr_file(args)
    v = ecs_receiver.BOARD.snapshot()["values"]
    assert v["lh_no"] == "3" and v["rh_no"] == "2"
    assert v["total"] == "7" and v["wickets"] == "1"
    assert v["last_bat"] == "2" and v["last_wkt_total"] == "5"
