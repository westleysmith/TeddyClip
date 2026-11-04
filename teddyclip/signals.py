# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""Excitement signals and "clip that" triggers, fully local (wave -> numpy).

Per-second audio features over a whole recording:
  loudness  - RMS energy per second
  spike     - how loud this second is vs. the rolling median around it
  burst     - density of sudden energy onsets within the second
  noisiness - zero-crossing rate (laughter and crowd noise score high)

`people_sounds` adds laughter and shouts heard by a PANNs sound tagger.
`fuse` turns several per-second signals into one 0..1 score and `peak_windows`
picks the windows around its strongest, well-separated peaks.
"""

from __future__ import annotations

import difflib
import re
import wave
from pathlib import Path

import numpy as np

from teddyclip import progress
from teddyclip.panns import GROUPS, SAMPLE_RATE as PANNS_RATE
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


TRIGGER_MAX_PAUSE = 1.0  # seconds between one word of a trigger phrase and the next
TRIGGER_FIRST_WORD_RATIO = 0.8
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")
_PAST_TENSE = ("ped", "ed", "d", "t")


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _first_word_matches(heard: str, target: str, next_target: str | None) -> bool:
    """Whether a heard word can be the first word of a trigger phrase.

    The same word always counts. A misspelling counts when it is close
    (difflib ratio >= 0.8, for example "cliip"), but an inflection of the word
    does not: "clips that" and "clipping that" are ordinary talk. One mishear is
    allowed on purpose: before a word starting with "th" Whisper often writes
    "clip that" as "clipped that", because the p runs into the th. "clipped it"
    has no such excuse and does not count."""
    if heard == target:
        return True
    if heard.startswith(target):
        rest = heard[len(target):]
        return bool(next_target and next_target.startswith("th") and rest in _PAST_TENSE)
    return difflib.SequenceMatcher(None, heard, target).ratio() >= TRIGGER_FIRST_WORD_RATIO


def find_triggers(words: list[Word], phrases: list[str]) -> list[float]:
    """Start time of each place the player said one of `phrases`, such as
    "clip that", matched word by word on lowercase, punctuation-stripped text.

    The first word may be a close misspelling (see `_first_word_matches`); every
    later word must be exactly the phrase's word. The words must follow each
    other with at most 1 s between one word's end and the next one's start, and
    no word but the last may end a sentence (. ! or ?), so "...a clip. That
    was..." is not a trigger; a comma is fine. A match within 5 s of the
    previous one is dropped."""
    spoken: list[tuple[Word, str, bool]] = []  # (word, normalized text, ends a sentence)
    for w in words:
        text = _normalize(w.text)
        ends = bool(_SENTENCE_END.search(w.text.strip()))
        if text:
            spoken.append((w, text, ends))
        elif ends and spoken:
            # Punctuation on its own still ends the sentence before it.
            prev, prev_text, _ = spoken[-1]
            spoken[-1] = (prev, prev_text, True)

    hits: list[float] = []
    for phrase in phrases:
        target = _normalize(phrase).split()
        n = len(target)
        if n == 0:
            continue
        for i in range(len(spoken) - n + 1):
            run = spoken[i:i + n]
            if not _first_word_matches(run[0][1], target[0], target[1] if n > 1 else None):
                continue
            if any(text != want for (_, text, _), want in zip(run[1:], target[1:])):
                continue
            if any(ends for _, _, ends in run[:-1]):
                continue
            if any(b.start - a.end > TRIGGER_MAX_PAUSE + 1e-6 for (a, _, _), (b, _, _) in zip(run, run[1:])):
                continue
            hits.append(run[0][0].start)
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


def contributions(signals: dict[str, np.ndarray], weights: dict[str, float]) -> dict[str, np.ndarray]:
    """Each signal's share of the fused score, per second: its percentile rank
    times its weight (clipped to 0..1). Every array is padded with zeros to the
    longest; a signal without a weight is all zeros. These are exactly the
    quantities `fuse` combines, so they also say which signal made a peak."""
    parts = {name: np.clip(pct(sig), 0.0, 1.0) * float(np.clip(weights.get(name, 0.0), 0.0, 1.0))
             for name, sig in signals.items()}
    n = max((p.size for p in parts.values()), default=0)
    out = {}
    for name, part in parts.items():
        padded = np.zeros(n, dtype=np.float32)
        padded[: part.size] = part
        out[name] = padded
    return out


def fuse(signals: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """One 0..1 score per second: the soft OR, 1 - product(1 - c), of every
    signal's contribution c (see `contributions`). Agreement raises it; a
    missing signal (an empty array) is simply absent, never a penalty."""
    parts = contributions(signals, weights)
    if not parts or not next(iter(parts.values())).size:
        return np.zeros(0, dtype=np.float32)
    miss = np.ones(next(iter(parts.values())).size, dtype=np.float32)
    for part in parts.values():
        miss *= 1.0 - part
    return (1.0 - miss).astype(np.float32)


def peak_windows(
    score: np.ndarray,
    percentile: float = 92,
    pre: float = 20,
    post: float = 15,
) -> list[tuple[float, float, float, float]]:
    """(start, end, peak score, peak second) of the window around each strong
    peak, in time order. A peak must be above the percentile value and above 0;
    peaks are at least `pre + post` seconds apart (the higher one wins), so no
    two windows overlap. Windows are clamped to the video: 0 to len(score)."""
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
        (max(0.0, t - pre), min(float(score.size), t + post), float(score[t]), float(t))
        for t in sorted(peaks)
    ]


PEOPLE_CHUNK_SECONDS = 60  # read and tagged at a time: a 4 hour file never sits in memory
PEOPLE_BASELINE = 90  # seconds either side that set a sound's usual level in this recording
PEOPLE_MIN_PROB = 0.1  # below this the tagger isn't really hearing it
PEOPLE_MIN_REF = 0.2  # "as strong as it gets" is never lower, so a quiet recording's loudest blip isn't a peak


def _wav32k_chunks(wav32k: Path, seconds: int):
    """Mono 32 kHz float32 audio from a 16-bit WAV, `seconds` at a time."""
    with wave.open(str(wav32k), "rb") as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2 or f.getframerate() != PANNS_RATE:
            raise ValueError(
                f"{wav32k} must be 32 kHz mono 16-bit PCM, got {f.getframerate()} Hz, "
                f"{f.getnchannels()} channel(s), {8 * f.getsampwidth()}-bit"
            )
        while True:
            raw = f.readframes(seconds * PANNS_RATE)
            if not raw:
                break
            yield np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def people_sounds(wav32k: Path, tagger) -> dict[str, np.ndarray]:
    """Laughter and shouts heard in a 32 kHz mono 16-bit WAV: {"laughter",
    "shout"} -> 0..1 per second.

    For second s the tagger hears the 2 s around it, [s - 0.5, s + 1.5), and
    a group's probability is its strongest class there. Each group is then
    judged against its own level in this recording (its rolling 90 s median),
    so a stream that is always a bit laughy needs a real burst to score. A
    group none of whose classes are in `tagger.labels` stays at zero. Audio
    shorter than one second yields empty arrays."""
    names = {name: i for i, name in enumerate(tagger.labels)}
    index = {g: [names[c] for c in classes if c in names] for g, classes in GROUPS.items()}

    sr = PANNS_RATE
    half, width = sr // 2, 2 * sr
    heard: dict[str, list[np.ndarray]] = {g: [] for g in GROUPS}
    # buf holds samples from absolute offset `start`; half a second of silence
    # stands in before the start and after the end.
    buf = np.zeros(half, dtype=np.float32)
    start = -half
    total = 0
    s = 0

    def run(windows: list[np.ndarray]) -> None:
        if not windows:
            return
        probs = np.asarray(tagger.tag(np.stack(windows)))
        for g, ix in index.items():
            heard[g].append(probs[:, ix].max(axis=1) if ix else np.zeros(len(windows)))

    expected = max(1, (Path(wav32k).stat().st_size - 44) // 2 // sr)  # seconds, from the WAV size
    for chunk in _wav32k_chunks(Path(wav32k), PEOPLE_CHUNK_SECONDS):
        progress.step(s / expected)
        total += chunk.size
        buf = np.concatenate([buf, chunk])
        windows = []
        while (s + 1) * sr + half <= start + buf.size:
            a = s * sr - half - start
            windows.append(buf[a:a + width])
            s += 1
        run(windows)
        keep = s * sr - half - start
        buf, start = buf[keep:], start + keep

    seconds = total // sr
    if seconds < 1:
        return {g: np.zeros(0, dtype=np.float32) for g in GROUPS}
    buf = np.concatenate([buf, np.zeros(width, dtype=np.float32)])
    windows = []
    while s < seconds:
        a = s * sr - half - start
        windows.append(buf[a:a + width])
        s += 1
    run(windows)
    return {g: _people_strength(np.concatenate(v)[:seconds].astype(np.float32)) for g, v in heard.items()}


def _people_strength(p: np.ndarray) -> np.ndarray:
    """A sound group's probability per second as 0..1 against its own usual
    level here: its loudest moments score 1, its usual level 0."""
    level = _rolling_median(p, PEOPLE_BASELINE)
    ref = max(float(np.percentile(p, 99.5)), PEOPLE_MIN_REF)
    usual = float(np.median(p))
    strength = np.clip((p - level) / max(ref - usual, 0.05), 0.0, 1.0) * (p >= PEOPLE_MIN_PROB)
    return strength.astype(np.float32)
