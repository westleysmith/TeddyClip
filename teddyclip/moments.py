# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""Candidate moments: from "clip that" triggers, OBS markers, signal peaks and a
joke sweep, to a labeled, deduplicated and budgeted list of clips.

Adapted from Clips Kitty's duplicate prevention (`analysis/highlights.py`:
`_select_unique`, `_check_against_kept`, `_text_similarity`, `_chunk_segments`),
rerank (`analysis/fusion.py`: `_rerank`, `_parse_order`) and section-spread
selection (`longform/highlight_select.py`). Prompts are rewritten for couch humor.

Forced moments (kind "trigger" or "marker") are never dropped, never trimmed by
the model and never lengthened for being short: snap only clamps their start to 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

from teddyclip.llm import LLM
from teddyclip.transcribe import Segment

KINDS = ("trigger", "marker", "laughter", "joke", "loud", "game")  # best first
FORCED_KINDS = ("trigger", "marker")

MAX_OVERLAP = 0.40  # share of the shorter moment covered by the other
MAX_TEXT_SIMILARITY = 0.70
TITLE_WORDS = 8  # words of transcript used when the model gives no title
TITLE_CHARS = 60
MAX_TRIM_SHARE = 0.5  # trims that would cut more than this of a window are ignored
RERANK_BONUS = 6.0

SWEEP_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 10}, "quote": {"type": "string"}},
    "required": ["score", "quote"],
}
LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
        "title": {"type": "string"},
        "why": {"type": "string"},
        "trim_start": {"type": "number"},
        "trim_end": {"type": "number"},
    },
    "required": ["score", "title", "why", "trim_start", "trim_end"],
}
ORDER_SCHEMA = {
    "type": "object",
    "properties": {"order": {"type": "array", "items": {"type": "integer"}}},
    "required": ["order"],
}


@dataclass
class Moment:
    start: float
    end: float
    score: float
    kind: str
    title: str = ""
    why: str = ""
    events: list[str] = field(default_factory=list)
    keep: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def forced(self) -> bool:
        return self.kind in FORCED_KINDS


def load_prompt(name: str) -> str:
    """Text of `prompts/<name>.txt` at the repo root."""
    return (Path(__file__).parent.parent / "prompts" / f"{name}.txt").read_text(encoding="utf-8")


class _Blank(dict):
    """format_map source that turns a placeholder nobody filled into ''."""

    def __missing__(self, key: str) -> str:
        return ""


def _fill(prompt: str, **fields) -> str:
    return prompt.format_map(_Blank(fields))


def _num(value) -> float | None:
    """`value` as a finite float, or None for anything else (strings, bools, nan)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _text(m: Moment, segments: list[Segment]) -> str:
    """What is said inside the moment."""
    return " ".join(s.text.strip() for s in segments if s.end > m.start and s.start < m.end).strip()


def _lines(m: Moment, segments: list[Segment]) -> str:
    """Transcript lines in the moment, timed in seconds from the moment's start."""
    return "\n".join(
        f"[{max(0.0, s.start - m.start):.0f}s - {min(m.end, s.end) - m.start:.0f}s] {s.text.strip()}"
        for s in segments if s.end > m.start and s.start < m.end and s.text.strip()
    )


# candidates


def forced_windows(times: list[float], kind: str, pre: float = 45, gap: float = 0.3) -> list[Moment]:
    """One moment per "clip that" or marker time: [t - pre, t - gap], ending just
    before the phrase. Score 10. A time at or before `gap` leaves no window."""
    out = []
    for t in times:
        start, end = max(0.0, t - pre), t - gap
        if end > start:
            out.append(Moment(start, end, 10, kind))
    return out


def signal_windows(
    peaks: list[tuple[float, float, float]],
    signals: dict[str, np.ndarray],
) -> list[Moment]:
    """A moment per (start, end, peak) window. Its kind is the signal that is
    strongest inside the window (earlier in KINDS wins a tie; "loud" when no
    signal is given); its score is the peak times 10."""
    out = []
    for start, end, peak in peaks:
        lo, hi = max(0, int(start)), int(math.ceil(end))
        kind, best = "loud", -math.inf
        for k in KINDS:
            if k in FORCED_KINDS or k not in signals:
                continue
            chunk = np.asarray(signals[k])[lo:hi]
            if chunk.size and float(chunk.max()) > best:
                kind, best = k, float(chunk.max())
        out.append(Moment(float(start), float(end), float(peak) * 10, kind))
    return out


def sweep(
    segments: list[Segment],
    llm: LLM,
    prompt: str,
    slice_s: float = 120,
    overlap_s: float = 30,
) -> np.ndarray:
    """Per-second joke score 0..1: the model scores each transcript slice 1 to 10
    and score / 10 is spread over the slice's seconds (max where slices overlap).
    All zeros when the model is off or a slice gets no usable answer."""
    duration = max((s.end for s in segments), default=0.0)
    out = np.zeros(int(math.ceil(duration)), dtype=np.float32)
    if not llm.enabled or out.size == 0:
        return out
    step = max(1.0, slice_s - overlap_s)
    start = 0.0
    while start < duration:
        end = min(start + slice_s, duration)
        lines = "\n".join(
            f"[{s.start:.0f} - {s.end:.0f}] {s.text.strip()}"
            for s in segments if s.end > start and s.start < end and s.text.strip()
        )
        if lines:
            answer = llm.ask(_fill(prompt, transcript=lines), SWEEP_SCHEMA)
            score = _num(answer.get("score")) if answer else None
            if score is not None:
                level = min(max(score, 0.0), 10.0) / 10
                lo, hi = int(start), min(out.size, int(math.ceil(end)))
                out[lo:hi] = np.maximum(out[lo:hi], level)
        if start + slice_s >= duration:
            break
        start += step
    return out


# shaping


def snap(m: Moment, segments: list[Segment], min_s: float, max_s: float) -> Moment:
    """Start and end moved out to the segment boundaries around them, then the
    length clamped to min_s..max_s (cut or grown evenly on both sides). A forced
    moment keeps its window: only a start below 0 is clamped."""
    if m.forced:
        return replace(m, start=max(0.0, m.start), events=list(m.events))
    start, end = m.start, m.end
    for s in segments:
        if s.start <= start < s.end:
            start = s.start
        if s.start < end <= s.end:
            end = s.end
    if end - start > max_s:
        cut = (end - start - max_s) / 2
        start, end = start + cut, end - cut
    elif end - start < min_s:
        grow = (min_s - (end - start)) / 2
        start, end = start - grow, end + grow
        if start < 0:
            start, end = 0.0, end - start
        limit = max((s.end for s in segments), default=math.inf)
        if end > limit:
            start, end = max(0.0, start - (end - limit)), limit
    return replace(m, start=max(0.0, start), end=end, events=list(m.events))


def _same_moment(a: Moment, b: Moment, segments: list[Segment]) -> bool:
    overlap = min(a.end, b.end) - max(a.start, b.start)
    shorter = min(a.duration, b.duration)
    if overlap > 0 and shorter > 0 and overlap / shorter > MAX_OVERLAP:
        return True
    if not segments:
        return False
    text_a, text_b = _text(a, segments), _text(b, segments)
    if not text_a or not text_b:
        return False
    matcher = SequenceMatcher(None, text_a, text_b)
    # The two cheap upper bounds rule out most pairs before the full ratio.
    return (
        matcher.real_quick_ratio() > MAX_TEXT_SIMILARITY
        and matcher.quick_ratio() > MAX_TEXT_SIMILARITY
        and matcher.ratio() > MAX_TEXT_SIMILARITY
    )


def _join(a: Moment, b: Moment) -> Moment:
    """One moment covering both: the better kind (and its words), the best score."""
    first, second = (a, b) if KINDS.index(a.kind) <= KINDS.index(b.kind) else (b, a)
    events = list(a.events) + [e for e in b.events if e not in a.events]
    return Moment(
        start=min(a.start, b.start),
        end=max(a.end, b.end),
        score=max(a.score, b.score),
        kind=first.kind,
        title=first.title or second.title,
        why=first.why or second.why,
        events=events,
        keep=a.keep or b.keep,
    )


def merge(moments: list[Moment], segments: list[Segment]) -> list[Moment]:
    """Moments that overlap over 40 percent in time or say over 70 percent the
    same words become one (repeated until nothing more merges). Returned by start."""
    out: list[Moment] = []
    for m in sorted(moments, key=lambda m: m.start):
        m = replace(m, events=list(m.events))
        while True:
            hit = next((o for o in out if _same_moment(o, m, segments)), None)
            if hit is None:
                break
            out.remove(hit)
            m = _join(hit, m)
        out.append(m)
    return sorted(out, key=lambda m: m.start)


# local model


def _snippet(text: str) -> str:
    return " ".join(text.split()[:TITLE_WORDS])


def label(
    moments: list[Moment],
    segments: list[Segment],
    llm: LLM,
    prompt: str,
    people: list[str],
) -> list[Moment]:
    """Title, reason, score and optional trims from the model, one call per moment.
    The model's score is averaged with the moment's own. Trims (seconds to cut
    from the start and the end) apply only to non-forced moments, and not when
    they would cut more than half. Without an answer the title is the first
    words of the transcript and the reason is the kind."""
    out = []
    for m in moments:
        text = _text(m, segments)
        answer = None
        if llm.enabled:
            events = ", ".join([m.kind] + m.events)
            answer = llm.ask(
                _fill(prompt, transcript=_lines(m, segments), events=events, people=", ".join(people)),
                LABEL_SCHEMA,
            )
        if not isinstance(answer, dict):
            out.append(replace(m, title=_snippet(text) or m.kind, why=m.kind, events=list(m.events)))
            continue
        title, why = answer.get("title"), answer.get("why")
        title = title.strip()[:TITLE_CHARS].rstrip() if isinstance(title, str) else ""
        why = why.strip() if isinstance(why, str) else ""
        new = replace(m, title=title or _snippet(text) or m.kind, why=why or m.kind, events=list(m.events))
        given = _num(answer.get("score"))
        if given is not None and not m.forced:
            new.score = (m.score + min(max(given, 1.0), 10.0)) / 2
        if not m.forced:
            cut_start = max(0.0, _num(answer.get("trim_start")) or 0.0)
            cut_end = max(0.0, _num(answer.get("trim_end")) or 0.0)
            if cut_start + cut_end <= MAX_TRIM_SHARE * m.duration:
                new.start, new.end = m.start + cut_start, m.end - cut_end
        out.append(new)
    return out


def _repair_order(raw, n: int) -> list[int] | None:
    """Valid first occurrences from the model's order, missing indices appended
    in original order. None when nothing in it is usable."""
    if not isinstance(raw, list):
        return None
    seen: list[int] = []
    for i in raw:
        if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n and i not in seen:
            seen.append(i)
    if not seen:
        return None
    return seen + [i for i in range(n) if i not in seen]


def rerank(moments: list[Moment], llm: LLM, prompt: str, top: int = 15) -> list[Moment]:
    """One call comparing the `top` highest-scoring moments head to head. The
    rank only raises a score, by 6 * (1 - position / count). The list comes back
    in its input order; an unusable answer changes nothing."""
    ranked = sorted(range(len(moments)), key=lambda i: moments[i].score, reverse=True)[:top]
    if not llm.enabled or len(ranked) < 2:
        return [replace(m, events=list(m.events)) for m in moments]
    lines = "\n".join(
        f"{n}: [{moments[i].start:.0f}s-{moments[i].end:.0f}s] {moments[i].kind}, "
        f"score {moments[i].score:.0f} | {moments[i].title} | {moments[i].why}"
        for n, i in enumerate(ranked)
    )
    answer = llm.ask(
        _fill(prompt, count=len(ranked), candidates=lines, transcript=lines), ORDER_SCHEMA
    )
    order = _repair_order(answer.get("order") if isinstance(answer, dict) else None, len(ranked))
    out = [replace(m, events=list(m.events)) for m in moments]
    if order is None:
        return out
    for position, n in enumerate(order):
        out[ranked[n]].score += RERANK_BONUS * (1 - position / len(ranked))
    return out


# selection


def select(
    moments: list[Moment],
    duration: float,
    max_clips: int,
    sections: int = 8,
    cap: float = 0.22,
) -> list[Moment]:
    """Marks `keep` on every forced moment (even beyond max_clips), then on the
    best of the rest while fewer than max_clips are kept and no eighth (`sections`)
    of the recording holds more than ceil(cap * max_clips). All moments come back
    by start; the input is untouched."""
    out = [replace(m, keep=m.forced, events=list(m.events)) for m in moments]
    section_len = duration / sections if duration > 0 else math.inf
    limit = math.ceil(cap * max_clips)
    used = [0] * sections

    def section(m: Moment) -> int:
        return min(sections - 1, max(0, int(m.start / section_len)))

    kept = 0
    for m in out:
        if m.keep:
            kept += 1
            used[section(m)] += 1
    for m in sorted((m for m in out if not m.keep), key=lambda m: m.score, reverse=True):
        if kept >= max_clips:
            break
        if used[section(m)] >= limit:
            continue
        m.keep = True
        kept += 1
        used[section(m)] += 1
    return sorted(out, key=lambda m: m.start)
