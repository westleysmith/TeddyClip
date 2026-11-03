import wave
from pathlib import Path

import numpy as np
import pytest

from teddyclip.panns import GROUPS, Tagger, ensure_assets
from teddyclip.signals import people_sounds


def write_silence_wav(path: Path, seconds: int, rate: int) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(np.zeros(seconds * rate, dtype="<i2").tobytes())
    return path


class FakeTagger:
    labels = ["Speech", "Laughter", "Giggle", "Shout"] + ["x"] * 523

    def tag(self, windows):
        out = np.zeros((len(windows), 527))
        out[30:33, 1] = 0.9  # laugh at ~30 s
        return out[: len(windows)]


def test_people_sounds_finds_laugh(tmp_path):
    wav = write_silence_wav(tmp_path / "a.wav", seconds=120, rate=32000)
    s = people_sounds(wav, FakeTagger())
    assert s["laughter"].argmax() in range(29, 34) and s["shout"].max() == 0


class SecondTagger:
    """Laughter at absolute second 95 only, regardless of chunking: each window
    is tagged by the sample value written into it."""
    labels = FakeTagger.labels

    def tag(self, windows):
        out = np.zeros((len(windows), 527))
        out[:, 1] = np.abs(windows).max(axis=1)
        return out


def test_people_sounds_spans_chunks_and_aligns_seconds(tmp_path):
    # 150 s crosses the 60 s chunk boundary twice; a burst at 95 s must come
    # out at second 95 and the array must have one value per second.
    rate = 32000
    pcm = np.zeros(150 * rate, dtype="<i2")
    pcm[95 * rate:96 * rate] = 16384
    wav = tmp_path / "b.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm.tobytes())
    s = people_sounds(wav, SecondTagger())
    assert s["laughter"].size == 150 and s["shout"].size == 150
    assert s["laughter"].argmax() in (94, 95)
    assert s["laughter"][:93].max() == 0 and s["laughter"][97:].max() == 0


def test_people_sounds_skips_missing_group_labels(tmp_path):
    class NoShout(FakeTagger):
        labels = ["Speech", "Laughter"] + ["x"] * 525

    wav = write_silence_wav(tmp_path / "c.wav", seconds=10, rate=32000)
    s = people_sounds(wav, NoShout())
    assert s["shout"].size == 10 and s["shout"].max() == 0


def test_people_sounds_short_audio(tmp_path):
    wav = write_silence_wav(tmp_path / "d.wav", seconds=0, rate=32000)
    s = people_sounds(wav, FakeTagger())
    assert s["laughter"].size == 0 and s["shout"].size == 0


def test_people_sounds_rejects_wrong_rate(tmp_path):
    wav = write_silence_wav(tmp_path / "e.wav", seconds=2, rate=16000)
    with pytest.raises(ValueError):
        people_sounds(wav, FakeTagger())


def test_groups_names():
    assert "Laughter" in GROUPS["laughter"] and "Screaming" in GROUPS["shout"]


@pytest.mark.slow
def test_real_tagger_loads(tmp_path):
    w, l = ensure_assets(tmp_path)
    assert Tagger(w, l).tag(np.zeros((1, 64000), np.float32)).shape == (1, 527)
