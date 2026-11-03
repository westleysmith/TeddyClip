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


@pytest.fixture
def tiny_speech_wav(tmp_path) -> Path:
    """WAV of Windows SAPI saying "clip that". Skips when SAPI is unavailable."""
    out = tmp_path / "speech.wav"
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{str(out).replace(chr(39), chr(39) * 2)}'); "
        "$s.Speak('clip that'); "
        "$s.Dispose()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("Windows SAPI speech synthesis unavailable")
    if not out.is_file() or out.stat().st_size == 0:
        pytest.skip("Windows SAPI produced no audio")
    return out
