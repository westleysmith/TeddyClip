"""Draws teddyclip/teddyclip.ico, the starburst logo from the TeddyClip page.
Run it again only if the logo changes: python scripts/make_icon.py"""

import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ORANGE, MUSTARD, CREAM, TEAL = "#d4612a", "#d9a227", "#fff9ee", "#2b7a74"
OUT = Path(__file__).resolve().parent.parent / "teddyclip" / "teddyclip.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


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


def _dib(img: Image.Image) -> bytes:
    """One icon image the way the Windows shell reads it: a 32-bit bottom-up
    BGRA bitmap followed by a 1-bit transparency mask. Without the mask the
    desktop and Start menu reject the whole file and show a blank page."""
    w, h = img.size
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = [img.crop((0, y, w, y + 1)).tobytes("raw", "BGRA") for y in range(h)]
    alpha = img.getchannel("A")
    stride = ((w + 31) // 32) * 4
    mask = bytearray()
    for y in reversed(range(h)):
        bits = bytearray(stride)
        for x in range(w):
            if alpha.getpixel((x, y)) == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits
    return header + b"".join(reversed(rows)) + bytes(mask)


def write_ico(art: Image.Image, path: Path) -> None:
    images = []
    for size in SIZES:
        img = art.resize((size, size), Image.LANCZOS)
        if size == 256:  # the large size is stored as PNG, as Windows' own icons do
            buf = io.BytesIO()
            img.save(buf, "PNG")
            images.append((size, buf.getvalue()))
        else:
            images.append((size, _dib(img)))
    offset = 6 + 16 * len(images)
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for size, data in images:
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in images:
        out += data
    path.write_bytes(bytes(out))


if __name__ == "__main__":
    write_ico(draw(), OUT)
    print(f"wrote {OUT}")
