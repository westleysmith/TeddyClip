import logging
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from teddyclip import media
from teddyclip.media import (
    CPU_ARGS,
    Chapter,
    concat,
    cut,
    extract_audio,
    probe,
    read_frames,
    write_chapters,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def probe_wav_rate(path: Path) -> int:
    with wave.open(str(path), "rb") as f:
        return f.getframerate()


def wav_peak_hz(path: Path) -> float:
    with wave.open(str(path), "rb") as f:
        assert f.getnchannels() == 1 and f.getsampwidth() == 2
        rate = f.getframerate()
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(np.float64)
    spectrum = np.abs(np.fft.rfft(pcm))
    return float(np.argmax(spectrum) * rate / pcm.size)


def test_probe_reads_basics(tiny_video):
    p = probe(tiny_video)
    assert 9.5 < p.duration < 10.5 and round(p.fps) == 30 and p.audio_tracks == 1
    assert (p.width, p.height) == (640, 360)
    assert p.chapters == []


def test_extract_audio_rate(tiny_video, tmp_path):
    wav = extract_audio(tiny_video, tmp_path / "a.wav", rate=16000)
    assert probe_wav_rate(wav) == 16000
    with wave.open(str(wav), "rb") as f:
        assert f.getnchannels() == 1 and f.getsampwidth() == 2


def test_extract_audio_bad_track_falls_back(tiny_video, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        wav = extract_audio(tiny_video, tmp_path / "a.wav", rate=16000, track=5)
    assert wav.exists() and "track 5" in caplog.text


@pytest.fixture
def two_track_video(tmp_path) -> Path:
    """OBS-style recording: one video stream and two separate audio streams (440 Hz, 1000 Hz)."""
    out = tmp_path / "two_tracks.mkv"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=3",
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(out),
        ],
        check=True,
    )
    return out


def test_two_audio_tracks(two_track_video, tmp_path):
    assert probe(two_track_video).audio_tracks == 2
    first = extract_audio(two_track_video, tmp_path / "t1.wav", rate=16000)
    second = extract_audio(two_track_video, tmp_path / "t2.wav", rate=16000, track=2)
    assert abs(wav_peak_hz(first) - 440) < 15
    assert abs(wav_peak_hz(second) - 1000) < 15


def test_read_frames_shape(tiny_video):
    frames = list(read_frames(tiny_video, [1.0, 2.0], width=320))
    assert [t for t, _ in frames] == [1.0, 2.0] and frames[0][1].shape[1] == 320
    arr = frames[0][1]
    assert arr.dtype == np.uint8 and arr.shape == (180, 320, 3)


def test_read_frames_even_height_for_odd_aspect(tmp_path):
    src = tmp_path / "odd.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=642x362:rate=10:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
        ],
        check=True,
    )
    (_, arr), = read_frames(src, [0.5], width=321)
    assert arr.shape[1] == 321 and arr.shape[0] % 2 == 0 and arr.shape[2] == 3


def test_cut_duration(tiny_video, tmp_path):
    out = cut(tiny_video, 2.0, 5.0, tmp_path / "c.mp4")
    assert abs(probe(out).duration - 3.0) < 0.15


def test_cut_retries_on_cpu_when_hardware_encoder_fails(tiny_video, tmp_path, monkeypatch):
    # No NVIDIA GPU here (or a driver that refuses the footage): the first encode fails.
    bogus = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-b:v", "0"]
    calls = []

    def fake_encoder_args():
        calls.append(1)
        return bogus

    monkeypatch.setattr(media, "encoder_args", fake_encoder_args)
    seen = []
    real_run = subprocess.run

    def spy(cmd, *a, **k):
        seen.append(list(cmd))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(media.subprocess, "run", spy)
    out = cut(tiny_video, 1.0, 3.0, tmp_path / "r.mp4")
    assert abs(probe(out).duration - 2.0) < 0.15
    encodes = [c for c in seen if "-ss" in c and "-t" in c]
    assert len(encodes) == 2
    assert "h264_nvenc" in encodes[0] and "libx264" in encodes[1] and "h264_nvenc" not in encodes[1]


def test_cut_failure_reports_ffmpeg_tail(tmp_path):
    with pytest.raises(RuntimeError, match="ffmpeg"):
        cut(tmp_path / "nope.mp4", 0, 1, tmp_path / "o.mp4")


def test_encoder_args_falls_back_to_cpu_without_gpu(monkeypatch):
    monkeypatch.setattr(media, "_encoder_cache", None)
    monkeypatch.setattr(media, "_probe_encoder", lambda args: False)
    assert media.encoder_args() == CPU_ARGS
    # cached: a later probe is not run again
    monkeypatch.setattr(media, "_probe_encoder", lambda args: pytest.fail("probed twice"))
    assert media.encoder_args() == CPU_ARGS


def test_chapters_roundtrip(tiny_video, tmp_path):
    dst = write_chapters(tiny_video, tmp_path / "o.mp4", [Chapter(0, 4, "A = b; c"), Chapter(4, 10, "Two")])
    assert [c.title for c in probe(dst).chapters] == ["A = b; c", "Two"]


def test_chapter_title_escaping_is_complete():
    assert media._escape_meta("a=b;c#d\\e\nf") == "a\\=b\\;c\\#d\\\\e\\\nf"


def test_concat_two_cuts(tiny_video, tmp_path):
    a = cut(tiny_video, 0, 3, tmp_path / "it's a.mp4")
    b = cut(tiny_video, 5, 8, tmp_path / "b.mp4")
    assert abs(probe(concat([a, b], tmp_path / "j.mp4")).duration - 6.0) < 0.3
