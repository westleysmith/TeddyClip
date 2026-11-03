# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""Everything a finished recording leaves behind: the clips, moments.csv, a
DaVinci Resolve marker EDL, YouTube chapters, the highlight video, and the
original moved into Done with chapter markers.

The chapter rules and the `_timestamp` helper come from Clips Kitty's
longform/chapters.py. The highlight join flow is a trimmed version of its
longform/assemble.py: clips are already encoded identically by `media.cut`, so
they are joined losslessly (no outro card, progress callback or cancel hook).
Clip naming, the CSV, the EDL and the archive step are TeddyClip's own.

Every ffmpeg call goes through the `media` module (called as `media.cut`, etc.).
These functions take plain data and never decide what to keep: a moment is
output only when its `keep` flag is set.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from teddyclip import media
from teddyclip.moments import Moment

CLIP_THAT_PREFIX = "Clip that - "
MAX_TITLE_CHARS = 80
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CLIP_FILE = re.compile(r"^(\d+)h(\d{2})m(\d{2})s - (.*)$")

# YouTube ignores the whole chapter list if any rule is broken (Clips Kitty chapters.py).
MIN_CHAPTERS = 3
MIN_CHAPTER_SECONDS = 10.0

CSV_COLUMNS = ["keep", "start", "end", "score", "kind", "title", "why", "events", "file"]

EDL_COLORS = {
    "trigger": "ResolveColorRed",
    "marker": "ResolveColorRed",
    "laughter": "ResolveColorYellow",
    "joke": "ResolveColorBlue",
    "game": "ResolveColorPurple",
    "loud": "ResolveColorGreen",
}

ARCHIVE_TOLERANCE_SECONDS = 0.5


def _kept(moments: list[Moment]) -> list[Moment]:
    """Kept moments in time order."""
    return sorted((m for m in moments if m.keep), key=lambda m: m.start)


# clips


def _file_title(title: str) -> str:
    cleaned = " ".join(UNSAFE_FILENAME_CHARS.sub("", title or "").split())
    cleaned = cleaned.strip(" .")[:MAX_TITLE_CHARS].strip(" .")
    return cleaned or "moment"


def clip_name(m: Moment) -> str:
    total = int(m.start)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    prefix = CLIP_THAT_PREFIX if m.kind == "trigger" else ""
    return f"{hours}h{minutes:02d}m{seconds:02d}s - {prefix}{_file_title(m.title)}.mp4"


def _unique_name(name: str, used: set[str]) -> str:
    stem, ext = name[: -len(".mp4")], ".mp4"
    candidate, n = name, 1
    while candidate.lower() in used:  # Windows folders are case-insensitive
        n += 1
        candidate = f"{stem} ({n}){ext}"
    used.add(candidate.lower())
    return candidate


def write_clips(src: Path, moments: list[Moment], out_dir: Path) -> list[Path]:
    """Cut every kept moment into `out_dir`. Colliding names get " (2)", " (3)"."""
    kept = _kept(moments)
    if not kept:
        return []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    return [media.cut(src, m.start, m.end, out_dir / _unique_name(clip_name(m), used)) for m in kept]


# moments.csv


def _hms(seconds: float) -> str:
    hours, rest = divmod(max(0, round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def write_moments_csv(moments: list[Moment], path: Path) -> None:
    """Every candidate, kept or not. utf-8-sig so Excel opens accents correctly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for m in moments:
            writer.writerow(
                [
                    "yes" if m.keep else "no",
                    _hms(m.start),
                    _hms(m.end),
                    f"{m.score:.1f}",
                    m.kind,
                    m.title,
                    m.why,
                    "; ".join(m.events),
                    clip_name(m) if m.keep else "",
                ]
            )


# Resolve marker EDL


def _ascii_text(text: str) -> str:
    """ASCII only, no pipes or line breaks (Resolve's marker fields use | as a separator).
    Accents fold to their base letter, apostrophes stay."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.replace("|", " ").split())


def _parse_timecode(text: str, base: int) -> int:
    try:
        hours, minutes, seconds, frames = (int(part) for part in text.strip().split(":"))
    except ValueError:
        raise ValueError(f"timeline_start must look like 01:00:00:00, got {text!r}") from None
    return ((hours * 60 + minutes) * 60 + seconds) * base + frames


def _timecode(frames: int, base: int) -> str:
    seconds, ff = divmod(frames, base)
    minutes, ss = divmod(seconds, 60)
    hh, mm = divmod(minutes, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def write_resolve_edl(moments: list[Moment], path: Path, fps: float, timeline_start: str, title: str) -> None:
    """CMX 3600 marker EDL for Resolve's "Import > Timeline Markers from EDL".

    Positions are real frame indices (`round(t * fps)`) shown with timebase
    `round(fps)`, so 59.94 footage does not drift 3.6 s per hour. The marker EDL
    has no note field, so `why` lives only in the CSV.
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    base = round(fps)
    origin = _parse_timecode(timeline_start, base)
    lines = [f"TITLE: {_ascii_text(title)}", "FCM: NON-DROP FRAME"]
    for n, m in enumerate(_kept(moments), start=1):
        first = origin + round(m.start * fps)
        tc_in, tc_out = _timecode(first, base), _timecode(first + 1, base)
        lines += [
            "",
            f"{n:03d}  001      V     C        {tc_in} {tc_out} {tc_in} {tc_out}",
            f" |C:{EDL_COLORS.get(m.kind, 'ResolveColorBlue')} |M:{_ascii_text(m.title) or 'moment'} |D:{max(1, round(m.duration * fps))}",
        ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))


# YouTube chapters


def _timestamp(seconds: float) -> str:
    """0:00, 4:07, or 1:02:33 past the hour. Seconds are floored so a chapter
    never starts before the cut it names."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def youtube_chapters(entries: list[tuple[float, float, str]]) -> list[str]:
    """Description lines for (start, end, title) positions in the finished video,
    or [] when YouTube would silently ignore them: the first must start at 0:00,
    there must be at least three, each at least 10 s, ascending."""
    if len(entries) < MIN_CHAPTERS:
        return []
    if int(entries[0][0]) != 0:
        return []
    if any(end - start < MIN_CHAPTER_SECONDS for start, end, _ in entries):
        return []
    starts = [int(start) for start, _, _ in entries]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        return []
    lines = []
    for index, (start, _, title) in enumerate(entries, start=1):
        label = " ".join((title or "").split())[:MAX_TITLE_CHARS].rstrip() or f"Moment {index}"
        lines.append(f"{_timestamp(start)} {label}")
    return lines


def _no_chapters_note(durations: list[float]) -> str:
    if len(durations) < MIN_CHAPTERS:
        return (
            f"No chapters: this video has fewer than {MIN_CHAPTERS} clips, "
            f"and YouTube ignores a chapter list shorter than that.\n"
        )
    if any(d < MIN_CHAPTER_SECONDS for d in durations):
        return (
            f"No chapters: a clip is under {MIN_CHAPTER_SECONDS:g} seconds, "
            f"and YouTube ignores the whole list when any chapter is that short.\n"
        )
    return "No chapters: the clips do not meet YouTube's chapter rules.\n"


# highlight video


def _clip_order(path: Path) -> tuple[int, str]:
    """Time order from the `<h>h<mm>m<ss>s` prefix (plain name order breaks past 9 hours)."""
    found = CLIP_FILE.match(path.stem)
    if found is None:
        return (10**9, path.name.lower())
    hours, minutes, seconds = (int(found.group(i)) for i in (1, 2, 3))
    return ((hours * 60 + minutes) * 60 + seconds, path.name.lower())


def _clip_title(path: Path) -> str:
    found = CLIP_FILE.match(path.stem)
    title = found.group(4) if found else path.stem
    if title.startswith(CLIP_THAT_PREFIX):
        title = title[len(CLIP_THAT_PREFIX):]
    return title


def build_highlight(clip_dir: Path, video_out: Path, chapters_out: Path) -> Path | None:
    """Join every clip in `clip_dir` in time order and write the chapter list.
    Returns None when the folder has no clips."""
    video_out = Path(video_out)
    skip = video_out.resolve()
    clips = sorted(
        (p for p in Path(clip_dir).glob("*.mp4") if p.resolve() != skip),
        key=_clip_order,
    )
    if not clips:
        return None
    durations = [media.probe(p).duration for p in clips]
    entries, offset = [], 0.0
    for clip, length in zip(clips, durations):
        entries.append((offset, offset + length, _clip_title(clip)))
        offset += length
    media.concat(clips, video_out)
    lines = youtube_chapters(entries)
    chapters_out = Path(chapters_out)
    chapters_out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n" if lines else _no_chapters_note(durations)
    chapters_out.write_text(text, encoding="utf-8")
    return video_out


# archive


def archive_original(src: Path, done_dir: Path, moments: list[Moment], name: str,
                     keep_source: bool = False) -> Path:
    """Remux `src` into `done_dir/<name><src extension>` with the kept moments as
    chapters, check the copy is as long as the original, then delete `src`
    (unless `keep_source`). On any failure the partial output is removed and
    `src` is left alone."""
    src, done_dir = Path(src), Path(done_dir)
    dst = done_dir / f"{name}{src.suffix or '.mp4'}"
    if dst.exists():
        raise FileExistsError(f"{dst} already exists, so the original was not moved. Rename or remove it and try again.")
    done_dir.mkdir(parents=True, exist_ok=True)
    kept = _kept(moments)
    chapters = [media.Chapter(m.start, m.end, " ".join(m.title.split()) or "moment") for m in kept]
    if kept and kept[0].start > 1.0:
        # The mov muxer makes chapters gapless, so without this the first moment's chapter would start at 0.
        chapters.insert(0, media.Chapter(0, kept[0].start, "Start"))
    try:
        media.write_chapters(src, dst, chapters)
        want, got = media.probe(src).duration, media.probe(dst).duration
        if abs(got - want) > ARCHIVE_TOLERANCE_SECONDS:
            raise RuntimeError(
                f"The archived copy's duration ({got:.1f} s) does not match the original ({want:.1f} s), "
                "so the original was kept."
            )
        if not keep_source:
            src.unlink()
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return dst
