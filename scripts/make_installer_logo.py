"""Draws the bear and the TeddyClip name (in Fredoka) for the setup window and
puts it into install.ps1 as base64, because the installer runs before any of
TeddyClip's files are on the PC. Run it again if the logo changes:
python scripts/make_installer_logo.py"""

import base64
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import make_icon

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "teddyclip" / "fonts" / "Fredoka.ttf"
INSTALLER = ROOT / "install.ps1"
WALNUT = "#4a2e1f"
SCALE = 2  # drawn at twice the size so it stays sharp on high-DPI screens


def draw() -> Image.Image:
    bear = make_icon.draw(96 * SCALE)
    font = ImageFont.truetype(str(FONT), 54 * SCALE)
    font.set_variation_by_axes([600, 100])  # weight (SemiBold), width
    text = "TeddyClip"
    left, top, right, bottom = font.getbbox(text)
    width = bear.width + 14 * SCALE + (right - left)
    img = Image.new("RGBA", (width, bear.height), (0, 0, 0, 0))
    img.alpha_composite(bear, (0, 0))
    ImageDraw.Draw(img).text((bear.width + 14 * SCALE - left, (bear.height - (bottom + top)) // 2), text,
                             font=font, fill=WALNUT)
    return img


def _png64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


if __name__ == "__main__":
    script = INSTALLER.read_text(encoding="utf-8")
    for name, img in (("LogoPng", draw()), ("IconPng", make_icon.draw(64))):
        data = _png64(img)
        script, n = re.subn(rf"(?m)^\${name} = '[^']*'$", lambda m: f"${name} = '{data}'", script)
        if n != 1:
            raise SystemExit(f"install.ps1 has no ${name} = '...' line to fill")
        print(f"{name}: {len(data)} base64 characters")
    INSTALLER.write_text(script, encoding="utf-8")
