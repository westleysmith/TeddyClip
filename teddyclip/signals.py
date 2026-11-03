# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""Excitement signals and "clip that" triggers, fully local (wave -> numpy).

Per-second audio features over a whole recording:
  loudness  - RMS energy per second
  spike     - how loud this second is vs. the rolling median around it
  burst     - density of sudden energy onsets within the second
  noisiness - zero-crossing rate (laughter and crowd noise score high)

`fuse` turns several per-second signals into one 0..1 score and `peak_windows`
picks the windows around its strongest, well-separated peaks.
"""

from __future__ import annotations

import difflib
import re
import wave
from pathlib import Path

import numpy as np

from teddyclip.transcribe import Word

SAMPLE_RATE = 16000
FRAME = SAMPLE_RATE // 20  # 50 ms analysis frames
SPIKE_HALF_WINDOW = 15  # seconds either side for the spike baseline
TRIGGER_GAP = 5.0  # seconds; a repeat of a trigger this close to the last is dropped

_FEATURES = ("loudness", "spike", "burst", "noisiness")


def audio_features(wav16k: Path) -> dict[str, np.ndarray]:
    """Per-second features of a 16 kHz mono 16-bit WAV, one value per second.

    Audio shorter than one second yields empty arrays under every key."""
    pcm = _read_mono_pcm(Path(wav16k))
    n_frames = pcm.size // FRAME
    frames_per_sec = SAMPLE_RATE // FRAME
    n_secs = n_frames // frames_per_sec
    if n_secs == 0:
        return {k: np.zeros(0, dtype=np.float32) for k in _FEATURES}

    # 50 ms frame energies are the working unit for everything below.
    frames = pcm[: n_frames * FRAME].reshape(n_frames, FRAME)
    frame_rms = np.sqrt((frames**2).mean(axis=1))
    used = n_secs * frames_per_sec

    loudness = frame_rms[:used].reshape(n_secs, frames_per_sec).mean(axis=1)

    # Spike: this second vs. the rolling median loudness around it (clamped ratio).
    spike = loudness / np.maximum(_rolling_median(loudness, SPIKE_HALF_WINDOW), 1e-6)
    spike = np.clip(spike, 0, 5)

    # Burst: frame-level onsets (energy jumping >2x over the previous frame)
    # per second; laughter and applause are onset-dense.
    onsets = np.concatenate([[False], frame_rms[1:] > 2.0 * np.maximum(frame_rms[:-1], 1e-6)])
    burst = onsets[:used].reshape(n_secs, frames_per_sec).sum(axis=1)

    # Noisiness: zero-crossing rate per second.
    signs = np.signbit(frames)
    frame_zcr = (signs[:, 1:] != signs[:, :-1]).mean(axis=1)
    noisiness = frame_zcr[:used].reshape(n_secs, frames_per_sec).mean(axis=1)
    # Only count noisiness when something is actually audible.
    audible = loudness > max(loudness.mean() * 0.3, 1e-6)
    noisiness = noisiness * audible

    return {
        "loudness": loudness.astype(np.float32),
        "spike": spike.astype(np.float32),
        "burst": burst.astype(np.float32),
        "noisiness": noisiness.astype(np.float32),
    }


def _read_mono_pcm(wav16k: Path) -> np.ndarray:
    with wave.open(str(wav16k), "rb") as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2 or f.getframerate() != SAMPLE_RATE:
            raise ValueError(
                f"{wav16k} must be 16 kHz mono 16-bit PCM, got {f.getframerate()} Hz, "
                f"{f.getnchannels()} channel(s), {8 * f.getsampwidth()}-bit"
            )
        raw = f.readframes(f.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _rolling_median(x: np.ndarray, half: int) -> np.ndarray:
    """Median of the `half` seconds either side of each second."""
    from numpy.lib.stride_tricks import sliding_window_view

    padded = np.pad(x, half, mode="edge")
    return np.median(sliding_window_view(padded, 2 * half + 1), axis=1).astype(np.float32)


def voice_jump(loudness: np.ndarray) -> np.ndarray:
    """Seconds where the player suddenly gets loud: a shout, a laugh, a scream.
    0..1 per second.

    Measured against their own audible level over the minute either side, not
    the recording's overall level, so a quiet stretch does not make ordinary
    talking read as a shout. Twice that level starts to count; 3.5x is a full
    shout. Silent seconds never count."""
    loud = np.asarray(loudness, dtype=np.float32)
    n = loud.size
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    audible = loud > max(float(loud.mean()) * 0.3, 1e-4)
    if not audible.any():
        return np.zeros(n, dtype=np.float32)
    level = np.full(n, float(np.median(loud[audible])), dtype=np.float32)
    for t in np.flatnonzero(audible):
        lo, hi = max(0, t - 60), t + 61
        near = loud[lo:hi][audible[lo:hi]]
        if near.size >= 10:
            level[t] = float(np.median(near))
    ratio = loud / np.maximum(level, 1e-6)
    return (np.clip((ratio - 2.0) / 1.5, 0.0, 1.0) * audible).astype(np.float32)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def find_triggers(words: list[Word], phrases: list[str], threshold: float = 0.8) -> list[float]:
    """Start time of each place the player said one of `phrases`, such as
    "clip that". Slides over word n-grams of each phrase's length and compares
    lowercase, punctuation-stripped text, so "Clip that!" and a mis-heard
    "clipped that" or "flip that" still match. A match within 5 s of the
    previous one is dropped."""
    spoken = [(w.start, _normalize(w.text)) for w in words]
    spoken = [(t, s) for t, s in spoken if s]
    hits: list[float] = []
    for phrase in phrases:
        target = _normalize(phrase)
        n = len(target.split())
        if n == 0:
            continue
        for i in range(len(spoken) - n + 1):
            heard = " ".join(s for _, s in spoken[i:i + n])
            if difflib.SequenceMatcher(None, heard, target).ratio() >= threshold:
                hits.append(spoken[i][0])
    triggers: list[float] = []
    for t in sorted(hits):
        if not triggers or t - triggers[-1] >= TRIGGER_GAP:
            triggers.append(t)
    return triggers


def pct(x: np.ndarray) -> np.ndarray:
    """Percentile-rank normalization to 0..1 within this video. Equal values
    share the lowest rank, so a mostly-zero signal stays at 0 where it is quiet."""
    x = np.asarray(x)
    if x.size == 0:
        return x.astype(np.float32)
    ranks = np.searchsorted(np.sort(x), x, side="left")
    return (ranks / max(x.size - 1, 1)).astype(np.float32)


def _soft_or(sources: list[tuple[np.ndarray, float]]) -> np.ndarray:
    """Evidence from several independent sources, each 0..1 per second with
    a trust weight: 1 - product(1 - w*s). Agreement raises it; a missing
    source (an empty array) is simply absent, never a penalty."""
    sources = [(s, w) for s, w in sources if s.size]
    if not sources:
        return np.zeros(0, dtype=np.float32)
    n = max(s.size for s, _ in sources)
    miss = np.ones(n, dtype=np.float32)
    for sig, w in sources:
        x = np.zeros(n, dtype=np.float32)
        x[: sig.size] = np.clip(sig, 0.0, 1.0)
        miss *= 1.0 - w * x
    return (1.0 - miss).astype(np.float32)


def fuse(signals: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """One 0..1 score per second: the soft OR of each signal's percentile rank
    times its weight (clipped to 0..1). A signal without a weight counts for
    nothing; shorter arrays are padded with zeros to the longest."""
    sources = [(pct(sig), float(np.clip(weights.get(name, 0.0), 0.0, 1.0)))
               for name, sig in signals.items()]
    return _soft_or(sources)


def peak_windows(
    score: np.ndarray,
    percentile: float = 92,
    pre: float = 20,
    post: float = 15,
) -> list[tuple[float, float, float]]:
    """(start, end, peak score) of the window around each strong peak, in time
    order. A peak must be above the percentile value and above 0; peaks are at
    least `pre + post` seconds apart (the higher one wins), so no two windows
    overlap. Windows are clamped to the video: 0 to len(score)."""
    score = np.asarray(score, dtype=np.float32)
    if score.size == 0:
        return []
    cutoff = max(float(np.percentile(score, percentile)), 0.0)
    hot = np.flatnonzero(score > cutoff)
    # Strongest first; a stable sort keeps the earlier second on ties.
    hot = hot[np.argsort(-score[hot], kind="stable")]
    spacing = pre + post
    peaks: list[int] = []
    for t in hot:
        if all(abs(int(t) - p) >= spacing for p in peaks):
            peaks.append(int(t))
    return [
        (max(0.0, t - pre), min(float(score.size), t + post), float(score[t]))
        for t in sorted(peaks)
    ]
