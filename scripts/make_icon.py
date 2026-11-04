"""Draws teddyclip/teddyclip.ico, the starburst logo from the TeddyClip page.
Run it again only if the logo changes: python scripts/make_icon.py"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

ORANGE, MUSTARD, CREAM, TEAL = "#d4612a", "#d9a227", "#fff9ee", "#2b7a74"
OUT = Path(__file__).resolve().parent.parent / "teddyclip" / "teddyclip.ico"


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 40  # the page's SVG is drawn on a 40 x 40 grid
    c = 20 * s
    d.ellipse([c - 18 * s, c - 18 * s, c + 18 * s, c + 18 * s], fill=ORANGE)
    for k in range(8):
        a = k * math.pi / 4
        inner, outer = 9.5 * s, 16 * s
        d.line([(c + inner * math.cos(a), c + inner * math.sin(a)),
                (c + outer * math.cos(a), c + outer * math.sin(a))], fill=MUSTARD, width=round(2.8 * s))
    d.ellipse([c - 7.5 * s, c - 7.5 * s, c + 7.5 * s, c + 7.5 * s], fill=CREAM)
    d.polygon([(18 * s, 16.5 * s), (24 * s, 20 * s), (18 * s, 23.5 * s)], fill=TEAL)
    return img


if __name__ == "__main__":
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT}")
