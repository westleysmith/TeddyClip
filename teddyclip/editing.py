"""Cutting the range Teddy picked in the editor into a clip. Cuts run one at
a time (a lock, not the analysis job), so clips can be made from one session
while TeddyClip is still finding clips in another."""

from __future__ import annotations

import math
import threading
from pathlib import Path

from teddyclip import media, session
from teddyclip.config import Config
from teddyclip.moments import TITLE_WORDS
from teddyclip.output import MAX_TITLE_CHARS, UNSAFE_FILENAME_CHARS, _unique_name

MIN_CLIP_SECONDS = 1.0
MAX_CLIP_SECONDS = 600.0
_cutting = threading.Lock()


class CutError(ValueError):
    """Why a clip could not be made, in words for the person using the app."""


def _clean(text: str) -> str:
    cleaned = " ".join(UNSAFE_FILENAME_CHARS.sub("", text or "").split())
    return cleaned.strip(" .")[:MAX_TITLE_CHARS].strip(" .")


def safe_title(title: str, fallback: str) -> str:
    """`title` as part of a Windows file name; what was said, or "clip", when nothing is left."""
    return _clean(title) or _clean(fallback) or "clip"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _said(data: dict, start: float, end: float) -> str:
    text = " ".join(s["text"] for s in data.get("segments", []) if s["end"] > start and s["start"] < end)
    return " ".join(text.split()[:TITLE_WORDS])


def _stamp(seconds: float) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s"


def cut_clip(cfg: Config, name: str, start: object, end: object, title: str,
             replace: str | None = None, suggestion: int | None = None) -> Path:
    """Cut `start`..`end` of session `name`'s original recording into its clip
    folder as "<0h05m41s> - <title>.mp4" (" (2)" and so on when taken), note it
    in the session file, and return it. With `replace`, that clip of the
    session is swapped for the new one. Raises CutError with a plain reason."""
    data = session.load(cfg, name)
    if data is None:
        raise CutError("That session is gone. Close the editor and find clips again.")
    start, end = _number(start), _number(end)
    if start is None or end is None:
        raise CutError("The clip's start and end must be times in seconds.")
    duration = float(data.get("duration") or 0.0)
    start, end = max(0.0, start), min(end, duration)
    if end - start < MIN_CLIP_SECONDS:
        raise CutError("A clip has to be at least 1 second long. Move its end after its start.")
    if end - start > MAX_CLIP_SECONDS:
        raise CutError("A clip can be at most 10 minutes long. Move its start or end closer together.")
    recording = Path(data.get("recording", ""))
    if not recording.is_file():
        raise CutError(f"The recording is missing ({recording}). It may have been moved or deleted.")
    folder = cfg.paths.clips / name
    if replace is not None:
        if (not isinstance(replace, str) or replace != Path(replace).name or not replace.lower().endswith(".mp4")
                or not (folder / replace).is_file()):
            raise CutError("That clip to replace is not in this session any more.")
    clip_title = safe_title(title, _said(data, start, end))
    with _cutting:
        folder.mkdir(parents=True, exist_ok=True)
        taken = {p.name.lower() for p in folder.glob("*.mp4")} - ({replace.lower()} if replace else set())
        file = _unique_name(f"{_stamp(start)} - {clip_title}.mp4", taken)
        clip = media.cut(recording, start, end, folder / file)
        if replace and replace.lower() != file.lower():
            (folder / replace).unlink(missing_ok=True)
        session.record_made(cfg, name, {"file": file, "start": round(start, 1), "end": round(end, 1),
                                        "title": clip_title, "suggestion": suggestion}, replace=replace)
    return clip
