"""The `teddyclip` command: process the inbox, one recording, a highlight
video, or check that everything TeddyClip needs is installed."""

from __future__ import annotations

import argparse
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
import yaml

from teddyclip import progress
from teddyclip.config import Config, load_config
from teddyclip.detectors import Lexicon, game_profile, screen_events
from teddyclip.llm import LLM
from teddyclip.media import CPU_ARGS, encoder_args, extract_audio, find_tool, probe
from teddyclip.moments import (
    forced_windows,
    label,
    load_prompt,
    merge,
    rerank,
    select,
    signal_windows,
    snap,
    sweep,
)
from teddyclip.output import (
    archive_original,
    build_highlight,
    write_clips,
    write_moments_csv,
    write_resolve_edl,
)
from teddyclip.panns import LABELS_NAME, SAMPLE_RATE as PANNS_RATE, WEIGHTS_NAME, Tagger, ensure_assets
from teddyclip.signals import (
    SAMPLE_RATE as WHISPER_RATE,
    audio_features,
    contributions,
    find_triggers,
    fuse,
    pct,
    peak_windows,
    people_sounds,
    voice_jump,
)
from teddyclip.transcribe import all_words, gpu_ready, release, transcribe

VIDEO_SUFFIXES = {".mp4", ".mkv"}
WHISPER_DEVICES = ("auto", "cpu")
QUIET_SECONDS = 60


# finding finished recordings


def _opens_exclusively(path: Path) -> bool:
    """Whether no other program has the file open. On Windows the file is
    opened for appending with no sharing at all, which fails while OBS (or a
    copy) still holds it; nothing is written."""
    if os.name != "nt":
        try:
            with open(path, "ab"):
                return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    file_append_data, open_existing, normal = 0x0004, 3, 0x80
    handle = create(str(path), file_append_data, 0, None, open_existing, normal, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        return False
    kernel32.CloseHandle(handle)
    return True


def is_finished(path: Path, quiet_seconds: float = QUIET_SECONDS, now: float | None = None) -> bool:
    """True when the file has not changed for `quiet_seconds` and no other
    program has it open, so a recording in progress is never touched."""
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return False
    if (time.time() if now is None else now) - mtime < quiet_seconds:
        return False
    return _opens_exclusively(Path(path))


# one recording


def _folder_name(path: Path, cfg: Config, mtime: float) -> str:
    """"<date> <game>": the recording's date and its inbox subfolder (or its
    file name). " (2)", " (3)" are added while that name is taken in 2 Clips or Done."""
    date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    try:
        parts = path.relative_to(cfg.paths.inbox).parts
    except ValueError:
        parts = (path.name,)
    base = f"{date} {parts[0] if len(parts) > 1 else path.stem}"
    name, n = base, 1
    suffix = path.suffix or ".mp4"
    while (cfg.paths.clips / name).exists() or (cfg.paths.done / f"{name}{suffix}").exists():
        n += 1
        name = f"{base} ({n})"
    return name


def _in_inbox(path: Path, cfg: Config) -> bool:
    return Path(path).resolve().is_relative_to(cfg.paths.inbox.resolve())


def _count(n: int, thing: str) -> str:
    return f"{n} {thing}" if n == 1 else f"{n} {thing}s"


def _highest(*signals: np.ndarray) -> np.ndarray:
    """Per-second maximum of signals that may differ in length (short ones count as 0 past their end)."""
    out = np.zeros(max(s.size for s in signals), dtype=np.float32)
    for s in signals:
        out[: s.size] = np.maximum(out[: s.size], s)
    return out


ARCHIVE_ROOM = 1.01  # the copy in Done is about as big as the original; a little to spare


def _check_room_for_original(src: Path, done: Path) -> None:
    """Raise a plain error when the Done drive cannot hold a copy of `src`."""
    need = Path(src).stat().st_size * ARCHIVE_ROOM
    free = shutil.disk_usage(done).free
    if free < need:
        drive = Path(done).drive or Path(done).anchor or str(done)
        raise RuntimeError(
            f"Not enough free space on {drive} to file the original in Done: "
            f"need about {max(need / 1e9, 0.1):.1f} GB, {free / 1e9:.1f} GB is free. "
            "Free up some space and run TeddyClip again."
        )


def _mark_incomplete(out_dir: Path) -> Path | None:
    """Rename the clip folder of a failed run to "<name> (incomplete)", or
    "(incomplete 2)" and so on when that is taken, so the next run gets the
    clean name. Returns the new folder, or None when there was nothing to
    rename or the rename itself failed."""
    if not out_dir.is_dir():
        return None
    target, n = out_dir.with_name(f"{out_dir.name} (incomplete)"), 1
    while target.exists():
        n += 1
        target = out_dir.with_name(f"{out_dir.name} (incomplete {n})")
    try:
        out_dir.rename(target)
    except OSError:
        return None
    print(f"The clips made so far are in \"{target.name}\".")
    return target


def process_recording(path: Path, cfg: Config) -> Path:
    """Find the moments in one recording, cut them into a clip folder with
    moments.csv and Resolve markers, and move the original into Done with
    chapters. A recording from outside the inbox is copied there instead and
    left where it is. Returns the clip folder."""
    path = Path(path)
    paths = cfg.paths
    paths.ensure()
    stat = path.stat()
    name = _folder_name(path, cfg, stat.st_mtime)
    out_dir = paths.clips / name
    print(f"\nProcessing {path.name} into \"{name}\"")

    info = probe(path)
    if info.audio_tracks == 0:
        raise RuntimeError(
            f"{path.name} has no sound track. "
            "Check OBS Settings > Output > Recording > Audio Track, then record again."
        )
    cache = paths.cache / f"{path.name}-{stat.st_size}-{int(stat.st_mtime)}"
    # Shares of the progress bar per stage, sized for transcribing on a CPU.
    print("Extracting audio...")
    with progress.band(0.00, 0.05, "Extracting audio"):
        wav16 = extract_audio(path, cache / "audio16k.wav", WHISPER_RATE, cfg.audio_track)
        wav32 = extract_audio(path, cache / "audio32k.wav", PANNS_RATE, cfg.audio_track)

    print("Transcribing...")
    with progress.band(0.05, 0.60, "Transcribing what you said"):
        segments = transcribe(wav16, cache, cfg.whisper_model, hotwords=cfg.triggers,
                              language=cfg.language, device=cfg.whisper_device)
    release()  # frees the GPU before Ollama is asked anything

    print("Measuring loudness...")
    with progress.band(0.60, 0.62, "Measuring loudness"):
        features = audio_features(wav16)
        jumps = voice_jump(features["loudness"])
    print("Listening for laughter and shouts...")
    with progress.band(0.62, 0.70, "Listening for laughter"):
        people = people_sounds(wav32, Tagger(*ensure_assets(paths.models)))
    laughter, shout = people["laughter"], people["shout"]

    llm = LLM(cfg.llm_url, cfg.llm_model, cache)
    if llm.enabled and not llm.available():
        print(f"Ollama is not running or model {cfg.llm_model} is not pulled: continuing without AI titles")
        llm = LLM(cfg.llm_url, "none", cache)
    if llm.enabled:
        print("Looking for jokes in the transcript...")
    with progress.band(0.70, 0.78, "Looking for jokes"):
        jokes = sweep(segments, llm, load_prompt("sweep"))

    spike = pct(features["spike"])
    fusing = {"laughter": laughter, "joke_sweep": jokes, "loudness": _highest(spike, pct(shout)), "voice_jump": jumps}
    fused = fuse(fusing, cfg.weights)
    # What each signal added to the fused score, to name the kind of each peak.
    parts = contributions(fusing, cfg.weights)
    triggers = find_triggers(all_words(segments), cfg.triggers)
    if triggers:
        print(f"Heard \"clip that\" {_count(len(triggers), 'time')}")
    candidates = (
        forced_windows(triggers, "trigger", pre=cfg.pre_trigger_seconds)
        + forced_windows([c.start for c in info.chapters], "marker", pre=cfg.pre_trigger_seconds)
        + signal_windows(
            peak_windows(fused),
            {"laughter": parts["laughter"], "joke": parts["joke_sweep"],
             "loud": _highest(parts["loudness"], parts["voice_jump"])},
        )
    )

    def snapped(moments):
        return [snap(m, segments, cfg.min_seconds, cfg.max_seconds) for m in moments]

    moments = snapped(merge(snapped(candidates), segments))

    terms = cfg.lexicons.get(game_profile(path, paths.inbox, cfg.games))
    if terms and moments:
        print("Reading on-screen text...")
        with progress.band(0.78, 0.83, "Reading on-screen text"):
            moments = screen_events(path, moments, Lexicon(terms), weight=cfg.weights["screen_text"])

    if llm.enabled and moments:
        print("Titling the moments...")
    with progress.band(0.83, 0.90, "Titling the moments"):
        moments = snapped(label(moments, segments, llm, load_prompt("label"), cfg.people))
        moments = rerank(moments, llm, load_prompt("rerank"))
    moments = select(moments, info.duration, cfg.max_clips)

    kept = sum(m.keep for m in moments)
    # Checked before anything is cut, so a full disk fails early and cleanly.
    _check_room_for_original(path, paths.done)
    print(f"Found {_count(len(moments), 'moment')}, cutting {_count(kept, 'clip')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with progress.band(0.90, 0.98, "Cutting clips"):
            write_clips(path, moments, out_dir)
        write_moments_csv(moments, out_dir / "moments.csv")
        write_resolve_edl(moments, out_dir / "Resolve markers.edl", info.fps, cfg.resolve_timeline_start, name)

        with progress.band(0.98, 1.00, "Filing the original in Done"):
            if _in_inbox(path, cfg):
                print("Moving the original to Done...")
                archive_original(path, paths.done, moments, name)
            else:
                print("Copying the original into Done (it is outside the inbox, so it stays where it is)...")
                archive_original(path, paths.done, moments, name, keep_source=True)
    except BaseException:
        _mark_incomplete(out_dir)
        raise
    # The transcript and AI answers stay cached; the audio is only needed again
    # if the recording is processed again, and costs over 1 GB per 4 hours.
    for wav in (wav16, wav32):
        wav.unlink(missing_ok=True)
    print(f"Finished: {out_dir}")
    return out_dir


# the inbox


def _describe(error: Exception) -> str:
    return str(error).strip() or type(error).__name__


_GENERIC_LINES = {"conversion failed!", "exiting normally, received signal 2."}


def _summary(why: str) -> str:
    """One line for the summary: the last line that says something. ffmpeg
    errors start with "ffmpeg could not ... (exit code N):" and end with
    "Conversion failed!"; the reason is in between."""
    lines = [line.strip() for line in why.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.lower() not in _GENERIC_LINES and not line.endswith(":"):
            return line
    return lines[0] if lines else why


def process_inbox(cfg: Config) -> int:
    """Process every finished .mp4 and .mkv under the inbox, one at a time. A
    recording that fails stays in the inbox and the rest carry on. Returns the
    number of failures."""
    cfg.paths.ensure()
    inbox = cfg.paths.inbox
    files = sorted(p for p in inbox.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)
    if not files:
        print(f"Nothing to do: there are no recordings in {inbox}")
        return 0
    # OBS's "Automatically remux to mp4" leaves the .mkv next to the .mp4 it made.
    remuxed = {(p.parent, p.stem.lower()) for p in files if p.suffix.lower() == ".mp4"}
    for path in [p for p in files if p.suffix.lower() == ".mkv" and (p.parent, p.stem.lower()) in remuxed]:
        print(f"Skipping {path.name}: it is a duplicate of {path.stem}.mp4 next to it (OBS remuxed it). "
              "Delete the .mkv once you no longer need it.")
        files.remove(path)

    processed: list[Path] = []
    failed: list[tuple[Path, str]] = []
    waiting: list[Path] = []
    for number, path in enumerate(files):
        if not is_finished(path):
            print(f"Skipping {path.name} for now: it is still being recorded or copied.")
            waiting.append(path)
            continue
        try:
            # Each recording takes an equal share of the progress bar.
            with progress.band(number / len(files), (number + 1) / len(files)):
                processed.append(process_recording(path, cfg))
        except Exception as e:
            print(f"Could not process {path.name}: {_describe(e)}")
            print("It stays in the inbox, so you can fix the problem and run TeddyClip again.")
            failed.append((path, _describe(e)))

    print(f"\nDone: {len(processed)} processed, {len(failed)} failed")
    for folder in processed:
        print(f"  Clips in {folder}")
    for path, why in failed:
        print(f"  Failed: {path.name} ({_summary(why)})")
    if waiting:
        print(f"  {len(waiting)} recording(s) still being written; run again once they are finished.")
    return len(failed)


# highlight


def highlight(folder: Path, cfg: Config) -> int:
    """Join the clips left in a clip folder into 3 Highlights, with chapters."""
    folder = Path(folder)
    if not folder.is_dir():
        print(f"No such folder: {folder}")
        return 1
    out = cfg.paths.highlights
    print(f"Joining the clips in \"{folder.name}\"...")
    try:
        video = build_highlight(folder, out / f"{folder.name}.mp4", out / f"{folder.name} - chapters.txt")
    except Exception as e:
        print(f"Could not build the highlight video: {_describe(e)}")
        return 1
    if video is None:
        print(f"There are no clips in {folder}, so there is nothing to join.")
        return 1
    print(f"Highlight video: {video}")
    print(f"YouTube chapters: {out / f'{folder.name} - chapters.txt'}")
    return 0


# check


def _line(status: str, text: str) -> None:
    print(f"[{status}] {text}")


def check(cfg: Config) -> int:
    """Print what is installed and working, with a fix for each problem.
    Returns the number of problems that stop TeddyClip working fully."""
    failures = 0

    has_ffmpeg = bool(find_tool("ffmpeg") and find_tool("ffprobe"))
    if has_ffmpeg:
        _line("ok", "ffmpeg and ffprobe found")
        if encoder_args() != CPU_ARGS:
            _line("ok", "NVENC works: clips are encoded on the NVIDIA GPU")
        else:
            _line("info", "NVENC is not available: clips are encoded on the CPU, which is slower")
    else:
        failures += 1
        _line("fail", "ffmpeg not found: run 'winget install Gyan.FFmpeg', then open a new window (README step 2)")
        _line("info", "NVENC not checked, because it needs ffmpeg")

    if cfg.whisper_device == "cpu":
        _line("info", "whisper_device: cpu in config.yaml, so whisper transcribes on the CPU and the GPU is not checked")
    else:
        usable, reason = gpu_ready()
        if usable:
            _line("ok", f"CUDA for whisper (whisper_device: auto): {reason}")
        else:
            _line("info", f"Whisper will transcribe on the CPU, which is slower (whisper_device: auto): {reason}")

    if cfg.llm_model == "none":
        _line("info", "AI titles are turned off (llm model is \"none\" in config.yaml)")
    else:
        url = cfg.llm_url.rstrip("/")
        try:
            requests.get(f"{url}/api/tags", timeout=5).raise_for_status()
            running = True
        except requests.RequestException:
            running = False
        if not running:
            failures += 1
            _line("fail", f"Ollama is not running at {url}: install it from ollama.com and start it")
        elif LLM(cfg.llm_url, cfg.llm_model, cfg.paths.cache).available():
            _line("ok", f"Ollama is running and has {cfg.llm_model}")
        else:
            failures += 1
            _line("fail", f"Ollama model {cfg.llm_model} is not pulled: run 'ollama pull {cfg.llm_model}'")

    if (cfg.paths.models / WEIGHTS_NAME).is_file() and (cfg.paths.models / LABELS_NAME).is_file():
        _line("ok", "Laughter and shout model (PANNs) is downloaded")
    else:
        _line("info", "Laughter and shout model (PANNs) is not downloaded yet: it downloads on the first run")

    try:
        import rapidocr_onnxruntime  # noqa: F401
        _line("ok", "RapidOCR loads (on-screen text like YOU DIED)")
    except Exception as e:
        failures += 1
        _line("fail", f"RapidOCR could not be loaded ({type(e).__name__}): run 'pip install rapidocr-onnxruntime'")

    try:
        cfg.paths.ensure()
        _line("ok", f"Folders are ready in {cfg.root}")
    except OSError as e:
        failures += 1
        _line("fail", f"Could not create the folders in {cfg.root}: {_describe(e)}. Set root in config.yaml.")

    print("\nEverything needed is working." if failures == 0 else f"\n{_count(failures, 'problem')} to fix.")
    return failures


# command line


def _check_config(cfg: Config) -> None:
    """Raise ValueError with a plain message for settings that would fail later."""
    if cfg.whisper_device not in WHISPER_DEVICES:
        raise ValueError(f"whisper_device must be auto or cpu, not {cfg.whisper_device!r}")
    if cfg.language is not None and not (isinstance(cfg.language, str) and cfg.language.strip()):
        raise ValueError(f"language must be a language code like en, or null to detect it, not {cfg.language!r}")
    for name, value in cfg.weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"weights: {name} must be a number like 0.6, not {value!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="teddyclip",
        description="Turn long gaming recordings into clips. With no command, every finished recording in the inbox is processed.",
    )
    parser.add_argument("--config", type=Path, help="config.yaml to use (default: config.yaml in the current folder)")
    commands = parser.add_subparsers(dest="command")
    one = commands.add_parser("process", help="process one recording")
    one.add_argument("file", type=Path)
    joined = commands.add_parser("highlight", help="join the clips left in a clip folder into a highlight video")
    joined.add_argument("folder", type=Path)
    commands.add_parser("check", help="check that ffmpeg, Ollama and the models are ready")
    commands.add_parser("ui", help="open the TeddyClip page in your web browser")
    args = parser.parse_args(argv)

    config_path = args.config or Path.cwd() / "config.yaml"
    if args.config is not None and not args.config.is_file():
        print(f"Config file not found: {args.config}")
        return 2
    try:
        cfg = load_config(args.config)
        _check_config(cfg)
    except (yaml.YAMLError, OSError, TypeError, ValueError) as e:
        print(f"Could not read the config file {config_path}:\n  {_describe(e)}")
        print("Fix it (or delete it to use the defaults) and try again.")
        return 2

    if args.command == "check":
        return 1 if check(cfg) else 0
    if args.command == "ui":
        from teddyclip.ui import serve
        return serve(cfg)
    if args.command == "highlight":
        return highlight(args.folder, cfg)
    if args.command == "process":
        if not args.file.is_file():
            print(f"No such file: {args.file}")
            return 1
        try:
            process_recording(args.file, cfg)
        except Exception as e:
            print(f"Could not process {args.file.name}: {_describe(e)}")
            return 1
        return 0
    return 1 if process_inbox(cfg) else 0
