import ecs_protocol as proto


def frame_bits(field, digits, spare_lsb=False):
    """Build a 32-bit frame string. digits: 3 ints (15 = blank)."""
    out = ""
    for idx, d in zip((3, 2, 1, 0), [field] + list(digits)):
        spare = (d & 1) if (idx == 0 and spare_lsb) else 0
        out += format(idx, "03b") + format(d, "04b") + str(spare)
    return out


def test_decode_simple_value():
    assert proto.decode_frame(frame_bits(5, (15, 5, 5))) == (5, "55")


def test_decode_three_digits():
    assert proto.decode_frame(frame_bits(12, (9, 9, 7))) == (12, "997")


def test_decode_blank():
    assert proto.decode_frame(frame_bits(1, (15, 15, 15))) == (1, "")


def test_spare_bit_in_units_group_is_ignored():
    assert proto.decode_frame(frame_bits(5, (15, 15, 1), spare_lsb=True)) == (5, "1")


def test_rejects_bad_group_index():
    bits = frame_bits(5, (15, 5, 5))
    bad = "000" + bits[3:]
    assert proto.decode_frame(bad) is None


def test_decodes_umpire_light_field_0():
    assert proto.decode_frame(frame_bits(0, (15, 15, 1))) == (0, "1")


def test_keeps_unknown_field_15():
    assert proto.decode_frame(frame_bits(15, (15, 15, 1))) == (15, "1")
    assert proto.field_name(15) == "field_15"
    assert "15" in proto.field_label(15)


def test_rejects_non_bcd_digit():
    assert proto.decode_frame(frame_bits(5, (15, 10, 1))) is None


def test_rejects_embedded_blank():
    assert proto.decode_frame(frame_bits(5, (1, 15, 1))) is None


def test_every_field_has_a_name_and_label():
    assert set(proto.FIELDS) == set(proto.FIELD_LABELS) == set(range(0, 15))
    assert len(set(proto.FIELDS.values())) == 15


def test_levels_roundtrip():
    """Encode a frame as Manchester half-bits, repeat it, and decode the levels."""
    fs = 100e3
    spb = proto.HALF_BIT_S * fs
    bits = frame_bits(7, (15, 15, 3))
    half = "1111" + "0" + "".join("01" if b == "1" else "10" for b in bits) + "0000"
    burst = "10" * 20 + half * 10
    levels = []
    for i, c in enumerate(burst):
        n = int(round((i + 1) * spb)) - int(round(i * spb))
        levels += [int(c)] * n
    levels = [0] * 5000 + levels + [0] * 5000
    # The last frame's final low half-bit merges into the idle gap, so 9 of 10 copies decode.
    [(field, value, copies)] = proto.decode_levels(levels, fs)
    assert (field, value) == (7, "3") and copies >= 9
