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


def stage_in_inbox(video: Path, cfg: Config, game: str | None = None, name: str | None = None) -> Path:
    """Copy `video` into the inbox (inside a game subfolder when `game` is given)."""
    folder = cfg.paths.inbox / game if game else cfg.paths.inbox
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / (name or video.name)
    shutil.copy2(video, dst)
    return dst


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Replace the heavy pipeline steps at the names cli.py uses, so a run needs
    no model weights, GPU, network or Ollama (ffmpeg still runs for real).

    Active as soon as a test asks for it; call it to change the fake recording:
    `trigger_at` puts the words "clip that" in the transcript at that second,
    `flat_signals=True` makes every audio signal zero."""
    import wave

    import numpy as np

    from teddyclip import cli
    from teddyclip.transcribe import Segment, Word

    state = {"trigger_at": None, "flat": False, "transcribe_calls": []}

    def seconds(wav: Path) -> int:
        with wave.open(str(wav), "rb") as f:
            return f.getnframes() // f.getframerate()

    def transcribe(wav, cache, model="auto", hotwords=None, language="en", device="auto", models=None):
        state["transcribe_calls"].append({"model": model, "language": language, "device": device})
        t = state["trigger_at"]
        if t is None:
            return []
        words = [Word(t, t + 0.3, "Clip"), Word(t + 0.3, t + 0.7, "that!")]
        return [Segment(t, t + 0.7, "Clip that!", words)]

    def audio_features(wav16k):
        n = seconds(wav16k)
        loud = np.zeros(n, dtype=np.float32) if state["flat"] else np.linspace(0.1, 1.0, n, dtype=np.float32)
        return {"loudness": loud, "spike": loud.copy(), "burst": np.zeros(n, np.float32), "noisiness": np.zeros(n, np.float32)}

    def people_sounds(wav32k, tagger):
        n = seconds(wav32k)
        laughter = np.zeros(n, dtype=np.float32)
        if not state["flat"] and n > 3:
            laughter[3] = 1.0
        return {"laughter": laughter, "shout": np.zeros(n, dtype=np.float32)}

    def ask(self, prompt, schema):
        keys = set(schema.get("properties", {}))
        if "order" in keys:
            return {"order": [0]}
        if "title" in keys:
            return {"score": 7, "title": "Fake title", "why": "a test", "trim_start": 0, "trim_end": 0}
        return {"score": 1 if state["flat"] else 6, "quote": ""}

    real_screen_events = cli.screen_events

    def screen_events(video, moments, lexicon, weight=0.6, **kwargs):
        # Real frame reads through ffmpeg; the OCR model is replaced by one that reads nothing.
        return real_screen_events(video, moments, lexicon, weight, ocr=lambda img: ([], 0.0), **kwargs)

    monkeypatch.setattr(cli, "transcribe", transcribe)
    monkeypatch.setattr(cli, "release", lambda: None)
    monkeypatch.setattr(cli, "audio_features", audio_features)
    monkeypatch.setattr(cli, "people_sounds", people_sounds)
    monkeypatch.setattr(cli, "ensure_assets", lambda models: (Path(models) / "w.pth", Path(models) / "l.csv"))
    monkeypatch.setattr(cli, "Tagger", lambda weights, labels: object())
    monkeypatch.setattr(cli, "screen_events", screen_events)
    monkeypatch.setattr(cli.LLM, "available", lambda self: True)
    monkeypatch.setattr(cli.LLM, "ask", ask)

    def configure(trigger_at: float | None = None, flat_signals: bool = False) -> dict:
        state["trigger_at"] = trigger_at
        state["flat"] = flat_signals
        return state

    return configure
