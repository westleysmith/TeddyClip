import shutil
import subprocess
from pathlib import Path

import pytest

from teddyclip.config import Config, load_config


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = load_config(tmp_path / "missing.yaml")
    c.root = tmp_path / "TeddyClip"
    return c


@pytest.fixture
def tiny_video(tmp_path) -> Path:
    """10 s 640x360 30 fps mp4: test pattern, 440 Hz tone, silence from 4 s to 6 s."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    out = tmp_path / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
            "-af", "volume=enable='between(t,4,6)':volume=0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(out),
        ],
        check=True,
    )
    return out
