# TeddyClip v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Windows CLI that turns long OBS couch co-op recordings into named 16:9 clips, a moments CSV, DaVinci Resolve markers, chapters in the original, and a highlight video, using only local tools.

**Architecture:** Ten small modules in `teddyclip/` connected by plain dataclasses. Heavy work (whisper, PANNs, OCR, Ollama, ffmpeg) sits behind one function each so the rest is testable with fakes. Much of the low-level code is adapted from Clips Kitty (AGPL-3.0-or-later), whose clone is at `C:\Users\wsmith\ck-ref\repo` (paths below marked `CK:` are relative to it).

**Tech Stack:** Python 3.11+ (3.12 installed), faster-whisper, numpy, PyYAML, requests, torch (CPU wheel), rapidocr-onnxruntime, ffmpeg/ffprobe, Ollama, pytest.

**Spec:** `docs/design.md`

## Global Constraints

- Python `>=3.11`; package name `teddyclip`; console script `teddyclip = teddyclip.cli:main`.
- License AGPL-3.0-or-later. Every file containing adapted Clips Kitty code starts with: `# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.` `panns.py` additionally keeps `Copyright (c) 2018-2020 Qiuqiang Kong` (MIT).
- Never use em dashes or en dashes in code, comments, docs, prompts or output text. Use a hyphen or rephrase.
- No media, transcripts, caches or model weights in the repo. All runtime files live under `cfg.root` (default `C:\Users\{user}\TeddyClip`).
- No network calls except Ollama at `cfg.llm_url` and the one-time PANNs weights and labels download.
- Recordings are never deleted except the inbox copy after a verified copy exists in `Done`.
- Folder names exactly: `1 Inbox`, `2 Clips`, `3 Highlights`, `Done`, `.cache`.
- Clip lengths 20 s to 120 s; trigger window `[t - 45, t - 0.3]`; signal window 20 s before to 15 s after a peak; `max_clips` 40; section cap 22 percent of 8 sections; dedupe thresholds 40 percent overlap, 70 percent text similarity.
- Default `pytest` run must not need GPU, network, Ollama or model weights. Tests that do are marked `@pytest.mark.slow` and excluded by default (`addopts = "-m 'not slow'"`).
- Paths contain spaces (the repo is under `G:\My Drive\...`). Always pass subprocess args as lists, never shell strings.
- Each task ends with a commit on the working branch. Commit messages carry no Co-Authored-By trailer.

## Review Focus

1. **Names with spaces, apostrophes and symbols** (`Teddy's "best" run?.mp4`, titles with `: / ? *`): clips, concat lists, EDL and CSV must not break. Test owned by Task 9 (`test_clip_name_sanitizes`, `test_highlight_handles_quotes_in_names`).
2. **A recording with no moments, or shorter than 2 minutes:** no crash, empty CSV with header, EDL with zero events, no chapters, original still archived. Test owned by Task 10 (`test_process_recording_with_no_moments`).
3. **Trigger in the first 45 seconds, or two triggers 10 s apart:** window start clamps to 0; both stay kept and labeled trigger after merging. Test owned by Task 7 (`test_trigger_near_start_clamps`, `test_close_triggers_merge_but_stay_triggers`).
4. **Ollama down, or replying with empty or broken JSON mid-run:** clips still produced with transcript-snippet titles. Test owned by Task 7 (`test_label_falls_back_when_llm_fails`).
5. **`audio_track` set to a track the file does not have:** warn and fall back to the first audio track. Test owned by Task 2 (`test_extract_audio_bad_track_falls_back`).

---

### Task 1: Package scaffold and config

**Files:**
- Create: `pyproject.toml`, `teddyclip/__init__.py`, `teddyclip/config.py`, `config.yaml`, `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass Config` fields: `root: Path`, `people: list[str]`, `triggers: list[str]`, `audio_track: int | None`, `whisper_model: str`, `llm_model: str`, `llm_url: str`, `min_seconds: float`, `max_seconds: float`, `max_clips: int`, `pre_trigger_seconds: float`, `weights: dict[str, float]`, `games: dict[str, str]`, `lexicons: dict[str, list[str]]`, `resolve_timeline_start: str`
  - `@dataclass Paths` fields `inbox, clips, highlights, done, cache, models: Path`; `cfg.paths -> Paths` (property); `Paths.ensure() -> None` creates all.
  - `load_config(path: Path | None = None) -> Config`: built-in defaults (values from spec section 8, `llm_model="qwen3:4b"`, `llm_url="http://127.0.0.1:11434"`), overlaid by the YAML file if it exists. Nested YAML keys `llm.model`, `llm.url`, `clips.*`, `resolve.timeline_start` map to the flat fields. `{user}` in `root` expands to the Windows username.
  - `tests/conftest.py` fixture `tiny_video(tmp_path) -> Path`: builds a 10 s 640x360 30 fps mp4 with ffmpeg (`testsrc2` video, `sine=frequency=440` audio, 2 s of silence via `volume` enable expression from 4 s to 6 s). Fixture `cfg(tmp_path) -> Config` with `root=tmp_path / "TeddyClip"`.

- [ ] **Step 1: Write `pyproject.toml`** with setuptools build, deps `faster-whisper`, `numpy`, `pyyaml`, `requests`, `torch`, `rapidocr-onnxruntime`; optional `dev = ["pytest"]`; pytest `addopts = "-m 'not slow'"`, marker `slow`. Create venv and install: `py -3.12 -m venv .venv`, `.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu`, `.venv\Scripts\pip install -e .[dev]`.

- [ ] **Step 2: Write the failing tests**

```python
def test_defaults_without_file(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.max_clips == 40 and cfg.min_seconds == 20 and cfg.max_seconds == 120
    assert cfg.pre_trigger_seconds == 45
    assert "clip that" in cfg.triggers
    assert cfg.llm_url == "http://127.0.0.1:11434"

def test_yaml_overrides_nested_keys(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("llm:\n  model: none\nclips:\n  max_clips: 5\nresolve:\n  timeline_start: '00:00:00:00'\n")
    cfg = load_config(p)
    assert cfg.llm_model == "none" and cfg.max_clips == 5
    assert cfg.resolve_timeline_start == "00:00:00:00"
    assert cfg.max_seconds == 120  # untouched default

def test_user_placeholder_and_folder_names(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "teddy")
    p = tmp_path / "c.yaml"; p.write_text("root: C:\\Users\\{user}\\TeddyClip\n")
    paths = load_config(p).paths
    assert str(paths.inbox).endswith(r"teddy\TeddyClip\1 Inbox")
    assert paths.clips.name == "2 Clips" and paths.highlights.name == "3 Highlights"
    assert paths.done.name == "Done" and paths.cache.name == ".cache"
```

- [ ] **Step 3: Run** `.venv\Scripts\python -m pytest tests/test_config.py -v`. Expected: FAIL (module not found).
- [ ] **Step 4: Implement `teddyclip/config.py`** and write `config.yaml` with the spec section 8 contents (people `[Teddy, Friend]` as placeholders).
- [ ] **Step 5: Run** the same command. Expected: 3 passed.
- [ ] **Step 6: Commit** `git add pyproject.toml teddyclip config.yaml tests && git commit -m "Add package scaffold and config loading"`

---

### Task 2: media.py (ffmpeg helpers)

**Files:**
- Create: `teddyclip/media.py`, `tests/test_media.py`
- Adapt from: `CK: video/encoding.py` (`_CANDIDATES`, `CPU_ARGS`, `_probe`, `_select`, `audio_filter_args`, `source_probe`), `CK: video/cutter.py` (`cut_clip`, `_swap_encoder`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `@dataclass Chapter(start: float, end: float, title: str)`
  - `@dataclass Probe(duration: float, fps: float, width: int, height: int, audio_tracks: int, chapters: list[Chapter])`
  - `probe(path: Path) -> Probe` (ffprobe JSON with `-show_chapters`)
  - `extract_audio(src: Path, dst: Path, rate: int, track: int | None = None) -> Path` mono WAV; `track` is 1-based; a missing track logs a warning and uses track 1.
  - `read_frames(src: Path, times: list[float], width: int = 1280) -> Iterator[tuple[float, np.ndarray]]` RGB uint8 frames, one fast-seek ffmpeg call per time.
  - `encoder_args() -> list[str]` cached choice: NVENC if a 1 s test encode succeeds, else `CPU_ARGS`.
  - `cut(src: Path, start: float, end: float, dst: Path) -> Path` frame-accurate re-encode (`-ss` before `-i`, `-t`), constant frame rate, loudnorm to -14 LUFS, 0.15 s audio fade in and out; on encoder failure retries once with `CPU_ARGS`.
  - `concat(files: list[Path], dst: Path) -> Path` concat demuxer with `-c copy`; list file entries escape single quotes (`'` becomes `'\''`).
  - `write_chapters(src: Path, dst: Path, chapters: list[Chapter]) -> Path` remux `-map 0 -c copy` with an ffmetadata file (`TIMEBASE=1/1000`, title escaped for `=;#\` and newlines), `-map_chapters 1`.

- [ ] **Step 1: Write the failing tests** (all use the `tiny_video` fixture)

```python
def test_probe_reads_basics(tiny_video):
    p = probe(tiny_video)
    assert 9.5 < p.duration < 10.5 and round(p.fps) == 30 and p.audio_tracks == 1

def test_extract_audio_rate(tiny_video, tmp_path):
    wav = extract_audio(tiny_video, tmp_path / "a.wav", rate=16000)
    assert probe_wav_rate(wav) == 16000   # helper in test using the wave module

def test_extract_audio_bad_track_falls_back(tiny_video, tmp_path, caplog):
    wav = extract_audio(tiny_video, tmp_path / "a.wav", rate=16000, track=5)
    assert wav.exists() and "track 5" in caplog.text

def test_read_frames_shape(tiny_video):
    frames = list(read_frames(tiny_video, [1.0, 2.0], width=320))
    assert [t for t, _ in frames] == [1.0, 2.0] and frames[0][1].shape[1] == 320

def test_cut_duration(tiny_video, tmp_path):
    out = cut(tiny_video, 2.0, 5.0, tmp_path / "c.mp4")
    assert abs(probe(out).duration - 3.0) < 0.15

def test_chapters_roundtrip(tiny_video, tmp_path):
    dst = write_chapters(tiny_video, tmp_path / "o.mp4", [Chapter(0, 4, "A = b; c"), Chapter(4, 10, "Two")])
    assert [c.title for c in probe(dst).chapters] == ["A = b; c", "Two"]

def test_concat_two_cuts(tiny_video, tmp_path):
    a = cut(tiny_video, 0, 3, tmp_path / "it's a.mp4"); b = cut(tiny_video, 5, 8, tmp_path / "b.mp4")
    assert abs(probe(concat([a, b], tmp_path / "j.mp4")).duration - 6.0) < 0.3
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_media.py -v`. Expected: FAIL (import error).
- [ ] **Step 3: Implement `teddyclip/media.py`** adapting the CK functions named above; drop CK's `core.binaries` lookups in favor of `shutil.which("ffmpeg")`, raising `RuntimeError("ffmpeg not found: see README step 2")` when missing. Add the attribution header.
- [ ] **Step 4: Run** the same command. Expected: 7 passed.
- [ ] **Step 5: Commit** `git commit -am "Add ffmpeg media helpers adapted from Clips Kitty"` (after `git add` of new files).

---

### Task 3: transcribe.py

**Files:**
- Create: `teddyclip/transcribe.py`, `tests/test_transcribe.py`
- Adapt from: `CK: transcription/transcriber.py` (`_load_model`, `_run`, `transcribe`, `_collapse_repetition_loops`, `_cuda12_blas`), `CK: core/gpu.py` (`cuda_usable`)

**Interfaces:**
- Produces:
  - `@dataclass Word(start: float, end: float, text: str)`; `@dataclass Segment(start: float, end: float, text: str, words: list[Word])`
  - `transcribe(wav: Path, cache: Path, model: str = "auto", hotwords: list[str] | None = None) -> list[Segment]`. Cache file `cache / "transcript.json"`; when present it is returned without loading any model. `model="auto"`: `large-v3-turbo` float16 on CUDA, `small` int8 on CPU; CUDA failure mid-run retries on CPU. Passes `word_timestamps=True`, `vad_filter=True`, `beam_size=1`, `condition_on_previous_text=False`, and `hotwords=" ".join(hotwords)` when given.
  - `all_words(segments: list[Segment]) -> list[Word]`
  - `release() -> None` frees the model and calls `torch.cuda.empty_cache()` if available, so Ollama gets the GPU.

- [ ] **Step 1: Write the failing tests**

```python
def test_cache_hit_skips_model(tmp_path, monkeypatch):
    (tmp_path / "transcript.json").write_text(json.dumps([{"start": 0, "end": 1, "text": "clip that",
        "words": [{"start": 0, "end": 0.4, "text": "clip"}, {"start": 0.4, "end": 1, "text": "that"}]}]))
    monkeypatch.setattr(transcribe_mod, "_load_model", lambda *a, **k: pytest.fail("model loaded"))
    segs = transcribe(tmp_path / "a.wav", tmp_path)
    assert segs[0].words[1].text == "that"

def test_repetition_loops_collapse():
    segs = [Segment(i, i + 1, "thank you", []) for i in range(6)]
    assert len(collapse_repetition_loops(segs)) < 6

@pytest.mark.slow
def test_real_transcription(tiny_speech_wav, tmp_path):  # fixture uses Windows SAPI to say "clip that"
    assert "clip" in " ".join(w.text.lower() for w in all_words(transcribe(tiny_speech_wav, tmp_path)))
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_transcribe.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** by adapting the CK functions; remove the cloud path, `core.cancel`, `core.progress`; expose CK's loop collapser as `collapse_repetition_loops(segments) -> list[Segment]`.
- [ ] **Step 4: Run** the same command. Expected: 2 passed, 1 deselected.
- [ ] **Step 5: Commit** `"Add cached faster-whisper transcription adapted from Clips Kitty"`.

---

### Task 4: signals.py (audio features, triggers, fusion)

**Files:**
- Create: `teddyclip/signals.py`, `tests/test_signals.py`
- Adapt from: `CK: analysis/audio_features.py` (`extract_audio_features`, use the vectorized `_rolling_median` from `CK: analysis/game_audio.py`), `CK: analysis/fusion.py` (`_pct`, `_soft_or`, `_window_peak`, `_voice_jump`, `_strongest_peak_windows`)

**Interfaces:**
- Consumes: `Word` (Task 3).
- Produces:
  - `audio_features(wav16k: Path) -> dict[str, np.ndarray]` keys `loudness`, `spike`, `burst`, `noisiness`, one value per second.
  - `voice_jump(loudness: np.ndarray) -> np.ndarray` (0..1 per second).
  - `find_triggers(words: list[Word], phrases: list[str], threshold: float = 0.8) -> list[float]`: slide over word n-grams of each phrase's length, compare lowercase, punctuation-stripped text with `difflib.SequenceMatcher`; return start time of each match, dropping matches within 5 s of a previous one.
  - `pct(x: np.ndarray) -> np.ndarray` percentile rank within the video, 0..1.
  - `fuse(signals: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray` = soft OR of `pct(signal) * weight` (weights clipped to 0..1), arrays padded to the longest length.
  - `peak_windows(score: np.ndarray, percentile: float = 92, pre: float = 20, post: float = 15) -> list[tuple[float, float, float]]` (start, end, peak score); a peak must be above the percentile value and above 0; peaks at least `pre + post` apart (the higher one wins), start clamped to 0 and end to `len(score)`.

- [ ] **Step 1: Write the failing tests**

```python
def W(t, s): return Word(t, t + 0.3, s)

@pytest.mark.parametrize("said", [["clip", "that"], ["Clip", "that!"], ["clipped", "that"], ["flip", "that"]])
def test_trigger_variants_match(said):
    words = [W(10, "oh"), W(11, said[0]), W(11.3, said[1])]
    assert find_triggers(words, ["clip that"]) == [11]

def test_trigger_does_not_match_unrelated():
    assert find_triggers([W(1, "chip"), W(1.3, "bag")], ["clip that"]) == []

def test_triggers_within_5s_collapse():
    words = [W(1, "clip"), W(1.3, "that"), W(3, "clip"), W(3.3, "that"), W(20, "clip"), W(20.3, "it")]
    assert find_triggers(words, ["clip that", "clip it"]) == [1, 20]

def test_pct_and_fuse():
    a = np.array([0, 0, 10, 0.]); b = np.array([0, 5, 0, 0.])
    s = fuse({"a": a, "b": b}, {"a": 1.0, "b": 0.5})
    assert s.argmax() == 2 and s[1] > s[0] and np.all((0 <= s) & (s <= 1))

def test_peak_windows_clamp_and_spacing():
    s = np.zeros(300); s[5] = 1; s[150] = 1; s[160] = 0.9
    wins = peak_windows(s, percentile=90)
    assert wins[0][0] == 0 and len(wins) == 2

def test_voice_jump_flags_sudden_loud():
    x = np.full(200, 0.1); x[100] = 0.35
    assert voice_jump(x)[100] > 0.5 and voice_jump(x)[50] == 0
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_signals.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the functions; `audio_features` reads the WAV with the `wave` module plus numpy instead of CK's ffmpeg pipe. Add the attribution header.
- [ ] **Step 4: Run** the same command. Expected: all passed.
- [ ] **Step 5: Commit** `"Add audio features, clip-that triggers and signal fusion"`.

---

### Task 5: panns.py and laughter/shout signals

**Files:**
- Create: `teddyclip/panns.py`, `tests/test_panns.py`
- Modify: `teddyclip/signals.py` (add `people_sounds`)
- Adapt from: `CK: analysis/panns.py` (whole file), `CK: analysis/game_audio.py` (`listen`, `sound_signal` people side), `CK: scripts/fetch_panns.py` (download URL), label groups from `CK: config/gaming.yaml` `sound_groups`.

**Interfaces:**
- Produces:
  - `panns.ensure_assets(models: Path) -> tuple[Path, Path]` downloads `MobileNetV1_mAP=0.389.pth` from `https://zenodo.org/records/3987831/files/MobileNetV1_mAP%3D0.389.pth` and the AudioSet `class_labels_indices.csv` (URL as in CK's fetch script) once; returns (weights, labels).
  - `class Tagger(weights: Path, labels: Path)` with `.labels: list[str]` and `.tag(windows: np.ndarray) -> np.ndarray` (n, 527) on CPU.
  - `GROUPS = {"laughter": ["Laughter", "Belly laugh", "Giggle", "Chuckle, chortle", "Snicker"], "shout": ["Screaming", "Shout", "Yell", "Battle cry"]}`
  - `signals.people_sounds(wav32k: Path, tagger) -> dict[str, np.ndarray]` keys `laughter`, `shout`: per second, max class probability in the group over a 2 s window, then scored against its own rolling 90 s median (CK `sound_signal` logic), 0..1. `tagger` is anything with `.labels` and `.tag()`.

- [ ] **Step 1: Write the failing tests**

```python
class FakeTagger:
    labels = ["Speech", "Laughter", "Giggle", "Shout"] + ["x"] * 523
    def tag(self, windows):
        out = np.zeros((len(windows), 527)); out[30:33, 1] = 0.9  # laugh at ~30 s
        return out[: len(windows)]

def test_people_sounds_finds_laugh(tmp_path):
    wav = write_silence_wav(tmp_path / "a.wav", seconds=120, rate=32000)
    s = people_sounds(wav, FakeTagger())
    assert s["laughter"].argmax() in range(29, 34) and s["shout"].max() == 0

@pytest.mark.slow
def test_real_tagger_loads(tmp_path):
    w, l = ensure_assets(tmp_path)
    assert Tagger(w, l).tag(np.zeros((1, 64000), np.float32)).shape == (1, 527)
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_panns.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `panns.py` (copy CK's network and `torch.stft` front end, keep Kong's MIT notice plus the CK header) and `people_sounds`.
- [ ] **Step 4: Run** the same command. Expected: 1 passed, 1 deselected. Then run `-m slow tests/test_panns.py` once manually; expected PASS (downloads about 17 MB).
- [ ] **Step 5: Commit** `"Add PANNs laughter and shout signals adapted from Clips Kitty"`.

---

### Task 6: llm.py (Ollama client)

**Files:**
- Create: `teddyclip/llm.py`, `tests/test_llm.py`
- Adapt from: `CK: llm/ollama_backend.py` (`_answer`, `_limit_reasoning`, retry loop), `CK: analysis/highlights.py` (`_parse_clips_json` lenient parsing)

**Interfaces:**
- Produces:
  - `class LLM(url: str, model: str, cache: Path)`; `.enabled -> bool` (False when `model == "none"`); `.available() -> bool` (GET `/api/tags` succeeds and lists the model); `.ask(prompt: str, schema: dict) -> dict | None`.
  - `.ask` posts to `{url}/api/chat` with `{"model", "messages": [{"role": "user", "content": prompt}], "format": schema, "stream": False, "think": False, "options": {"num_ctx": 8192, "temperature": 0.2}}`, timeout 120 s; up to 3 attempts; parses with `parse_json`; returns None after failures or when disabled. Answers cached as JSON in `cache / "llm" / f"{sha1(model + prompt + json.dumps(schema))}.json"`.
  - `parse_json(text: str) -> dict | None`: strip code fences, slice first `{` to last `}`, `json.loads`, None on failure.

- [ ] **Step 1: Write the failing tests** (monkeypatch `requests.post`/`requests.get`)

```python
def test_parse_json_messy():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}
    assert parse_json("no json here") is None

def test_ask_sends_schema_and_caches(tmp_path, monkeypatch):
    calls = []
    def post(url, json, timeout):
        calls.append(json); return FakeResp({"message": {"content": '{"score": 7}'}})
    monkeypatch.setattr(requests, "post", post)
    llm = LLM("http://x", "m", tmp_path)
    assert llm.ask("p", {"type": "object"}) == {"score": 7}
    assert llm.ask("p", {"type": "object"}) == {"score": 7}
    assert len(calls) == 1 and calls[0]["format"] == {"type": "object"} and calls[0]["think"] is False

def test_ask_retries_then_none(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({"message": {"content": "garbage"}}))
    assert LLM("http://x", "m", tmp_path).ask("p", {}) is None

def test_none_model_disabled(tmp_path):
    llm = LLM("http://x", "none", tmp_path)
    assert not llm.enabled and llm.ask("p", {}) is None
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_llm.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `teddyclip/llm.py` with the attribution header.
- [ ] **Step 4: Run** the same command. Expected: 4 passed.
- [ ] **Step 5: Commit** `"Add local Ollama client with JSON schema and cache"`.

---

### Task 7: moments.py and prompts

**Files:**
- Create: `teddyclip/moments.py`, `prompts/sweep.txt`, `prompts/label.txt`, `prompts/rerank.txt`, `tests/test_moments.py`
- Adapt from: `CK: analysis/highlights.py` (`_select_unique`, `_check_against_kept`, `_text_similarity`, `_chunk_segments`), `CK: analysis/fusion.py` (`_rerank`, `_parse_order`), `CK: longform/highlight_select.py` (`select_highlights`), prompts `CK: config/prompts/score_clips.txt`, `score_windows.txt`, `rerank.txt`.

**Interfaces:**
- Consumes: `Segment`, `Word` (Task 3), `LLM` (Task 6), `peak_windows` (Task 4).
- Produces:
  - `KINDS = ("trigger", "marker", "laughter", "joke", "loud", "game")`
  - `@dataclass Moment(start: float, end: float, score: float, kind: str, title: str = "", why: str = "", events: list[str] = field(default_factory=list), keep: bool = False)`; `.duration -> float`
  - `forced_windows(times: list[float], kind: str, pre: float = 45, gap: float = 0.3) -> list[Moment]` score 10, window `[max(0, t - pre), t - gap]`.
  - `signal_windows(peaks: list[tuple[float, float, float]], signals: dict[str, np.ndarray]) -> list[Moment]` kind = the strongest signal at the peak (`laughter`, `joke`, `loud`), score = peak * 10.
  - `sweep(segments: list[Segment], llm: LLM, prompt: str, slice_s: float = 120, overlap_s: float = 30) -> np.ndarray` per-second joke score 0..1 (score / 10 spread over the slice; max where slices overlap). All zeros when `llm.enabled` is False.
  - `snap(m: Moment, segments: list[Segment], min_s: float, max_s: float) -> Moment` expands start/end to segment boundaries, then clamps length (forced moments keep their end).
  - `merge(moments: list[Moment], segments: list[Segment]) -> list[Moment]`: overlap over 40 percent or text similarity over 70 percent merges into one; the merged kind is the highest priority kind in `KINDS` order; events are unioned; score is the max.
  - `label(moments: list[Moment], segments: list[Segment], llm: LLM, prompt: str, people: list[str]) -> list[Moment]`: one `llm.ask` per moment with schema `{score: int 1-10, title: str, why: str, trim_start: number, trim_end: number}`; trims are applied only within the window and only to non-forced kinds. On None: title = first 8 words of the moment's transcript, why = kind.
  - `rerank(moments: list[Moment], llm: LLM, prompt: str, top: int = 15) -> list[Moment]`: one call with schema `{order: [int]}`; missing indices appended in original order; position bonus `6 * (1 - i / n)` added to score (never lowers). Only the `top` highest-scoring moments are sent; the list is returned in its original input order.
  - `select(moments: list[Moment], duration: float, max_clips: int, sections: int = 8, cap: float = 0.22) -> list[Moment]`: sets `keep=True` on all forced kinds, then on the best others while total kept is under `max_clips` and each eighth of `duration` holds at most `ceil(cap * max_clips)`; returns all moments sorted by start.
- Prompts: plain text with `{transcript}`, `{events}`, `{people}` placeholders filled by `str.format`. `sweep.txt` asks for a 1 to 10 score for a funny exchange, joke or great line between friends playing games on a couch, quoting the line; `label.txt` asks for score, a title under 60 characters that uses the people's names when said, a one sentence why, and optional trims; `rerank.txt` adapts CK's rerank prompt. No em dashes.

- [ ] **Step 1: Write the failing tests** (use a `FakeLLM` with `.enabled=True` and a queue of answers)

```python
def test_trigger_near_start_clamps():
    m = forced_windows([20.0], "trigger")[0]
    assert m.start == 0 and m.end == pytest.approx(19.7) and m.kind == "trigger"

def test_close_triggers_merge_but_stay_triggers():
    ms = merge(forced_windows([100.0, 110.0], "trigger"), segments=[])
    assert len(ms) == 1 and ms[0].kind == "trigger" and ms[0].end == pytest.approx(109.7)

def test_merge_prefers_higher_priority_kind():
    a = Moment(10, 40, 6, "loud"); b = Moment(15, 45, 4, "laughter")
    assert merge([a, b], [])[0].kind == "laughter"

def test_label_falls_back_when_llm_fails():
    segs = [Segment(0, 30, "no way he just walked off the cliff again buddy", [])]
    out = label([Moment(0, 30, 5, "laughter")], segs, FakeLLM([None]), "{transcript}", ["Teddy"])
    assert out[0].title == "no way he just walked off the cliff" and out[0].why == "laughter"

def test_label_never_trims_triggers():
    llm = FakeLLM([{"score": 8, "title": "T", "why": "w", "trim_start": 10, "trim_end": 20}])
    out = label([Moment(0, 44.7, 10, "trigger")], [], llm, "{transcript}", [])
    assert (out[0].start, out[0].end) == (0, 44.7) and out[0].title == "T"

def test_rerank_repairs_partial_order():
    ms = [Moment(i, i + 30, 5, "loud") for i in range(3)]
    out = rerank(ms, FakeLLM([{"order": [2]}]), "{transcript}")
    assert out[2].score > out[0].score > out[1].score >= 5

def test_select_keeps_all_triggers_and_caps_sections():
    ms = [Moment(t, t + 30, 9, "loud") for t in range(0, 600, 31)] + forced_windows([5000], "trigger")
    kept = [m for m in select(ms, duration=8000, max_clips=10) if m.keep]
    assert any(m.kind == "trigger" for m in kept)
    assert sum(1 for m in kept if m.start < 1000) <= 3  # ceil(0.22 * 10)

def test_sweep_disabled_is_zero():
    assert sweep([Segment(0, 300, "hi", [])], FakeLLM([], enabled=False), "{transcript}").max() == 0
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_moments.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `teddyclip/moments.py` (attribution header) and the three prompt files.
- [ ] **Step 4: Run** the same command. Expected: all passed.
- [ ] **Step 5: Commit** `"Add moment finding, labeling, rerank and selection"`.

---

### Task 8: detectors.py (screen text)

**Files:**
- Create: `teddyclip/detectors.py`, `tests/test_detectors.py`
- Adapt from: `CK: analysis/game_text.py` (`_norm`, `Lexicon`, `read_frame` banner filter, `_read_windows` budget)

**Interfaces:**
- Consumes: `media.read_frames` (Task 2), `Moment` (Task 7).
- Produces:
  - `game_profile(recording: Path, inbox: Path, games: dict[str, str]) -> str`: inbox subfolder name, then filename, matched case-insensitively against `games` keys; else `"generic"`.
  - `class Lexicon(terms: list[str])` with `.find(text: str) -> list[str]`, normalizing case, spaces and misreads (`Q` and `0` to `O`, `1` to `I`, `5` to `S`).
  - `banner_texts(ocr_result, frame_height: int, min_height: float = 0.035) -> list[str]` keeps only boxes at least 3.5 percent of frame height.
  - `screen_events(video: Path, moments: list[Moment], lexicon: Lexicon, weight: float = 0.6, step: float = 2.0, max_frames: int = 160, ocr=None) -> list[Moment]`: samples the center crop every `step` seconds inside each moment (at most `max_frames` in total), appends hits such as `"YOU DIED"` to `m.events` once each, sets `kind="game"` only if the moment was `loud`, and adds `10 * weight` to its score once per moment. `ocr` is a callable `img -> (result, elapse)` and defaults to a lazily created `RapidOCR()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_game_profile_from_subfolder(tmp_path):
    inbox = tmp_path / "1 Inbox"; f = inbox / "Elden Ring" / "2026-11-01 20-14-03.mp4"
    assert game_profile(f, inbox, {"elden ring": "soulslike"}) == "soulslike"
    assert game_profile(inbox / "gta night.mp4", inbox, {"gta": "sandbox"}) == "sandbox"
    assert game_profile(inbox / "x.mp4", inbox, {"gta": "sandbox"}) == "generic"

def test_lexicon_handles_misreads():
    lex = Lexicon(["YOU DIED", "WASTED"])
    assert lex.find("Y0U  DlED") == ["YOU DIED"] and lex.find("WA5TED") == ["WASTED"]
    assert lex.find("you did it") == []

def test_banner_filter_ignores_small_text():
    result = [([[0, 0], [100, 0], [100, 50], [0, 50]], "YOU DIED", 0.9),
              ([[0, 0], [100, 0], [100, 10], [0, 10]], "chat msg", 0.9)]
    assert banner_texts(result, frame_height=720) == ["YOU DIED"]

def test_screen_events_tags_moment(tiny_video):
    fake_ocr = lambda img: ([([[0, 0], [9, 0], [9, 40], [0, 40]], "YOU DIED", 0.9)], None)
    m = screen_events(tiny_video, [Moment(1, 5, 5, "loud")], Lexicon(["YOU DIED"]), ocr=fake_ocr)[0]
    assert m.events == ["YOU DIED"] and m.kind == "game" and m.score > 5
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_detectors.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `teddyclip/detectors.py` (attribution header).
- [ ] **Step 4: Run** the same command. Expected: 4 passed.
- [ ] **Step 5: Commit** `"Add per-game screen text events adapted from Clips Kitty"`.

---

### Task 9: output.py

**Files:**
- Create: `teddyclip/output.py`, `tests/test_output.py`
- Adapt from: `CK: longform/chapters.py` (`chapter_lines`, `_timestamp`, rules), `CK: longform/assemble.py` (join flow, trimmed)

**Interfaces:**
- Consumes: `Moment` (Task 7), `media.cut`, `media.concat`, `media.probe`, `media.write_chapters`, `Chapter` (Task 2).
- Produces:
  - `clip_name(m: Moment) -> str` `f"{h}h{mm:02d}m{ss:02d}s - {prefix}{title}.mp4"`, prefix `"Clip that - "` for triggers; title stripped of `<>:"/\|?*` and trailing dots, collapsed spaces, at most 80 characters; empty title becomes `"moment"`.
  - `write_clips(src: Path, moments: list[Moment], out_dir: Path) -> list[Path]` cuts kept moments.
  - `write_moments_csv(moments: list[Moment], path: Path) -> None` columns `keep,start,end,score,kind,title,why,events,file` with times as `H:MM:SS`, utf-8-sig encoding so Excel opens it cleanly.
  - `write_resolve_edl(moments: list[Moment], path: Path, fps: float, timeline_start: str, title: str) -> None`: header `TITLE: {title}` and `FCM: NON-DROP FRAME`; per kept moment an event line `{n:03d}  001      V     C        {tc} {tc+1f} {tc} {tc+1f}` then ` |C:{color} |M:{name} |D:{frames}`. Frame positions are real frame indices `round(t * fps)` and durations `round(duration * fps)`, formatted as timecode with timebase `round(fps)` (so 59.94 footage does not drift 3.6 s per hour); colors `trigger/marker: ResolveColorRed`, `laughter: ResolveColorYellow`, `joke: ResolveColorBlue`, `game: ResolveColorPurple`, `loud: ResolveColorGreen`. The marker EDL has no note field, so `why` lives only in the CSV.
  - `youtube_chapters(entries: list[tuple[float, float, str]]) -> list[str]` returns `[]` unless first starts at 0, at least 3, each at least 10 s, ascending.
  - `build_highlight(clip_dir: Path, video_out: Path, chapters_out: Path) -> Path | None`: all `*.mp4` in `clip_dir` sorted by name, titles parsed from names, `media.concat`, chapters text written (empty file note if rules fail); None if the folder has no clips.
  - `archive_original(src: Path, done_dir: Path, moments: list[Moment], name: str) -> Path`: `media.write_chapters` into `done_dir / f"{name}.mp4"` using kept moments as chapters; verifies duration within 0.5 s of the source; then deletes `src`. On any failure removes the partial output, leaves `src` and raises.

- [ ] **Step 1: Write the failing tests**

```python
def test_clip_name_sanitizes():
    m = Moment(3760, 3800, 9, "trigger", title='Teddy\'s "best" run?: part/2')
    assert clip_name(m) == "1h02m40s - Clip that - Teddy's best run part2.mp4"

def test_youtube_chapter_rules():
    assert youtube_chapters([(0, 20, "a"), (20, 40, "b")]) == []
    assert youtube_chapters([(0, 20, "a"), (20, 25, "b"), (25, 60, "c")]) == []
    assert youtube_chapters([(0, 20, "a"), (20, 40, "b"), (40, 3700, "c")]) == ["0:00 a", "0:20 b", "0:40 c"]

def test_edl_lines():
    ms = [Moment(12.5, 42.5, 9, "trigger", title="Malenia", keep=True)]
    text = write_and_read_edl(ms, fps=59.94, timeline_start="01:00:00:00")
    assert "01:00:12:29 01:00:12:30" in text and "|C:ResolveColorRed |M:Malenia |D:1798" in text

def test_csv_has_all_moments(tmp_path):
    p = tmp_path / "m.csv"
    write_moments_csv([Moment(0, 30, 5, "loud"), Moment(60, 90, 9, "joke", keep=True)], p)
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    assert len(rows) == 2 and rows[1]["start"] == "0:01:00"

def test_highlight_handles_quotes_in_names(tiny_video, tmp_path):
    d = tmp_path / "clips"; d.mkdir()
    for i, t in enumerate(["Teddy's fall", "Big 'oops'", "Third"]):
        media.cut(tiny_video, i * 3, i * 3 + 3, d / f"0h00m0{i}s - {t}.mp4")
    out = build_highlight(d, tmp_path / "h.mp4", tmp_path / "h.txt")
    assert abs(media.probe(out).duration - 9) < 0.5

def test_archive_keeps_source_on_failure(tiny_video, tmp_path, monkeypatch):
    monkeypatch.setattr(media, "write_chapters", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        archive_original(tiny_video, tmp_path / "Done", [], "x")
    assert tiny_video.exists() and not (tmp_path / "Done" / "x.mp4").exists()
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_output.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `teddyclip/output.py` (attribution header).
- [ ] **Step 4: Run** the same command. Expected: all passed.
- [ ] **Step 5: Commit** `"Add clip, CSV, Resolve EDL, chapter and highlight outputs"`.

---

### Task 10: cli.py, inbox flow and check

**Files:**
- Create: `teddyclip/cli.py`, `teddyclip/__main__.py`, `TeddyClip.bat`, `Highlight.bat`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `main(argv: list[str] | None = None) -> int` subcommands: none (process inbox), `process <file>`, `highlight <clip folder>`, `check`; global `--config PATH`.
  - `is_finished(path: Path, quiet_seconds: float = 60, now: float | None = None) -> bool` true when mtime is older than `quiet_seconds` and the file opens for exclusive append.
  - `process_recording(path: Path, cfg: Config) -> Path` runs the spec section 4 pipeline: probe, extract 16 kHz (respecting `audio_track`) and 32 kHz audio into `cache/<key>/`, transcribe (hotwords = triggers), `release()`, features, people sounds, sweep, fuse, peak windows, forced windows from triggers and OBS chapters, snap, merge, screen events if the profile has a lexicon, label, rerank, select, then `write_clips`, CSV, EDL, `archive_original`. Cache key = `f"{name}-{size}-{int(mtime)}"`. Output folder name = `f"{date} {game title}"` from mtime and the inbox subfolder (or the file stem). Returns the clip folder.
  - `process_inbox(cfg: Config) -> int` processes every finished `*.mp4`/`*.mkv` under `inbox` (recursively), catching per-file exceptions, printing a summary; returns count of failures.
  - `check(cfg: Config) -> int` prints `[ok]`/`[fail]` lines with fix hints for: ffmpeg, NVENC, CUDA for whisper, Ollama reachable, configured model pulled, PANNs assets present, RapidOCR import, folders exist; returns number of failures.
  - `TeddyClip.bat`: `@echo off`, runs `"%~dp0.venv\Scripts\teddyclip.exe"`, then `pause`. `Highlight.bat`: asks for a folder (drag and drop path as `%1`) and runs `teddyclip highlight %1`.

- [ ] **Step 1: Write the failing tests** (pipeline heavy steps monkeypatched: `transcribe`, `people_sounds`, `audio_features`, `LLM.ask`)

```python
def test_is_finished(tmp_path):
    f = tmp_path / "r.mp4"; f.write_bytes(b"x")
    assert not is_finished(f, quiet_seconds=60)
    assert is_finished(f, quiet_seconds=60, now=time.time() + 120)

def test_process_recording_end_to_end(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    out = process_recording(stage_in_inbox(tiny_video, cfg, game="Elden Ring"), cfg)
    names = [p.name for p in out.glob("*.mp4")]
    assert any("Clip that" in n for n in names)
    assert (out / "moments.csv").exists() and (out / "Resolve markers.edl").exists()
    assert list(cfg.paths.done.glob("*.mp4")) and not list(cfg.paths.inbox.rglob("*.mp4"))

def test_process_recording_with_no_moments(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=None, flat_signals=True)
    out = process_recording(stage_in_inbox(tiny_video, cfg), cfg)
    assert not list(out.glob("*.mp4"))
    assert (out / "moments.csv").read_text(encoding="utf-8-sig").startswith("keep,")
    assert list(cfg.paths.done.glob("*.mp4"))

def test_inbox_continues_after_failure(fake_pipeline, tiny_video, cfg, monkeypatch):
    a = stage_in_inbox(tiny_video, cfg, name="a.mp4"); b = stage_in_inbox(tiny_video, cfg, name="b.mp4")
    real = cli.process_recording
    monkeypatch.setattr(cli, "process_recording", lambda p, c: (_ for _ in ()).throw(RuntimeError()) if p == a else real(p, c))
    monkeypatch.setattr(cli, "is_finished", lambda p, **k: True)
    assert process_inbox(cfg) == 1 and a.exists() and not b.exists()

def test_check_reports_missing_ffmpeg(cfg, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert check(cfg) >= 1 and "ffmpeg not found" in capsys.readouterr().out
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `teddyclip/cli.py` (argparse), `__main__.py`, and the two bat files. `fake_pipeline` and `stage_in_inbox` fixtures go in `tests/conftest.py`.
- [ ] **Step 4: Run** the full suite `.venv\Scripts\python -m pytest -v`. Expected: all passed, slow tests deselected.
- [ ] **Step 5: Commit** `"Add CLI, inbox processing, check command and launchers"`.

---

### Task 11: README, OBS setup and real-footage check

**Files:**
- Modify: `README.md`
- Create: `docs/obs-setup.md`, `docs/real-footage-checklist.md`

- [ ] **Step 1: README** gains Quick start (spec section 11 steps, with the exact `pip` commands from Task 1), the folder flow diagram from spec section 3, a config summary, and keeps Roadmap, Built on and License. Status line changes to "v1: works end to end; tuning on real footage."
- [ ] **Step 2: `docs/obs-setup.md`**: Settings > Output > Recording Format "Hybrid MP4"; Settings > Hotkeys "Add Chapter Marker" (optional clip button); Audio tracks: track 1 full mix, mics alone on track 2, then `audio_track: 2` in config; Recording Path pointed at `TeddyClip\1 Inbox\<Game>`.
- [ ] **Step 3: `docs/real-footage-checklist.md`**: run `teddyclip check`; process one real session; confirm every "clip that" produced a clip; rate the top 10 clips; for a Souls session confirm YOU DIED events in `moments.csv`; import `Resolve markers.edl` via Media Pool right-click > Timelines > Import > Timeline Markers from EDL and confirm positions; try 2 models (`qwen3:4b`, `gemma3:4b`) and record which titles better; note misheard trigger variants to add to `triggers`.
- [ ] **Step 4: Run** `grep -rnP "\x{2014}|\x{2013}" README.md docs teddyclip prompts config.yaml` (em and en dash code points). Expected: no output.
- [ ] **Step 5: Commit** `"Document install, OBS setup and real-footage checklist"`.

---

## Execution notes

- Branch: work continues from `docs/design-spec` (it carries the AGPL license that copied code requires). Create `feat/v1` from it before Task 1.
- Clips Kitty reference clone: `C:\Users\wsmith\ck-ref\repo` at commit `f098e39`. Treat it as read-only source to copy from.
