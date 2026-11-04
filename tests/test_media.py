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
    make_preview,
    read_frames,
    remux_to_mp4,
    window_playable,
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
    # Deterministic on any host (GPU or not): these args always fail, and differ from CPU_ARGS.
    failing = ["-c:v", "libx264", "-preset", "no_such_preset"]
    assert failing != CPU_ARGS
    monkeypatch.setattr(media, "encoder_args", lambda: list(failing))
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

    def has_block(cmd, block):
        return any(cmd[i:i + len(block)] == block for i in range(len(cmd)))

    assert has_block(encodes[0], failing) and not has_block(encodes[0], CPU_ARGS)
    assert has_block(encodes[1], CPU_ARGS) and "no_such_preset" not in encodes[1]


def test_cut_failure_reports_ffmpeg_tail(tmp_path):
    with pytest.raises(RuntimeError, match="ffmpeg"):
        cut(tmp_path / "nope.mp4", 0, 1, tmp_path / "o.mp4")
    assert list(tmp_path.iterdir()) == []  # no half-written leftovers


def test_cut_only_shows_up_once_finished(tiny_video, tmp_path, monkeypatch):
    # The app lists *.mp4 while a job runs; a clip still being written must not be one.
    seen = []
    real_run = subprocess.run

    def spy(cmd, *a, **k):
        result = real_run(cmd, *a, **k)
        seen.append(sorted(p.name for p in out_dir.iterdir()))
        return result

    out_dir = tmp_path / "clips"
    monkeypatch.setattr(media.subprocess, "run", spy)
    out = cut(tiny_video, 1.0, 3.0, out_dir / "c.mp4")
    assert seen[-1] == ["c.mp4.part"]  # right after ffmpeg: still the temporary name
    assert sorted(p.name for p in out_dir.iterdir()) == ["c.mp4"] and out.is_file()


def test_encoder_args_falls_back_to_cpu_without_gpu(monkeypatch):
    monkeypatch.setattr(media, "_encoder_cache", None)
    monkeypatch.setattr(media, "_probe_encoder", lambda args: False)
    assert media.encoder_args() == CPU_ARGS
    # cached: a later probe is not run again
    monkeypatch.setattr(media, "_probe_encoder", lambda args: pytest.fail("probed twice"))
    assert media.encoder_args() == CPU_ARGS


def test_probe_reads_obs_chapter_markers(tiny_video, tmp_path):
    meta = tmp_path / "chapters.ffmeta"
    meta.write_text("\n".join([";FFMETADATA1", "[CHAPTER]", "TIMEBASE=1/1000", "START=0", "END=4000", "title=One",
                               "[CHAPTER]", "TIMEBASE=1/1000", "START=4000", "END=10000", "title=Two", ""]),
                    encoding="utf-8")
    dst = tmp_path / "marked.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tiny_video), "-i", str(meta),
                    "-map", "0", "-c", "copy", "-map_chapters", "1", str(dst)], check=True)
    assert [c.title for c in probe(dst).chapters] == ["One", "Two"]


def _convert(src, dst, *args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), *args, str(dst)], check=True)
    return dst


def test_window_plays_h264_mp4_but_not_mkv_or_hevc(tiny_video, tmp_path):
    mkv = _convert(tiny_video, tmp_path / "a.mkv", "-c", "copy")
    hevc = _convert(tiny_video, tmp_path / "h.mp4", "-c:v", "libx265", "-c:a", "copy")
    assert probe(tiny_video).video_codec == "h264" and probe(hevc).video_codec == "hevc"
    assert window_playable(tiny_video)
    assert not window_playable(mkv) and not window_playable(hevc)


def test_remux_mkv_to_mp4_keeps_its_length(tiny_video, tmp_path):
    mkv = _convert(tiny_video, tmp_path / "a.mkv", "-c", "copy")
    out = remux_to_mp4(mkv, tmp_path / "out" / "a.mp4")
    assert window_playable(out) and abs(probe(out).duration - probe(tiny_video).duration) < 0.2
    assert sorted(p.name for p in out.parent.iterdir()) == ["a.mp4"]


def test_preview_is_h264_at_most_720p(tiny_video, tmp_path):
    big_hevc = _convert(tiny_video, tmp_path / "h.mp4", "-vf", "scale=1920:1080", "-c:v", "libx265", "-c:a", "copy")
    out = make_preview(big_hevc, tmp_path / "preview.mp4")
    info = probe(out)
    assert window_playable(out) and info.height == 720 and abs(info.duration - 10.0) < 0.3


def test_concat_two_cuts(tiny_video, tmp_path):
    a = cut(tiny_video, 0, 3, tmp_path / "it's a.mp4")
    b = cut(tiny_video, 5, 8, tmp_path / "b.mp4")
    assert abs(probe(concat([a, b], tmp_path / "j.mp4")).duration - 6.0) < 0.3


def test_find_tool_falls_back_to_winget_folder(tmp_path, monkeypatch):
    # Right after the installer runs, a new ffmpeg may not be on PATH yet.
    bin_dir = tmp_path / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_x" / "ffmpeg-9-full_build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ffprobe.exe").write_bytes(b"")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert media.find_tool("ffprobe") == str(bin_dir / "ffprobe.exe")
    assert media.find_tool("ffmpeg") is None


def test_encoder_tries_nvidia_then_amd_then_intel(monkeypatch):
    tried = []
    monkeypatch.setattr(media, "_encoder_cache", None)
    monkeypatch.setattr(media, "_probe_encoder", lambda args: tried.append(args[1]) or args[1] == "h264_qsv")
    assert media.encoder_args() == media.QSV_ARGS
    assert tried == ["h264_nvenc", "h264_amf", "h264_qsv"]
    assert media.encoder_name() == "Intel Quick Sync"
