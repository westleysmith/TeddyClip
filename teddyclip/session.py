"""A session's own record, kept in `.cache/sessions/<session>/session.json`:
the transcript, laughter and yelling per second, the suggested clips and
the clips made from them. The analysis writes it; the editor reads it and
adds to `made` when a clip is cut."""

from __future__ import annotations

import contextlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np

from teddyclip.config import Config
from teddyclip.moments import TITLE_WORDS, Moment
from teddyclip.transcribe import Segment

VERSION = 1
FILE_NAME = "session.json"
SAVE_TRIES = 10


def session_dir(cfg: Config, name: str) -> Path:
    return cfg.paths.notes / name


def _cue(values: np.ndarray, seconds: int) -> list[float]:
    """One value per second for `seconds` seconds, rounded to 2 decimals."""
    out = np.zeros(seconds, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)[:seconds]
    out[: values.size] = values
    return [round(float(v), 2) for v in out]


def _said(segments: list[Segment], start: float, end: float) -> str:
    text = " ".join(s.text.strip() for s in segments if s.end > start and s.start < end)
    return " ".join(text.split()[:TITLE_WORDS])


def build(name: str, recording: Path | str, preview: Path | str | None, duration: float,
          segments: list[Segment], laughter: np.ndarray, yelling: np.ndarray,
          moments: list[Moment]) -> dict:
    """The session file's contents. Suggestions are the kept moments in time
    order, numbered from 1, clamped to the recording."""
    seconds = math.ceil(duration)
    suggestions = []
    for number, m in enumerate(sorted((m for m in moments if m.keep), key=lambda m: m.start), start=1):
        start = round(min(max(m.start, 0.0), duration), 1)
        end = round(min(max(m.end, 0.0), duration), 1)
        suggestions.append({
            "id": number, "start": start, "end": end, "kind": m.kind, "score": round(m.score, 1),
            "title": " ".join(m.title.split()) or _said(segments, start, end),
            "why": m.why, "events": list(m.events),
        })
    return {
        "version": VERSION,
        "name": name,
        "recording": str(recording),
        "preview": str(preview) if preview else None,
        "duration": round(float(duration), 2),
        "segments": [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments],
        "cues": {"laughter": _cue(laughter, seconds), "yelling": _cue(yelling, seconds)},
        "suggestions": suggestions,
        "made": [],
    }


def save(cfg: Config, data: dict) -> Path:
    """Write the session file whole or not at all."""
    path = session_dir(cfg, data["name"]) / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        # Windows refuses to replace a file another thread is reading for a
        # moment (the main page polls every session file), so try a few times.
        for attempt in range(SAVE_TRIES):
            try:
                os.replace(tmp, path)
                return path
            except PermissionError:
                if attempt == SAVE_TRIES - 1:
                    raise
                time.sleep(0.1)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def load(cfg: Config, name: str) -> dict | None:
    """The session file, or None when there is none or it cannot be read."""
    path = session_dir(cfg, name) / FILE_NAME
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return None


def record_made(cfg: Config, name: str, entry: dict, replace: str | None = None) -> dict:
    """Note a clip made from this session (dropping the one it replaces, and
    any older entry for the same file), save, and return the session."""
    data = load(cfg, name)
    if data is None:
        raise FileNotFoundError(f"No session named {name}")
    gone = {entry["file"].lower()} | ({replace.lower()} if replace else set())
    data["made"] = [m for m in data.get("made", []) if m.get("file", "").lower() not in gone] + [entry]
    save(cfg, data)
    return data
