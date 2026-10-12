"""Draw the Stream Deck key images in streamdeck/icons (144x144 PNG, scoreboard colours).

    pip install pillow
    python tools/make_streamdeck_icons.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "streamdeck", "icons")
S = 144
BG, PANEL, INK, MUTED, ACCENT = "#0f2a22", "#1d4a3c", "#f4f1e8", "#b9c4bd", "#e8b84a"
FONT = None
for f in ("DejaVuSansCondensed-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
          "C:/Windows/Fonts/bahnschrift.ttf", "C:/Windows/Fonts/arialbd.ttf"):
    try:
        ImageFont.truetype(f, 10)
        FONT = f
        break
    except OSError:
        pass


def font(size):
    return ImageFont.truetype(FONT, size) if FONT else ImageFont.load_default()


def key(label, sub=None, colour=INK):
    im = Image.new("RGB", (S, S), BG)
    d = ImageDraw.Draw(im)
    if label:
        f = font(26 if len(label) <= 6 else 21)
        w = d.textlength(label, font=f)
        d.text(((S - w) / 2, 102 if sub is None else 94), label, font=f, fill=colour)
    if sub:
        f = font(17)
        w = d.textlength(sub, font=f)
        d.text(((S - w) / 2, 121), sub, font=f, fill=MUTED)
    return im, d


def camera(d, cx, cy, scale=1.0, fill=INK):
    w, h = 44 * scale, 30 * scale
    d.rounded_rectangle((cx - w / 2 - 8 * scale, cy - h / 2, cx + w / 2 - 8 * scale, cy + h / 2), 6 * scale, fill=fill)
    x = cx + w / 2 - 8 * scale
    d.polygon([(x, cy - 5 * scale), (x + 18 * scale, cy - 14 * scale), (x + 18 * scale, cy + 14 * scale),
               (x, cy + 5 * scale)], fill=fill)


def end_key(side):
    im, d = key("LEFT END" if side == "left" else "RIGHT END", "bowling now", ACCENT)
    camera(d, 72 + (10 if side == "left" else -6), 52, 0.95)
    if side == "left":
        d.polygon([(10, 52), (32, 34), (32, 70)], fill=ACCENT)
    else:
        d.polygon([(134, 52), (112, 34), (112, 70)], fill=ACCENT)
    return im


def board_key():
    im, d = key("BOARD")
    for r in range(3):
        for c in range(3):
            x, y = 34 + c * 26, 18 + r * 24
            d.rounded_rectangle((x, y, x + 22, y + 20), 4, fill=ACCENT if (r, c) == (0, 1) else PANEL)
    return im


def live_key():
    im, d = key("LIVE", "back to play")
    camera(d, 64, 50, 1.1)
    d.ellipse((96, 16, 112, 32), fill="#d9534f")
    return im


def team_key(team):
    im, d = key(team.upper(), "bat first", ACCENT)
    # a bat
    d.rounded_rectangle((62, 20, 82, 70), 8, fill=INK)
    d.rectangle((68, 6, 76, 22), fill=MUTED)
    d.ellipse((92, 58, 106, 72), fill="#c0392b")
    return im


def swap_key():
    im, d = key("SWAP", "ends")
    d.line((30, 38, 110, 38), fill=INK, width=8)
    d.polygon([(114, 38), (96, 24), (96, 52)], fill=INK)
    d.line((34, 70, 114, 70), fill=ACCENT, width=8)
    d.polygon([(30, 70), (48, 56), (48, 84)], fill=ACCENT)
    return im


def auto_key():
    im, d = key("AUTO", "on / off")
    d.ellipse((40, 12, 104, 76), outline=ACCENT, width=8)
    d.polygon([(100, 30), (112, 48), (90, 46)], fill=ACCENT)
    d.ellipse((62, 34, 82, 54), fill=INK)
    return im


def breaks_key():
    im, d = key("BREAKS", "scenes")
    d.rounded_rectangle((40, 30, 92, 74), 10, fill=INK)          # a cup
    d.ellipse((84, 38, 108, 62), outline=INK, width=7)
    d.rounded_rectangle((32, 76, 108, 84), 4, fill=MUTED)
    for x in (52, 66, 80):
        d.line((x, 10, x, 24), fill=MUTED, width=4)
    return im


def setup_key():
    im, d = key("SETUP", "match")
    import math
    cx, cy = 72, 46
    for k in range(8):
        a = k * math.pi / 4
        d.line((cx + 22 * math.cos(a), cy + 22 * math.sin(a), cx + 36 * math.cos(a), cy + 36 * math.sin(a)),
               fill=INK, width=12)
    d.ellipse((cx - 27, cy - 27, cx + 27, cy + 27), fill=INK)
    d.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill=BG)
    return im


def scene_key(label, sub=None):
    im, d = key(label, sub)
    d.rounded_rectangle((26, 18, 118, 78), 8, outline=MUTED, width=5)
    return im


ICONS = {
    "left_end.png": end_key("left"), "right_end.png": end_key("right"),
    "board.png": board_key(), "live.png": live_key(),
    "home_first.png": team_key("Home"), "away_first.png": team_key("Away"),
    "swap_ends.png": swap_key(), "auto.png": auto_key(),
    "breaks.png": breaks_key(), "setup.png": setup_key(),
    "starting_soon.png": scene_key("STARTING", "soon"), "break_scene.png": scene_key("DRINKS", "tea / innings"),
    "technical.png": scene_key("TECH", "difficulties"),
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, im in ICONS.items():
        im.save(os.path.join(OUT, name))
    sheet = Image.new("RGB", (4 * (S + 12) + 12, ((len(ICONS) + 3) // 4) * (S + 12) + 12), "#222")
    for i, im in enumerate(ICONS.values()):
        sheet.paste(im, (12 + (i % 4) * (S + 12), 12 + (i // 4) * (S + 12)))
    sheet.save(os.path.join(OUT, "_all.png"))
    print("wrote %d icons to %s" % (len(ICONS), OUT))
