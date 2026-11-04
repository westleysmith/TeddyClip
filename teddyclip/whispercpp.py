"""Transcription on any graphics card, through whisper.cpp built with Vulkan
(NVIDIA, AMD and Intel all support Vulkan). faster-whisper is still used on
NVIDIA cards, where it is fastest; this engine is for everything else.

The installer puts whisper-cli.exe (built by .github/workflows/whisper-vulkan.yml)
in <install folder>/engines/whisper-vulkan and the model in .cache/models."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from teddyclip import progress
from teddyclip.media import NO_WINDOW

MODEL_NAME = "ggml-large-v3-turbo-q5_0.bin"  # large-v3-turbo, quantized: about 550 MB
MODEL_URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{MODEL_NAME}"
ENGINE_DIR = Path(sys.prefix).parent / "engines" / "whisper-vulkan"


def cli_path() -> Path:
    """whisper-cli.exe; TEDDYCLIP_WHISPER_CLI points elsewhere (for development)."""
    override = os.environ.get("TEDDYCLIP_WHISPER_CLI")
    return Path(override) if override else ENGINE_DIR / "whisper-cli.exe"


def model_path(models: Path) -> Path:
    return Path(models) / MODEL_NAME


def available(models: Path) -> tuple[bool, str]:
    """Whether the engine and its model are installed, and why not if they are not."""
    if not cli_path().is_file():
        return False, "the Vulkan transcription engine is not installed (run Install TeddyClip.bat again)"
    if not model_path(models).is_file():
        return False, f"the {MODEL_NAME} model is not downloaded (run Install TeddyClip.bat again)"
    return True, "ready"


# Sample the stderr lines whisper-cli writes while it works.
_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")
# "ggml_vulkan: 0 = Intel(R) Graphics (Intel Corporation) | uma: 1 | ..."
_DEVICE = re.compile(r"ggml_vulkan:\s*\d+\s*=\s*([^|]+)")
_VENDOR = re.compile(r"\s*\([^()]*\)\s*$")  # the trailing "(Intel Corporation)"


def run(wav: Path, models: Path, out_dir: Path, language: str | None = "en") -> tuple[list[dict], str]:
    """Transcribe `wav` with whisper-cli. Returns whisper.cpp's segments (with
    tokens) and the name of the graphics card it used ("" when it ran on the CPU)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / "whispercpp"
    cmd = [
        str(cli_path()), "-m", str(model_path(models)), "-f", str(wav),
        "-l", language or "auto",
        "-t", str(max(1, (os.cpu_count() or 4) - 1)),
        "-ojf", "-of", str(base),  # full JSON: segments plus token timings
        "-pp",  # progress lines on stderr
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", **NO_WINDOW)
    device, tail = "", []
    for line in proc.stderr:
        tail = (tail + [line.rstrip()])[-15:]
        if not device and (m := _DEVICE.search(line)):
            device = _VENDOR.sub("", m.group(1).strip())
        if m := _PROGRESS.search(line):
            fraction = int(m.group(1)) / 100
            progress.step(fraction)
            print(f"\r  Transcribed {fraction:4.0%}", end="", flush=True)
    print()
    code = proc.wait()
    if code != 0:
        # Windows crash codes are large negatives; hex is how they are looked up.
        shown = f"0x{code & 0xFFFFFFFF:08X}" if code < 0 else str(code)
        raise RuntimeError(f"whisper.cpp stopped with exit code {shown}. Last output:\n" + "\n".join(tail[-6:]))
    data = json.loads((base.with_suffix(".json")).read_text(encoding="utf-8"))
    return data.get("transcription", []), device


def to_segments(transcription: list[dict]):
    """whisper.cpp's segments as TeddyClip Segments with word timings. A word
    is a run of tokens up to the next one starting with a space; special
    tokens ([_BEG_], [_TT_123] and the like) are skipped."""
    from teddyclip.transcribe import Segment, Word

    segments = []
    for entry in transcription:
        offsets = entry.get("offsets", {})
        start, end = offsets.get("from", 0) / 1000, offsets.get("to", 0) / 1000
        text = (entry.get("text") or "").strip()
        words: list[Word] = []
        for token in entry.get("tokens", []):
            piece = token.get("text", "")
            if not piece.strip() or piece.strip().startswith("[_"):
                continue
            t0, t1 = token.get("offsets", {}).get("from", 0) / 1000, token.get("offsets", {}).get("to", 0) / 1000
            if words and not piece.startswith(" "):
                last = words[-1]
                words[-1] = Word(last.start, round(max(last.end, t1), 2), last.text + piece)
            else:
                words.append(Word(round(t0, 2), round(t1, 2), piece.strip()))
        if text:
            segments.append(Segment(round(start, 2), round(end, 2), text, words))
    return segments
