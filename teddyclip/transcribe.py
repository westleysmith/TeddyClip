# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""Local speech-to-text with faster-whisper, cached as JSON next to the other
per-recording files so re-runs skip the expensive transcription step."""

from __future__ import annotations

import ctypes
import dataclasses
import gc
import inspect
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from teddyclip import progress


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


def all_words(segments: list[Segment]) -> list[Word]:
    """Every word of every segment, in order."""
    return [w for seg in segments for w in seg.words]


# GPU detection

def cuda_usable() -> tuple[bool, str]:
    """(usable, reason): whether faster-whisper can use an NVIDIA GPU here.

    The question is asked of CTranslate2, faster-whisper's own engine, not of
    PyTorch: the documented install uses the CPU build of PyTorch (all PANNs
    needs), which would always answer no. The reason string is always worth
    showing, since it explains why the CPU is being used."""
    try:
        import ctranslate2
    except Exception as e:
        return False, f"CTranslate2 did not load ({type(e).__name__})"
    try:
        count = ctranslate2.get_cuda_device_count()
    except Exception as e:
        # A diagnostic must never take the caller down.
        return False, f"could not check the GPU ({type(e).__name__})"
    if count <= 0:
        return False, "no NVIDIA GPU with a working driver was found"
    return True, "NVIDIA GPU found" if count == 1 else f"{count} NVIDIA GPUs found"


# faster-whisper's engine, CTranslate2, is built against CUDA 12 and loads
# cuBLAS 12 and cuDNN 9 by name the first time it runs on the GPU, not when the
# model loads. They come from NVIDIA's nvidia-cublas-cu12 and nvidia-cudnn-cu12
# wheels (the "gpu" extra: pip install -e .[gpu]) or a CUDA 12 toolkit.
_CUBLAS12 = ("cublasLt64_12.dll", "cublas64_12.dll")   # the first is the second's dependency
_GPU_LIBRARY_ERROR = re.compile(r"cublas|cudnn|cuda", re.IGNORECASE)


def _nvidia_bin_dirs(roots: list[Path] | None = None) -> list[Path]:
    """The bin folder of every NVIDIA pip package (site-packages/nvidia/*/bin)
    that exists: cuBLAS from nvidia-cublas-cu12, cuDNN from nvidia-cudnn-cu12.
    `roots` are the "nvidia" folders to look in; by default those of the
    installed packages."""
    if roots is None:
        roots = []
        try:
            import nvidia

            roots += [Path(p) for p in nvidia.__path__]
        except Exception:
            pass  # no NVIDIA wheels installed: nothing to add
        try:
            import site

            for base in [*site.getsitepackages(), site.getusersitepackages()]:
                roots.append(Path(base) / "nvidia")
        except Exception:
            pass  # a stripped-down Python without site: the import above had to do
    found: list[Path] = []
    for root in roots:
        try:
            candidates = sorted(root.glob("*/bin"))
        except OSError:
            continue
        for folder in candidates:
            if folder.is_dir() and folder not in found:
                found.append(folder)
    return found


def _add_nvidia_dll_dirs(dirs: list[Path] | None = None) -> list[Path]:
    """Make the NVIDIA pip packages' DLLs findable before a CUDA model loads:
    each folder goes on PATH (CTranslate2 loads cuDNN by name, which
    os.add_dll_directory alone does not reach) and is added as a DLL directory.
    Returns the folders. Only Windows needs this."""
    if os.name != "nt":
        return []
    folders = _nvidia_bin_dirs() if dirs is None else dirs
    on_path = os.environ.get("PATH", "").split(os.pathsep)
    for folder in folders:
        if str(folder) not in on_path:
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(str(folder))
        except (OSError, AttributeError):
            pass  # on PATH already
    return folders


def _cublas12_dirs() -> list[Path]:
    """Where cuBLAS 12 may be, the pip wheels' copy first."""
    dirs: list[Path] = list(_nvidia_bin_dirs())
    if os.environ.get("CUDA_PATH"):
        dirs.append(Path(os.environ["CUDA_PATH"]) / "bin")
    dirs += [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    return dirs


def _cuda12_blas(dirs: list[Path] | None = None, load=None) -> Path | None:
    """The folder cuBLAS 12 was loaded from, or None when it is not here.

    Loaded by full path, and its folder put first on PATH: CTranslate2's own
    later load asks for it by name, which finds a copy already loaded, and
    os.add_dll_directory alone does not reach that load. Not Windows: the
    system's loader finds the libraries as it always has."""
    if os.name != "nt":
        return Path(".")
    load = load or ctypes.WinDLL
    for folder in (_cublas12_dirs() if dirs is None else dirs):
        if not all((folder / name).is_file() for name in _CUBLAS12):
            continue
        try:
            for name in _CUBLAS12:
                load(str(folder / name))
        except OSError as e:
            print(f"  Whisper: could not load cuBLAS 12 from {folder} ({e})")
            continue
        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(str(folder))
        except (OSError, AttributeError):
            pass  # the libraries are loaded and the folder is on PATH already
        return folder
    return None


# Model loading

_model = None   # the loaded WhisperModel, kept between calls until release()


def _on_gpu(model) -> bool:
    """Whether a loaded Whisper model runs on the GPU (CTranslate2 says)."""
    return getattr(getattr(model, "model", None), "device", "cpu") == "cuda"


def gpu_ready() -> tuple[bool, str]:
    usable, reason = cuda_usable()
    if not usable:
        return False, reason
    _add_nvidia_dll_dirs()
    if _cuda12_blas() is None:
        return False, (
            "NVIDIA cuBLAS 12 (cublas64_12.dll) was not found; "
            "run 'pip install -e .[gpu]' to add the GPU libraries"
        )
    return True, reason


def _load_model(model_size: str, device: str = "auto"):
    """A WhisperModel. device is "auto" (GPU when usable, else CPU), "cuda" or
    "cpu". model_size "auto" means large-v3-turbo on the GPU and small on the
    CPU."""
    # Imported lazily: loading faster-whisper/ctranslate2 takes seconds and is
    # not needed when the transcript is cached.
    from faster_whisper import WhisperModel

    if device in ("auto", "cuda"):
        ready, reason = gpu_ready()
        if not ready:
            if device == "cuda":
                raise RuntimeError(f"GPU transcription is not possible: {reason}")
            print(f"  Whisper: GPU not used ({reason}). Transcribing on the CPU, which is slower.")
        else:
            try:
                # large-v3-turbo: large-v3 accuracy with a 4-layer decoder.
                # Falls back to small if it cannot be loaded.
                names = ("large-v3-turbo", "small") if model_size == "auto" else (model_size,)
                last_error: Exception | None = None
                for name in names:
                    try:
                        model = WhisperModel(name, device="cuda", compute_type="float16")
                        print(f"  Whisper: GPU (CUDA) active, model '{name}'")
                        return model
                    except Exception as e:
                        last_error = e
                raise last_error
            except Exception as e:
                if device == "cuda":
                    raise  # the GPU was demanded by name: do not silently downgrade
                print(f"  Whisper: GPU unavailable ({str(e)[:90]}), using the CPU")
    if model_size == "auto":
        model_size = "small"  # on the CPU, bigger models are several times slower
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def release() -> None:
    """Free the model and the GPU memory it held, so Ollama can use the GPU."""
    global _model
    _model = None
    gc.collect()
    torch = sys.modules.get("torch")   # never imported means nothing to free
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass  # freeing is best effort


# Transcription

def _run(model, wav: Path, hotwords: list[str] | None, language: str | None = "en") -> list[Segment]:
    """One pass of Whisper over the audio. language None lets Whisper detect it."""
    options: dict = {}
    if hotwords:
        # Older faster-whisper releases have no hotwords argument.
        if "hotwords" in inspect.signature(model.transcribe).parameters:
            options["hotwords"] = " ".join(hotwords)
    raw_segments, info = model.transcribe(
        str(wav),
        # Telling Whisper the language skips its guess from the first 30 s,
        # which on a gaming recording is often game music or menu noise.
        language=language,
        vad_filter=True,
        # Greedy decoding is much faster than beam 5 with near-identical output.
        beam_size=1,
        # Do not feed the previous window's text back in: on long recordings
        # with music or noise that is what causes repeated-sentence loops.
        condition_on_previous_text=False,
        word_timestamps=True,
        **options,
    )

    segments: list[Segment] = []
    for seg in raw_segments:  # generator: transcription happens here
        segments.append(Segment(
            start=round(seg.start, 2),
            end=round(seg.end, 2),
            text=seg.text.strip(),
            words=[
                Word(round(w.start, 2), round(w.end, 2), w.word.strip())
                for w in (seg.words or [])
            ],
        ))
        print(f"\r  Transcribed up to {seg.end:7.1f}s", end="", flush=True)
        if info.duration:
            progress.step(seg.end / info.duration)
    print()
    return segments


def _read_cache(cache_path: Path) -> list[Segment] | None:
    """The cached segments, or None when there is no usable cache.

    A truncated or malformed file (a crash mid-write, a hand edit) counts as a
    miss, so the recording is transcribed again instead of failing every run."""
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        return collapse_repetition_loops([
            Segment(d["start"], d["end"], d["text"], [Word(**w) for w in d["words"]])
            for d in data
        ])
    except (OSError, ValueError, KeyError, TypeError):   # ValueError covers bad JSON and bad UTF-8
        return None


def _write_cache(cache_path: Path, segments: list[Segment]) -> None:
    """Write the cache atomically: a temp file in the same folder, then
    os.replace, so a crash leaves the old file or none, never half of one."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_name(cache_path.name + ".tmp")
    tmp.write_text(
        json.dumps([dataclasses.asdict(s) for s in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, cache_path)


def transcribe(
    wav: Path,
    cache: Path,
    model: str = "auto",
    hotwords: list[str] | None = None,
    language: str | None = "en",
    device: str = "auto",
) -> list[Segment]:
    """Segments with word timings for `wav`, cached as cache/transcript.json.

    A cached transcript is returned without loading any model. model "auto"
    picks large-v3-turbo on a usable GPU and small on the CPU; a GPU that fails
    during the run is retried on the CPU. device "cpu" never touches the GPU.
    hotwords are names Whisper is told to listen for, so it spells them as
    given. language is the spoken language ("en"); None lets Whisper detect it."""
    global _model
    cache_path = cache / "transcript.json"
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached

    print(f"  Loading whisper model '{model}'...")
    _model = _load_model(model, "cpu" if device == "cpu" else "auto")
    try:
        segments = _run(_model, wav, hotwords, language)
    except RuntimeError as e:
        # The GPU's libraries are only loaded at the first encode, after the
        # model has loaded, so a GPU that loads can still fail here.
        if not _on_gpu(_model) or not _GPU_LIBRARY_ERROR.search(str(e)):
            raise
        print(f"\n  Whisper: the GPU failed ({str(e)[:120]}); transcribing again on the CPU")
        _model = _load_model(model, "cpu")
        segments = _run(_model, wav, hotwords, language)

    segments = collapse_repetition_loops(segments)
    _write_cache(cache_path, segments)
    return segments


# Repetition loops

# Inside one segment, a loop is a long span, a lot of words, and almost no
# vocabulary. All three must hold: sparse speech has a normal unique-word
# ratio, and a genuine chant is short because its pauses become segment
# boundaries.
_LOOP_MIN_SECONDS = 25.0
_LOOP_MIN_WORDS = 40
_LOOP_MAX_UNIQUE_RATIO = 0.15
# Across segments, Whisper on silence or noise also emits the same short line
# ("thank you") as many consecutive segments. Real speech rarely repeats one
# line this often back to back.
_LOOP_MIN_RUN = 4


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _collapse_within_segment(seg: Segment) -> Segment:
    """A copy of `seg` with a one-segment repetition loop collapsed, or `seg`
    itself when it is not one.

    Keeps the first instance of each distinct sentence and trims the duplicated
    word timings, so captions read correctly and the rest of the span is
    treated as what it is: not speech."""
    words = seg.words
    if seg.end - seg.start < _LOOP_MIN_SECONDS or len(words) < _LOOP_MIN_WORDS:
        return seg
    tokens = [w.text.strip(" .,!?").lower() for w in words if w.text]
    if not tokens or len(set(tokens)) / len(tokens) > _LOOP_MAX_UNIQUE_RATIO:
        return seg

    seen: set[str] = set()
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", seg.text.strip()):
        key = _normalize(sentence)
        if key and key not in seen:
            seen.add(key)
            kept.append(sentence.strip())
    # A loop usually gets cut off mid-phrase, leaving a stub that is not a
    # sentence and reads like a typo.
    if len(kept) > 1 and len(kept[-1].split()) < 2:
        kept.pop()
    if not kept:
        return seg

    text = " ".join(kept)
    keep_n = min(len(words), max(1, len(text.split())))
    kept_words = words[:keep_n]
    return Segment(seg.start, round(max(kept_words[-1].end, seg.start + 0.5), 2), text, kept_words)


def collapse_repetition_loops(segments: list[Segment]) -> list[Segment]:
    """Segments with Whisper repetition loops removed (the input is not changed).

    Two shapes are handled: one long segment that repeats a phrase inside
    itself, and a run of at least four consecutive segments with identical
    text, of which only the first is kept."""
    out: list[Segment] = []
    run_key = None
    run_len = 0
    for seg in segments:
        seg = _collapse_within_segment(seg)
        key = _normalize(seg.text)
        if key and key == run_key:
            run_len += 1
            # Reaching the threshold makes the whole run a loop: drop the copies
            # already appended after the first. Shorter runs are kept as said.
            if run_len == _LOOP_MIN_RUN:
                del out[-(_LOOP_MIN_RUN - 2):]
            if run_len >= _LOOP_MIN_RUN:
                continue
        else:
            run_key, run_len = key, 1
        out.append(seg)
    return out
