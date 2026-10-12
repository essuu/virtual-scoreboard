"""ECS cricket scoreboard radio protocol (reverse-engineered Oct 2026). See docs/PROTOCOL.md.

Line code : Manchester, half-bit ~531 us (~940 bit/s), sent via Radiometrix TX2 FM at 433.92 MHz.
Burst     : 1010... preamble, then the same frame repeated 10 times.
Frame     : sync = 4 half-bits high, one half-bit low, then 32 Manchester bits
            ("01" = 1, "10" = 0 at the TXD pin).
Payload   : 4 groups of 8 bits, MSB first: [3-bit group index][4-bit BCD digit][1 spare bit]
            group 3 = field ID, groups 2/1/0 = hundreds/tens/units. Digit 15 = blank.
"""

__version__ = "1.0.0"

HALF_BIT_S = 531e-6

FIELDS = {
    1: "lh_no", 2: "rh_no", 3: "lh_runs", 4: "rh_runs", 5: "total", 6: "wickets",
    7: "overs", 8: "extras", 9: "last_bat", 10: "last_wkt_total", 11: "first_inns",
    12: "target", 13: "dls_par", 14: "runs_remaining",
}
FIELD_LABELS = {
    1: "LH batter no.", 2: "RH batter no.", 3: "LH batter runs", 4: "RH batter runs",
    5: "Total", 6: "Wickets", 7: "Overs", 8: "Extras", 9: "Last batter",
    10: "Total at last wkt", 11: "1st innings total", 12: "Target", 13: "DLS par score",
    14: "Runs remaining",
}


def decode_frame(bits):
    """bits: 32-char '0'/'1' string (already in the '01'=1 convention).
    Returns (field_id, value_str) or None if the frame fails validation."""
    groups = [bits[i:i + 8] for i in range(0, 32, 8)]
    for n, g in enumerate(groups):
        if int(g[:3], 2) != 3 - n:
            return None
        if n < 3 and g[7] != "0":
            return None
    digits = [int(g[3:7], 2) for g in groups]
    field = digits[0]
    if field not in FIELDS:
        return None
    out = ""
    for d in digits[1:]:
        if d == 15:
            out += " "
        elif d <= 9:
            out += str(d)
        else:
            return None
    # blanks must be leading only (e.g. "  5", " 55", "   ")
    stripped = out.lstrip(" ")
    if " " in stripped:
        return None
    return field, stripped


def frames_from_halfbits(s):
    """s: string of half-bit levels ('0'/'1'). Yields decoded (field, value) per valid frame."""
    i = s.find("11110")
    while i != -1:
        h = s[i + 5:i + 69]
        if len(h) == 64:
            bits = []
            for k in range(0, 64, 2):
                p = h[k:k + 2]
                if p == "01":
                    bits.append("1")
                elif p == "10":
                    bits.append("0")
                else:
                    break
            if len(bits) == 32:
                r = decode_frame("".join(bits))
                if r:
                    yield r
        i = s.find("11110", i + 1)


def halfbits_from_runs(runs, samples_per_halfbit):
    """runs: list of (level 0/1, length in samples). Long runs (> 20 half-bits) break the stream."""
    parts = []
    for lvl, n in runs:
        k = int(round(n / samples_per_halfbit))
        if k > 20:
            parts.append("|")
            continue
        parts.append(str(lvl) * k)
    return "".join(parts)


def decode_levels(levels, fs):
    """levels: iterable/array of 0/1 samples at rate fs. Returns list of (field, value) with
    the number of frames agreeing, one entry per burst (majority vote, >=2 agreeing frames)."""
    import numpy as np
    from collections import Counter
    lv = np.asarray(levels, dtype=np.int8)
    if lv.size < 2:
        return []
    edges = np.flatnonzero(np.diff(lv)) + 1
    bounds = np.concatenate(([0], edges, [lv.size]))
    runs = [(int(lv[bounds[k]]), int(bounds[k + 1] - bounds[k])) for k in range(len(bounds) - 1)]
    s = halfbits_from_runs(runs, HALF_BIT_S * fs)
    results = []
    for chunk in s.split("|"):
        c = Counter(frames_from_halfbits(chunk))
        if c:
            (fv, n) = c.most_common(1)[0]
            if n >= 2:
                results.append((fv[0], fv[1], n))
    return results
