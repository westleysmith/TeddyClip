# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""Per-game on-screen text events (YOU DIED, WASTED, ...).

Adapted from Clips Kitty's `analysis/game_text.py` (`_norm`, `Lexicon`, the
`read_frame` banner filter and the `_read_windows` frame budget). Games announce
their moments in big letters near the middle of the screen, so only the center
of a few sampled frames is read, and only text tall enough to be a banner counts
(a stream's chat overlay and the HUD are smaller).

OCR is RapidOCR (PaddleOCR models on onnxruntime), created lazily on first use.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from pathlib import Path

from teddyclip.media import read_frames
from teddyclip.moments import Moment

BANNER_HEIGHT = 0.035  # a banner's letters are at least this share of the frame height
MIN_CONFIDENCE = 0.6
CENTER = 0.6  # share of the frame width and height that is read, around the middle
WHOLE_WORD = 5  # Latin terms this short only match as a whole word
# What the OCR often reads one letter as, folded together on both sides.
# "l" (a lowercase L) is read for "I" often enough that both fold to "I".
_FOLD = str.maketrans({"Q": "O", "0": "O", "1": "I", "5": "S", "L": "I"})
_SEPARATORS = re.compile(r"[\s:!?.,|/\\\[\]()_\-]+")

_engine = None


def game_profile(recording: Path, inbox: Path, games: dict[str, str]) -> str:
    """Profile for a recording: the inbox subfolder name first, then the file
    name, each matched case-insensitively against the `games` keys. Else "generic"."""
    recording, inbox = Path(recording), Path(inbox)
    try:
        parts = recording.relative_to(inbox).parts
    except ValueError:
        parts = (recording.name,)
    names = [parts[0]] if len(parts) > 1 else []
    names.append(recording.stem)
    for name in names:
        lowered = name.lower()
        for key, profile in games.items():
            if key.lower() in lowered:
                return profile
    return "generic"


def _norm(text: str) -> str:
    """Upper case, no accents, letters and digits only, the usual misreads folded."""
    t = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in t.upper() if ch.isalnum() and not unicodedata.combining(ch)).translate(_FOLD)


class Lexicon:
    """Terms to find in what the OCR read. Short Latin ones (ACE, GOAL) only as a
    whole word, so ACE is not found in PLACE."""

    def __init__(self, terms: list[str]):
        self.terms = [(str(t), _norm(t)) for t in terms or [] if _norm(t)]

    def find(self, text: str) -> list[str]:
        compact = _norm(text)
        words = {_norm(w) for w in _SEPARATORS.split(str(text))}
        hits = []
        for term, n in self.terms:
            whole = n.isascii() and len(n) <= WHOLE_WORD
            if (n in words or n == compact) if whole else n in compact:
                hits.append(term)
        return hits


def banner_texts(ocr_result, frame_height: int, min_height: float = BANNER_HEIGHT,
                 min_confidence: float = MIN_CONFIDENCE) -> list[str]:
    """Texts from RapidOCR output whose box is at least `min_height` of the frame
    height. `ocr_result` is a list of [box_points, text, score], or None."""
    texts = []
    for box, text, conf in ocr_result or []:
        if float(conf) < min_confidence:
            continue
        ys = [p[1] for p in box]
        if (max(ys) - min(ys)) >= min_height * frame_height:
            texts.append(text)
    return texts


def _default_ocr(img):
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine(img, use_cls=False)


def _center(img):
    h, w = img.shape[:2]
    mh, mw = round(h * (1 - CENTER) / 2), round(w * (1 - CENTER) / 2)
    return img[mh:h - mh, mw:w - mw]


def screen_events(video: Path, moments: list[Moment], lexicon: Lexicon, weight: float = 0.6,
                  step: float = 2.0, max_frames: int = 160, ocr=None) -> list[Moment]:
    """Read the center of a frame every `step` seconds inside each moment (at most
    `max_frames` in all, strongest moments first). Lexicon hits are added to the
    moment's events once each, the first hit adds `10 * weight` to its score, and
    a `loud` moment becomes `game`. Returns new moments, in the order given."""
    ocr = ocr or _default_ocr
    plan: dict[int, list[float]] = {}
    left = max_frames
    for i in sorted(range(len(moments)), key=lambda i: -moments[i].score):
        m, times = moments[i], []
        t = m.start + step / 2
        while t < m.end and len(times) < left:
            times.append(t)
            t += step
        left -= len(times)
        plan[i] = times
    out = []
    for i, m in enumerate(moments):
        hits: list[str] = []
        for _t, frame in read_frames(video, plan[i]):
            result, _elapsed = ocr(_center(frame))
            for text in banner_texts(result, frame.shape[0]):
                hits.extend(h for h in lexicon.find(text) if h not in hits)
        if not hits:
            out.append(replace(m, events=list(m.events)))
            continue
        out.append(replace(
            m,
            events=[*m.events, *(h for h in hits if h not in m.events)],
            score=m.score + 10 * weight,
            kind="game" if m.kind == "loud" else m.kind,
        ))
    return out
