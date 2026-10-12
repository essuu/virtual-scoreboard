"""End-to-end radio test: turn a real logic capture into simulated FM IQ and decode it."""
import numpy as np
import pytest

import ecs_receiver
from conftest import load_sr

FS = 1024000
OFFSET = 200e3


def simulate_iq(levels, fs_in, power, freq_error=0.0, deviation=20e3, snr_db=20.0, seed=1):
    """FM-modulate the TX2 data pin while the TX2 is powered, as uint8 IQ at FS."""
    n = int(levels.size * FS / fs_in)
    idx = (np.arange(n) * (fs_in / FS)).astype(np.int64)
    data = levels[idx].astype(np.float32)
    on = power[idx].astype(np.float32)
    f = OFFSET + freq_error + deviation * (2 * data - 1)
    phase = 2 * np.pi * np.cumsum(f) / FS
    rng = np.random.default_rng(seed)
    noise_amp = 10 ** (-snr_db / 20) / np.sqrt(2)
    x = on * np.exp(1j * phase) * 0.5
    x = x + 0.5 * noise_amp * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    iq = np.empty(2 * n, np.float32)
    iq[0::2], iq[1::2] = x.real, x.imag
    return np.clip(np.round(iq * 127 + 127.4), 0, 255).astype(np.uint8)


@pytest.mark.parametrize("freq_error", [0.0, 150e3, -150e3])
def test_fm_decode(freq_error):
    full, fs = load_sr("55_runs.sr")
    # D1 (bit 1) is the TX2 supply: the carrier is only on while it is high.
    seg = slice(int(0.6 * fs), int(1.5 * fs))
    data, power = full[seg] & 1, (full[seg] >> 1) & 1
    iq = simulate_iq(data, fs, power, freq_error=freq_error)
    dec = ecs_receiver.RadioDecoder(FS, OFFSET)
    chunk = FS * 2 // 10
    for i in range(0, iq.size, chunk):
        dec.feed(iq[i:i + chunk])
    got = [(e["field"], e["value"]) for e in ecs_receiver.BOARD.log]
    assert got == [(5, "55")]
    # applied early, from the first copies, then confirmed by the whole burst
    assert dec.last_early_ms is not None and dec.last_early_ms < 150
    assert ecs_receiver.BOARD.log[0]["copies"] >= 9


def test_noise_only_gives_no_messages():
    rng = np.random.default_rng(7)
    iq = np.clip(np.round(rng.standard_normal(2 * FS * 3) * 10 + 127.4), 0, 255).astype(np.uint8)
    dec = ecs_receiver.RadioDecoder(FS, OFFSET)
    chunk = FS * 2 // 10
    for i in range(0, iq.size, chunk):
        dec.feed(iq[i:i + chunk])
    assert ecs_receiver.BOARD.log == []
