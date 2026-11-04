"""Draws teddyclip/teddyclip.ico, the bear logo from the TeddyClip page.
Run it again only if the logo changes: python scripts/make_icon.py"""

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ORANGE, EAR, CREAM, BROWN = "#d4612a", "#f0a35e", "#fbf1e1", "#4a2e1f"
OUT = Path(__file__).resolve().parent.parent / "teddyclip" / "teddyclip.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw(size: int = 1024) -> Image.Image:
    """The page's bear SVG (a 48 x 44 grid), centred on a square."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s, top = size / 48, 2 * size / 48

    def circle(cx, cy, r, fill, ry=None):
        ry = r if ry is None else ry
        d.ellipse([(cx - r) * s, top + (cy - ry) * s, (cx + r) * s, top + (cy + ry) * s], fill=fill)

    for cx in (10.5, 37.5):
        circle(cx, 11, 8.5, ORANGE)
        circle(cx, 11, 4.4, EAR)
    circle(24, 25.5, 18, ORANGE, ry=17)
    circle(24, 28, 9.6, CREAM)
    d.polygon([(20.6 * s, top + 23.4 * s), (28.8 * s, top + 28 * s), (20.6 * s, top + 32.6 * s)], fill=BROWN)
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
