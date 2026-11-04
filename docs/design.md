# TeddyClip design (v1 MVP)

Date: 2026-11-03. Status: v1 built and tested on synthetic media; tuning on real footage. Sections 3, 4.2, 5, 9, 11 and 12 were updated after the build to match the decisions made along the way.

## 1. Purpose

TeddyClip turns long OBS recordings of two friends playing games on a couch into a short set of ready-to-post clips, plus markers on the original recording, so reviewing a 4 hour session takes about 30 minutes instead of hours.

**Who it is for:** a non-developer running it on their own Windows PC (RTX 3060, 6 or 12 GB, unconfirmed). One double-click per batch of recordings.

**What success looks like:**
- Every moment where someone said "clip that" ends up as a clip. No exceptions.
- Most of the remaining clips are moments they would have picked themselves, including quiet jokes, not just loud ones.
- Nothing costs money to run. All AI runs locally.
- Their DaVinci Resolve workflow gets every moment as a marker on the full recording.

**Content profile:** two laid-back people, a couch cam, lots of games (Dark Souls, Elden Ring, Red Dead, Counter-Strike, GTA, golf games, Wii Sports and other older titles). The best moments are usually reactions and jokes, often quiet ones, not on-screen events.

## 2. Scope

### In the v1 MVP
- Inbox, clips and highlights folder flow, `TeddyClip.bat`.
- Transcription with word timestamps, cached.
- Signals: "clip that" spoken triggers, OBS chapter markers, PANNs laughter and shouting, loudness relative to their own baseline, voice jumps.
- Per-game on-screen text events (YOU DIED, ENEMY FELLED, WASTED, and so on) via OCR, chosen by game.
- Local small model (Ollama): transcript sweep for quiet jokes, window labeling (title, score, trim), head-to-head rerank.
- Outputs: 16:9 clips, `moments.csv`, DaVinci Resolve marker EDL, chapters embedded in the original, highlight video plus YouTube chapters.
- `teddyclip check` for setup verification.

### Roadmap (not v1)
- 9:16 Shorts with burned-in, word-synced captions.
- Couch-cam layouts for Shorts.
- A simple local review UI.
- Tightening silences and filler words inside clips.
- Telling the two speakers apart (diarization).
- Compilations ("died to this boss 12 times, then won").

### Explicitly out (Clips Kitty features we do not take)
Translation, subtitles in other languages, dubbing, text to speech; publishing, scheduling, campaigns, watched channels; YouTube, Twitch and Kick downloads; cloud LLMs, OpenRouter, sign-ins, API keys; face tracking (YOLO, TalkNet), sports modes, podcast multi-cam, vertical live; web server, HTTP API, MCP server, desktop UI, plugin system, job queue, database, feedback reporting; creator profiles, AI edit chat, watermarks, outros, thumbnails, chat replay, YouTube heatmaps.

## 3. Folder flow

All media lives outside the repo and outside Google Drive. The root defaults to `C:\Users\<user>\TeddyClip` and is set in `config.yaml`.

```
TeddyClip\
  1 Inbox\
     Elden Ring\                      subfolder name = game (optional)
        2026-11-01 20-14-03.mp4
  2 Clips\
     2026-11-01 Elden Ring\
        0h12m40s - Teddy gets ganked by dogs.mp4
        1h03m15s - Clip that - Malenia rage quit.mp4
        moments.csv
        Resolve markers.edl
  3 Highlights\
     2026-11-01 Elden Ring.mp4
     2026-11-01 Elden Ring - chapters.txt
  Done\
     2026-11-01 Elden Ring.mp4        original, with chapters embedded (keeps its extension: .mkv stays .mkv)
  .cache\                             transcripts, signals, LLM answers, model weights
```

**Flow:**
1. They drop recordings into `1 Inbox`, optionally inside a folder named after the game, or point OBS's recording path there.
2. They double-click `TeddyClip.bat` (runs `teddyclip`). Each finished recording in the inbox is processed: moments found, clips cut, CSV and markers written, original moved to `Done` with chapters embedded.
3. They watch the clips and delete the ones they do not want.
4. They drag the clip folder onto `Highlight.bat` (which runs `teddyclip highlight "2 Clips\2026-11-01 Elden Ring"`). The remaining clips are joined in order into a highlight video with chapters.

**Rules:**
- A file is only processed once it has stopped growing for 10 seconds and can be opened exclusively, so a recording in progress is never touched.
- The game comes from the inbox subfolder name, then from a keyword in the filename, then falls back to `generic`.
- Recordings are never deleted. Moving to `Done` with chapters is a remux into `Done` that keeps the original's container extension (an `.mkv` stays `.mkv`); the inbox copy is removed only after the new file's duration matches. On any failure the original stays in the inbox and an error is printed.
- `teddyclip process <file>` on a file outside the inbox still writes the clips and a copy into `Done`, but leaves the original where it is.
- A recording with no audio track is refused with a plain message pointing at OBS's audio track setting; it stays in the inbox.
- Re-processing the same file reuses the transcript and AI answers in `.cache`, keyed by file name, size and modified time. The extracted WAV files are deleted after a successful run, because they run over 1 GB per 4 hours; they are rebuilt if the recording is processed again.

## 4. Pipeline

```
recording
  -> probe          duration, frame rate, audio tracks, OBS chapter markers (ffprobe)
  -> extract audio  16 kHz mono for whisper and features; 32 kHz for PANNs (ffmpeg)
  -> transcribe     faster-whisper, word timestamps, language from config (en), cached
  -> signals        per 1 second bin, normalized within the video
  -> candidates     peak windows from fused signals + forced trigger windows
  -> detectors      OCR on sampled frames inside candidate windows (if the game has a lexicon)
  -> sweep          local model scores 2 minute transcript slices for jokes
  -> label          local model titles, scores and trims each candidate window
  -> rerank         local model orders the finalists head to head
  -> select         triggers always; then best scores spread across the session, up to max_clips
  -> outputs        clips, moments.csv, Resolve EDL, chapters in original
```

### 4.1 Signals (per 1 second bin)

| Signal | How | Source |
|---|---|---|
| Trigger | Word-level match of trigger phrases ("clip that", "clip it", "clip this", configurable) over transcript words, lowercase and punctuation stripped. The first word may be a close misspelling (difflib ratio at least 0.8, not an inflection such as "clips"), plus the one known mishear "clipped" before a "th" word ("clipped that"); every later word must match exactly. Consecutive words are at most 1 s apart, and no word but the last may end a sentence (. ! ?), so "...a clip. That was..." does not fire; a comma is fine. Repeats within 5 s collapse. Time = phrase start | Ours |
| Marker | OBS chapter markers from the file | Ours |
| Laughter / shouting | PANNs AudioSet tagger, 2 s window each second; Laughter, Belly laugh, Giggle, Chuckle, Snicker groups and a Scream/Shout/Yell group; each scored against its own rolling 90 s median | Clips Kitty `panns.py`, `game_audio.py` |
| Loudness, spike, burst | RMS per second, ratio to rolling 30 s median, onset density | Clips Kitty `audio_features.py` |
| Voice jump | A laugh or shout 2 to 3.5x the speaker's own level over +/-60 s | Clips Kitty `fusion._voice_jump` |
| Joke sweep | Local model score per 2 minute transcript slice (30 s overlap), spread over its seconds | Ours, prompt adapted from Clips Kitty `score_clips.txt` |
| Screen text | OCR event hits (e.g. YOU DIED) | Clips Kitty `game_text.py` |

**Fusion:** each signal is percentile-normalized within the video, weighted (weights in `config.yaml`), and combined with a soft OR (1 minus the product of misses), following Clips Kitty's `_pct` and `_soft_or`. Peaks above a percentile become candidate windows.

**Audio track:** if `audio_track` is set (their mics recorded separately in OBS), that track is used for transcription and people-sound signals; clips always use the full mix (track 1).

### 4.2 Candidate windows
- **Trigger or OBS marker:** window = [t - 45 s, t - 0.3 s], ending just before the phrase so "clip that" is not in the clip. Always kept, never dropped by scoring or caps.
- **Signal peak:** window from 20 s before to 15 s after the peak, expanded to sentence boundaries from the transcript.
- **Screen events:** OCR runs only inside candidate windows, sampling a frame every 2 s, because scanning a whole 4 hour video on CPU is too slow. A hit (e.g. YOU DIED) is attached to the window and raises its score by the `screen_text` weight.
- Overlapping windows merge. When a "clip that" window merges with a nearby signal moment, the merged clip still ends before the phrase (at the latest forced end), so the trigger words are never in the clip. Forced windows are also never dropped or lengthened for being shorter than the minimum length. Duplicates are removed with Clips Kitty's three checks (time overlap over 40 percent, transcript text similarity over 70 percent, shared segments over 40 percent).
- Lengths are clamped to 20 s to 120 s (configurable).

### 4.3 Local model
- **Backend:** Ollama's native `/api/chat`, with `format` set to a JSON schema, an explicit `num_ctx`, thinking disabled, 3 retries, and Clips Kitty's lenient JSON parsing as a fallback. One file, about 80 lines.
- **Model:** a 3 to 4 B instruct model (Qwen or Gemma class) chosen by testing on real footage; set in config.
- **GPU order:** whisper runs and is released before Ollama is called.
- **Three prompts**, as plain text in `prompts/`:
  - `sweep.txt`: "Is there a funny exchange, joke or great line in this slice? Score 1 to 10, quote the line." Tuned for couch humor and in-jokes, not virality.
  - `label.txt`: per window, given transcript and events: score 1 to 10, a short title using their names from config, optional trim inside the window.
  - `rerank.txt`: finalists compared head to head, returning an order; the rank can only raise a score (Clips Kitty's approach).
- **Caching:** every answer is cached by prompt text, input and model name.
- **`llm: none`:** everything except the sweep still works; titles fall back to a transcript snippet.

### 4.4 Selection
- All trigger and marker windows are selected.
- The rest fill up to `max_clips` (default 40) by score, with no more than 22 percent from any one eighth of the session so a single long boss fight cannot take every slot (Clips Kitty `highlight_select.py`).

## 5. Outputs

| Output | Details |
|---|---|
| Clips | `<h>h<mm>m<ss>s - <title>.mp4` at the recording's own resolution; triggered ones get `Clip that - ` before the title. Frame-accurate re-encode, NVENC with CPU retry, audio loudness-normalized to -14 LUFS, short audio fades. Clips Kitty `cutter.py`, `encoding.py`. |
| `moments.csv` | Every candidate, kept or not: start, end, score, title, why, signals, file name. Opens in Excel. |
| `Resolve markers.edl` | Timeline markers as CMX 3600 EDL with Resolve marker comments: duration = moment length, name = title, color by type (red trigger and OBS marker, yellow laughter, blue joke sweep, purple game event, green loud). The marker EDL format has no note field, so the "why" lives only in `moments.csv`. Timeline start (default 01:00:00:00) is in config; the frame rate is read from the recording. Positions use real frame indices, so 59.94 fps footage does not drift. Ours. Must be verified by importing in their Resolve version. |
| Chapters in original | ffmetadata chapters written during a no-re-encode remux into `Done`, one per kept moment. The file keeps its container extension (`.mkv` stays `.mkv`). Because the container makes chapters gapless, a leading "Start" chapter is added when the first moment starts later than the beginning. Ours. |
| Highlight video | Remaining clips in `2 Clips\<recording>` joined in time order with a lossless concat at source resolution. It is not scaled to 1920x1080: the clips are all cut from the same recording, so they already match each other (Clips Kitty `assemble.py`, trimmed). |
| `chapters.txt` | YouTube chapter list obeying YouTube's rules (starts at 0:00, at least 3 chapters, each at least 10 s), or nothing if they cannot be met. Clips Kitty `chapters.py`. |

## 6. Code layout

```
TeddyClip/
  teddyclip/
    cli.py          entry point: (no args) process inbox | process <file> | highlight <folder> | check
                    (process <file> outside the inbox leaves the original in place)
    config.py       loads config.yaml over built-in defaults; paths
    media.py        ffprobe/ffmpeg: probe, audio extract, frames, chapters read/write, cut, concat, encoder pick
    transcribe.py   faster-whisper with cache and GPU/CPU fallback
    panns.py        AudioSet tagger model (MIT, Kong; via Clips Kitty)
    signals.py      audio features, laughter groups, voice jumps, triggers, markers, fusion
    detectors.py    screen-text OCR events with per-game lexicons
    llm.py          Ollama client with JSON schema, retries, cache
    moments.py      candidates, sweep, label, rerank, dedupe, selection
    output.py       clips, moments.csv, Resolve EDL, chapters, highlight, move to Done
  prompts/          sweep.txt, label.txt, rerank.txt
  config.yaml       folders, people names, triggers, games and lexicons, weights, lengths, model
  TeddyClip.bat
  tests/
  pyproject.toml  README.md  LICENSE  NOTICE  .gitignore
```

Ten code files. Each has one job and can be tested alone; `moments.py` and `output.py` take plain data (lists of windows) rather than calling each other.

**Dependencies:** faster-whisper, numpy, PyYAML, requests, torch (CPU build is enough for PANNs, which runs about 120x realtime on CPU), rapidocr-onnxruntime (pulls in OpenCV for frame reading). External: ffmpeg, Ollama. PANNs weights (MobileNetV1, Zenodo record 3987831) and the AudioSet label list are downloaded on first run into `.cache\models`, never committed.

## 7. Code reuse and credit

TeddyClip copies and adapts code from Clips Kitty (AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9), so TeddyClip is licensed AGPL-3.0-or-later.

| TeddyClip | Taken from Clips Kitty | How |
|---|---|---|
| `media.py` | `video/encoding.py` (encoder probe and select, loudnorm args, concat), `video/cutter.py` (cut with CPU retry), `core/gpu.py` | Adapt |
| `transcribe.py` | `transcription/transcriber.py` (model load, run, repetition-loop fix, cuBLAS check) | Adapt, cloud path removed |
| `panns.py` | `analysis/panns.py` | Copy, keeping Kong's MIT notice |
| `signals.py` | `analysis/audio_features.py`, `analysis/game_audio.py`, `fusion._pct`, `_soft_or`, `_window_peak`, `_voice_jump`, peak-window helpers | Copy and adapt |
| `detectors.py` | `analysis/game_text.py` (`Lexicon`, frame reading, text normalization), `config/gaming.yaml` screen-text lists | Adapt |
| `llm.py` | `llm/ollama_backend.py` retry and reasoning handling | Adapt |
| `moments.py` | `analysis/highlights.py` dedupe and JSON parsing, `fusion._rerank`, `longform/highlight_select.py` | Adapt |
| `output.py` | `longform/chapters.py`, `longform/assemble.py` (trimmed) | Copy and adapt |
| `prompts/` | `score_clips.txt`, `score_windows.txt`, `rerank.txt` | Rewritten for couch humor |

**Ours:** the inbox flow and growing-file check, game selection, "clip that" triggers, OBS markers, the joke sweep, Resolve EDL markers, chapters in the original, selection rules for triggers, the CLI, config and check command.

**How credit is given:**
- Each file with copied code starts with a short header: `Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.`
- `NOTICE` lists Clips Kitty, PANNs (MIT, Qiuqiang Kong), PANNs weights and AudioSet labels (CC BY 4.0), faster-whisper (MIT), RapidOCR (Apache-2.0).
- The README has a short "Built on" section.

## 8. Config (sketch)

```yaml
root: C:\Users\{user}\TeddyClip
people: [Teddy, Friend]            # used in titles
triggers: ["clip that", "clip it", "clip this"]
audio_track: null                  # e.g. 2 if mics are on their own OBS track
whisper_model: auto                # large-v3-turbo on GPU, small on CPU
whisper_device: auto               # auto (GPU when it works) or cpu (never use the GPU)
language: en                       # spoken language for whisper; null lets whisper detect it
llm:
  model: qwen3:4b                  # or "none"; final choice after testing
  url: http://127.0.0.1:11434
clips:
  min_seconds: 20
  max_seconds: 120
  max_clips: 40
  pre_trigger_seconds: 45
weights: {laughter: 1.0, joke_sweep: 0.7, loudness: 0.6, voice_jump: 0.6, screen_text: 0.6}
games:
  elden ring: soulslike
  dark souls: soulslike
  gta: sandbox
  counter strike: shooter
  red dead: sandbox
lexicons:                           # from Clips Kitty gaming.yaml, trimmed to English
  soulslike: ["YOU DIED", "ENEMY FELLED", "GREAT ENEMY FELLED", "DEMIGOD FELLED", "VICTORY ACHIEVED", "HEIR OF FIRE DESTROYED"]
  sandbox: ["WASTED", "BUSTED", "MISSION PASSED", "MISSION FAILED"]
  shooter: ["ROUND WON", "ROUND LOST", "ACE", "BOMB PLANTED", "BOMB DEFUSED"]
resolve:
  timeline_start: "01:00:00:00"
```

The model name above is a placeholder until tested.

## 9. Errors

- Every external failure is reported in plain words with the fix, e.g. "ffmpeg not found: see README step 2" or "Ollama is not running: continuing without AI titles".
- One bad recording never stops the batch; it stays in the inbox and the error is listed at the end.
- A recording with no audio track is refused up front with a plain message ("has no sound track", with where to look in OBS) rather than producing empty results.
- NVENC failure on a clip retries on CPU. CUDA failure in whisper falls back to CPU, and `whisper_device: cpu` skips the GPU entirely for PCs where it crashes.
- The first Ollama problem (a refusal with the server's own error text, or a failure) is printed once. After 3 failed asks in a row the client turns itself off for the rest of that recording ("Ollama stopped answering: continuing without AI for this recording").
- Before any clip is cut, the free space on the Done drive is checked against the recording's size, so a full disk fails early with a plain message. A run that fails after its clip folder was made renames it to "<name> (incomplete)", so the next run gets the clean name. The end-of-batch summary shows the last meaningful line of each error.
- When OBS remuxed an .mkv to .mp4, the inbox holds both: the .mkv is skipped as a duplicate.
- `teddyclip check` verifies ffmpeg, NVENC, CUDA for whisper, Ollama and the configured model, PANNs weights, OCR, and that the folders exist, printing a pass or fail list.

## 10. Testing

- **Unit tests (no media):** trigger fuzzy matching against misheard variants, percentile normalization and soft OR, peak windows and merging, dedupe, section-capped selection, time formatting, YouTube chapter rules, EDL formatting, LLM JSON parsing on messy replies, growing-file check.
- **End-to-end test:** builds a tiny video on the fly with ffmpeg (test pattern plus tones and silence), runs cut, concat, chapter embed and EDL writing, and checks durations and metadata. No media is committed.
- **Real-footage check (manual):** one real session; confirm every "clip that" came out, the top 10 clips are good, YOU DIED events are found in a Souls session, and the EDL imports into Resolve. Also confirm `think: false` causes no Ollama errors with the chosen model, that GPU transcription and NVENC are really used, that VRAM holds when whisper and Ollama run back to back in a batch, and whether "clip" said in other contexts causes false triggers. Tune weights from there. The step-by-step list is `docs/real-footage-checklist.md`.

## 11. Install (for the README)

1. Python 3.12 from python.org, not newer: rapidocr-onnxruntime 1.4.4 has no wheels for 3.13 or later, so `requires-python` is `>=3.11,<3.13`.
2. `winget install Gyan.FFmpeg`.
3. Ollama from ollama.com, then `ollama pull qwen3:4b` (the configured default, a starting point to be tested).
4. Download TeddyClip (git clone or ZIP). In its folder: `py -3.12 -m venv .venv`, `.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu`, then `.venv\Scripts\pip install -e .`.
5. On an NVIDIA PC, `.venv\Scripts\pip install -e .[gpu]` adds the CUDA 12 libraries faster-whisper needs (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12==9.10.*`, matching CTranslate2, which is pinned to `>=4.8,<4.9`). GPU transcription needs these plus an up-to-date NVIDIA driver; without them everything still works on the CPU, slower. `cuda_usable()` asks CTranslate2 (not PyTorch, which is the CPU build) whether a GPU exists, and the DLL folders of those packages are added before a CUDA model loads. This path has not yet been tested on a real GPU.
6. `.venv\Scripts\teddyclip check`, then use `TeddyClip.bat`. The first run downloads the whisper model and the PANNs weights.
7. OBS setup page (`docs/obs-setup.md`): Hybrid MP4 output, optional chapter marker hotkey, optional separate mic track, recording path pointed at `1 Inbox`.

## 12. Open items to confirm on real footage

- Which 3 to 4 B model titles and scores best.
- Whether "clip that" is transcribed reliably, and which misheard variants to add.
- Resolve EDL marker import on their Resolve version.
- RTX 3060 VRAM (6 or 12 GB); the whisper model choice adapts automatically.
- Whether their OBS records mics on a separate track.
- Whether `think: false` in Ollama requests is accepted by the chosen model without errors.
- Whether GPU transcription and NVENC are used in practice, and whether VRAM is enough when whisper and Ollama run back to back.
- Whether "clip" said in other contexts (for example a Counter-Strike magazine) causes false triggers.
