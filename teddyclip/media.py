# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""All ffmpeg and ffprobe calls live here: probing, audio and frame extraction,
frame-accurate cutting, joining, and copies the app window can play.

Encoder choice follows Clips Kitty's video/encoding.py (probe NVENC once with a
real test encode, otherwise use libx264) and the CPU retry in video/cutter.py.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

log = logging.getLogger(__name__)

CPU_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
NVENC_ARGS = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-b:v", "0"]
AMF_ARGS = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]
QSV_ARGS = ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "23"]
# Graphics-card video encoders, tried in this order; the first that works is used.
HARDWARE_ENCODERS = [("NVIDIA NVENC", NVENC_ARGS), ("AMD AMF", AMF_ARGS), ("Intel Quick Sync", QSV_ARGS)]

# Every platform normalises uploads to about -14 LUFS, so normalise once here.
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
FADE_SECONDS = 0.15
AUDIO_RATE = 48000  # loudnorm upsamples internally; bring it back down

_encoder_cache: list[str] | None = None


@dataclass
class Chapter:
    start: float
    end: float
    title: str


@dataclass
class Probe:
    duration: float
    fps: float
    width: int
    height: int
    audio_tracks: int
    chapters: list[Chapter] = field(default_factory=list)
    video_codec: str = ""


def find_tool(name: str) -> str | None:
    """Path to ffmpeg or ffprobe. Falls back to where winget installs FFmpeg,
    because a program started right after the installer (or before a restart)
    may not see the new PATH yet."""
    path = shutil.which(name)
    if path:
        return path
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    if not winget.parent.parent.name:
        return None
    candidates = [winget / "Links" / f"{name}.exe",
                  *sorted((winget / "Packages").glob(f"Gyan.FFmpeg*/*/bin/{name}.exe"))]
    return next((str(p) for p in candidates if p.is_file()), None)


def _tool(name: str) -> str:
    path = find_tool(name)
    if path is None:
        raise RuntimeError("ffmpeg not found: run Install TeddyClip.bat again, or see README step 2")
    return path


# The TeddyClip window has no console, so each ffmpeg run would otherwise flash one.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


@contextlib.contextmanager
def _writing(dst: Path) -> Iterator[Path]:
    """A temporary name next to `dst` that becomes `dst` only once ffmpeg has
    finished, so the app never lists (or tries to play) a half-written video."""
    part = dst.with_name(dst.name + ".part")
    try:
        yield part
        os.replace(part, dst)
    finally:
        part.unlink(missing_ok=True)


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    """Run a command (args are always a list, paths may contain spaces)."""
    result = subprocess.run(cmd, capture_output=True, **NO_WINDOW)
    if result.returncode != 0:
        _fail(what, result)
    return result


def _stderr_tail(result: subprocess.CompletedProcess, chars: int = 2000) -> str:
    err = result.stderr
    if isinstance(err, bytes):
        err = err.decode("utf-8", errors="replace")
    return (err or "").strip()[-chars:]


def _fail(what: str, result: subprocess.CompletedProcess) -> None:
    raise RuntimeError(f"ffmpeg could not {what} (exit code {result.returncode}):\n{_stderr_tail(result)}")


def _fraction(text: str) -> float:
    num, _, den = (text or "0/1").partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> Probe:
    result = _run(
        [
            _tool("ffprobe"), "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", "-show_chapters", str(path),
        ],
        f"read {Path(path).name}",
    )
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0.0)
    chapters = [
        Chapter(float(c["start_time"]), float(c["end_time"]), c.get("tags", {}).get("title", ""))
        for c in info.get("chapters", [])
    ]
    return Probe(
        duration=duration,
        fps=_fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        audio_tracks=len(audio),
        chapters=chapters,
        video_codec=str(video.get("codec_name", "")),
    )


def extract_audio(src: Path, dst: Path, rate: int, track: int | None = None) -> Path:
    """Mono 16-bit PCM WAV at `rate`. `track` is 1-based; a missing one falls back to track 1."""
    wanted = track or 1
    if wanted > 1 and probe(src).audio_tracks < wanted:
        log.warning("Audio track %d not found in %s, using track 1", wanted, Path(src).name)
        wanted = 1
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _tool("ffmpeg"), "-y", "-v", "error", "-i", str(src),
            "-map", f"0:a:{wanted - 1}", "-vn",
            "-c:a", "pcm_s16le", "-ac", "1", "-ar", str(rate), str(dst),
        ],
        f"extract audio from {Path(src).name}",
    )
    return dst


def read_frames(src: Path, times: list[float], width: int = 1280) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (time, RGB uint8 array of shape (h, w, 3)) per time, one fast-seek call each."""
    info = probe(src)
    if info.width <= 0 or info.height <= 0:
        raise RuntimeError(f"ffmpeg found no video stream in {Path(src).name}")
    height = max(2, int(round(info.height * width / info.width / 2)) * 2)  # even, aspect kept
    ffmpeg = _tool("ffmpeg")
    for t in times:
        result = _run(
            [
                ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", str(src),
                "-frames:v", "1", "-vf", f"scale={width}:{height}",
                "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ],
            f"read a frame at {t:.1f}s from {Path(src).name}",
        )
        if len(result.stdout) < width * height * 3:
            log.warning("No frame at %.1fs in %s (past the end?), skipping", t, Path(src).name)
            continue
        frame = np.frombuffer(result.stdout, np.uint8, width * height * 3).reshape(height, width, 3)
        yield t, frame


def _probe_encoder(args: list[str]) -> bool:
    """Test-encode a tiny clip with the exact arguments we render with."""
    try:
        result = subprocess.run(
            [
                _tool("ffmpeg"), "-v", "error",
                "-f", "lavfi", "-i", "color=black:s=256x256:r=30:d=1",
                *args, "-pix_fmt", "yuv420p", "-f", "null", "-",
            ],
            capture_output=True,
            timeout=30,
            **NO_WINDOW,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return False


def encoder_name() -> str:
    """Which encoder clips are cut with, in plain words."""
    args = encoder_args()
    return next((name for name, a in HARDWARE_ENCODERS if a == args), "the CPU")


def encoder_args() -> list[str]:
    """The first graphics-card encoder (NVIDIA, AMD, Intel) whose test encode
    works, otherwise libx264 on the CPU. Decided once per process."""
    global _encoder_cache
    if _encoder_cache is None:
        _encoder_cache = list(CPU_ARGS)
        for name, args in HARDWARE_ENCODERS:
            if _probe_encoder(args):
                log.info("Using %s for video encoding", name)
                _encoder_cache = list(args)
                break
    return list(_encoder_cache)


def _swap_encoder(cmd: list[str], old: list[str], new: list[str]) -> list[str]:
    """Replace the encoder block in a built command, so both attempts share every other choice."""
    i = cmd.index(old[0])
    return cmd[:i] + list(new) + cmd[i + len(old):]


def cut(src: Path, start: float, end: float, dst: Path) -> Path:
    """Frame-accurate re-encode of [start, end], constant frame rate, -14 LUFS, short audio fades."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    length = end - start
    if length <= 0:
        raise ValueError(f"cut needs end after start (got {start} to {end})")
    fade = min(FADE_SECONDS, length / 2)
    audio_filter = ",".join(
        [
            "aresample=async=1",
            LOUDNORM,
            f"aresample={AUDIO_RATE}",
            f"afade=t=in:st=0:d={fade:g}",
            f"afade=t=out:st={length - fade:.3f}:d={fade:g}",
        ]
    )
    enc = encoder_args()
    with _writing(dst.resolve()) as part:
        cmd = [
            _tool("ffmpeg"), "-y", "-v", "error",
            "-ss", f"{start:.3f}",  # before -i: fast seek, then decode to the exact frame
            "-i", str(Path(src).resolve()),
            "-t", f"{length:.3f}",
            "-map", "0:v:0", "-map", "0:a:0?",
            "-fps_mode", "cfr",  # VFR recordings otherwise drift against the audio
            "-af", audio_filter,
            *enc, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            "-f", "mp4", str(part),
        ]
        result = subprocess.run(cmd, capture_output=True, **NO_WINDOW)
        if result.returncode != 0 and enc != CPU_ARGS:
            # The start-up probe only sees a synthetic frame; the real footage can still be refused.
            log.warning("Hardware encoder refused %s, retrying on the CPU", Path(src).name)
            result = subprocess.run(_swap_encoder(cmd, enc, CPU_ARGS), capture_output=True, **NO_WINDOW)
        if result.returncode != 0:
            _fail(f"cut {Path(src).name} from {start:.1f}s to {end:.1f}s", result)
    return dst


def _quote_concat(path: Path) -> str:
    return "'" + str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''") + "'"


def concat(files: list[Path], dst: Path) -> Path:
    """Join clips that share codec settings (as `cut` makes them) without re-encoding."""
    if not files:
        raise ValueError("concat needs at least one file")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, _writing(dst.resolve()) as part:
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file {_quote_concat(f)}\n" for f in files), encoding="utf-8")
        _run(
            [
                _tool("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0",
                "-i", str(listing), "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(part),
            ],
            "join the clips",
        )
    return dst


# Formats the TeddyClip window (Edge WebView2) plays without help.
WINDOW_CONTAINERS = {".mp4", ".m4v", ".mov"}
WINDOW_CODECS = {"h264"}
PREVIEW_HEIGHT = 720


def window_playable(path: Path) -> bool:
    """True when the app window can play `path` as it is: H.264 in MP4 or MOV.
    OBS can also record MKV, or H.265 and AV1 on some graphics cards."""
    path = Path(path)
    return path.suffix.lower() in WINDOW_CONTAINERS and probe(path).video_codec in WINDOW_CODECS


def remux_to_mp4(src: Path, dst: Path) -> Path:
    """Copy the video and every audio track of `src` into an MP4, without re-encoding."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with _writing(dst.resolve()) as part:
        _run(
            [
                _tool("ffmpeg"), "-y", "-v", "error", "-i", str(Path(src).resolve()),
                "-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-movflags", "+faststart",
                "-f", "mp4", str(part),
            ],
            f"copy {Path(src).name} into an MP4",
        )
    return dst


def make_preview(src: Path, dst: Path) -> Path:
    """A smaller H.264 copy of `src` (at most 720 lines) for the window to play
    when it cannot play the original. Clips are still cut from the original."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    enc = encoder_args()
    with _writing(dst.resolve()) as part:
        cmd = [
            _tool("ffmpeg"), "-y", "-v", "error", "-i", str(Path(src).resolve()),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", f"scale=-2:'min({PREVIEW_HEIGHT},ih)'",
            *enc, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-f", "mp4", str(part),
        ]
        result = subprocess.run(cmd, capture_output=True, **NO_WINDOW)
        if result.returncode != 0 and enc != CPU_ARGS:
            log.warning("Hardware encoder refused %s, making the preview on the CPU", Path(src).name)
            result = subprocess.run(_swap_encoder(cmd, enc, CPU_ARGS), capture_output=True, **NO_WINDOW)
        if result.returncode != 0:
            _fail(f"make a preview of {Path(src).name}", result)
    return dst
