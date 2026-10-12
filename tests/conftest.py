import os
import re
import sys
import zipfile

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURES = os.path.join(ROOT, "captures")
sys.path.insert(0, os.path.join(ROOT, "receiver"))


def load_sr(name):
    """Return (raw sample bytes, sample rate) for a PulseView capture. Bit 0 = D0 (TX2 data),
    bit 1 = D1 (TX2 supply, high while transmitting)."""
    z = zipfile.ZipFile(os.path.join(CAPTURES, name))
    meta = z.read("metadata").decode()
    m = re.search(r"samplerate=([\d.]+) (\w?)Hz", meta)
    fs = float(m.group(1)) * {"": 1, "k": 1e3, "M": 1e6}[m.group(2)]
    names = sorted((n for n in z.namelist() if n.startswith("logic-1-")),
                   key=lambda n: int(n.split("-")[-1]))
    return np.frombuffer(b"".join(z.read(n) for n in names), dtype=np.uint8), fs


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep tests from touching receiver/state.json."""
    import ecs_receiver
    monkeypatch.setattr(ecs_receiver, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(ecs_receiver.DIRECTOR, "state_file", str(tmp_path / "match.json"))
    ecs_receiver.BOARD.reset()
    ecs_receiver.BOARD.log.clear()
    yield
