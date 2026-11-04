# Clip Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find clips saves suggestions instead of cutting; an editor plays the original with a synced, searchable transcript and cues, and Create clip cuts the chosen range.

**Architecture:** The pipeline writes `.cache/sessions/<session>/session.json` (transcript, per-second cues, suggestions, made clips) and files the original in a format the window can play. The local server gains routes to read a session, stream its recording, and cut a range. A new `editor.html` page does the reviewing; `ui.html` lists suggestions.

**Tech Stack:** Python 3.12, ffmpeg/ffprobe, stdlib `http.server`, plain HTML/JS in Edge WebView2 (pywebview), pytest.

**Spec:** `docs/superpowers/specs/2026-11-04-clip-editor-design.md`

## Global Constraints

- No em dashes anywhere (code comments, copy, docs). Use a hyphen or restructure.
- Commits carry no `Co-Authored-By` trailer.
- No new Python or JS dependencies; JS stays inline, no CDN (the app runs offline).
- Media writes go through `media._writing` (temp name, then rename).
- The server only serves paths it derives itself; never a path from the request.
- Clip length 1 s to 600 s; ranges clamped to `0..duration`.
- Cue arrays: one value per second, rounded to 2 decimals.
- Run tests with: `export PATH="/c/Users/wsmith/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin:$PATH" && /c/Users/wsmith/.venvs/teddyclip/Scripts/python -m pytest -q -p no:cacheprovider`

## Review Focus

- Restoring an archived session next to a newer one renames its clip folder to "<name> (2)"; its session file must follow, or the editor loses it. Test in Task 5.
- The recording was moved or deleted by hand: `/media/recording` gives 404, `/api/cut` gives a plain 400 message, nothing crashes. Test in Task 5.
- Create clip twice with the same title (or a title equal to an existing clip) must not overwrite unless it is the `replace` target. Test in Task 5.
- Titles with `:?"/\*<>|`, only spaces, or emoji must still give a valid Windows file name. Test in Task 5.
- Making a clip while Find clips runs on another recording must work (cuts do not use the analysis `Job`). Test in Task 5.

---

### Task 1: Playback formats

**Files:**
- Modify: `teddyclip/media.py` (`Probe`, `probe`, new helpers; remove `write_chapters` and `_escape_meta`)
- Test: `tests/test_media.py`

**Interfaces:**
- Produces: `Probe.video_codec: str` (ffprobe `codec_name`, "" when none); `window_playable(path: Path) -> bool`; `remux_to_mp4(src: Path, dst: Path) -> Path`; `make_preview(src: Path, dst: Path) -> Path`.

- [ ] **Step 1: Failing tests**

```python
def test_window_plays_h264_mp4_but_not_mkv_or_hevc(tiny_video, tmp_path):
    mkv = tmp_path / "a.mkv"; hevc = tmp_path / "h.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tiny_video), "-c", "copy", str(mkv)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tiny_video), "-c:v", "libx265", "-c:a", "copy", str(hevc)], check=True)
    assert probe(tiny_video).video_codec == "h264"
    assert window_playable(tiny_video) and not window_playable(mkv) and not window_playable(hevc)

def test_remux_mkv_to_mp4_keeps_length(tiny_video, tmp_path): ...  # duration within 0.2 s, codec h264, no .part left
def test_preview_is_small_h264(tiny_video, tmp_path): ...  # make_preview -> h264, height <= 720, duration within 0.3 s
```

- [ ] **Step 2: Run, expect failures** (`window_playable` not defined).
- [ ] **Step 3: Implement.** `window_playable`: suffix in `{.mp4, .m4v, .mov}` and `video_codec == "h264"`. `remux_to_mp4`: `-map 0:v:0 -map 0:a? -c copy -movflags +faststart -f mp4` via `_writing`. `make_preview`: `-vf scale=-2:'min(720,ih)'`, `encoder_args()` with the same CPU retry as `cut`, AAC 128k, `+faststart`, via `_writing`. Delete `write_chapters`, `_escape_meta`, `Chapter`-writing tests (keep `Chapter` for probe).
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit** "Know which recordings the window can play, and convert the rest".

### Task 2: Filing the original

**Files:**
- Modify: `teddyclip/output.py` (replace `archive_original` with `file_original`)
- Test: `tests/test_output.py` (replace the `archive_original` tests)

**Interfaces:**
- Consumes: Task 1 `remux_to_mp4`, `probe`.
- Produces: `file_original(src: Path, done_dir: Path, name: str, in_inbox: bool) -> Path`. Returns where the recording now is.

- [ ] **Step 1: Failing tests:** an inbox `.mp4` is moved (not copied) to `done/<name>.mp4`, same bytes, source gone; an inbox `.mkv` becomes `done/<name>.mp4` (remuxed, source deleted only after the length check); `in_inbox=False` returns `src` untouched and writes nothing; an existing destination raises `FileExistsError` and leaves `src`; a remux whose length is off by more than `ARCHIVE_TOLERANCE_SECONDS` raises and leaves `src` and no output.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.** Move with `os.replace`, falling back to `shutil.move` across drives. Free-space check (`ARCHIVE_ROOM`) only when remuxing.
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit** "File the original with a plain move".

### Task 3: Session file

**Files:**
- Create: `teddyclip/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Produces:
  - `session_dir(cfg, name: str) -> Path` (= `cfg.paths.notes / name`)
  - `build(name: str, recording: Path, preview: Path | None, duration: float, segments: list[Segment], laughter: np.ndarray, yelling: np.ndarray, moments: list[Moment]) -> dict` (shape exactly as in the spec; suggestions are the kept moments in time order, ids from 1, start/end clamped to `0..duration` and rounded to 0.1 s; titles fall back to the first words of the transcript inside the range)
  - `save(cfg, data: dict) -> Path` (atomic: `.tmp` then `os.replace`)
  - `load(cfg, name: str) -> dict | None` (None when missing or unreadable)
  - `record_made(cfg, name: str, entry: dict, replace: str | None = None) -> dict` (drops the `replace` entry and any entry with the same file, appends `entry`, saves, returns the data)

- [ ] **Step 1: Failing tests:** round trip of `build` + `save` + `load`; cues rounded and as long as `ceil(duration)`; a moment past the end is clamped; `load` of a missing or corrupt file is None; `record_made` with and without `replace`; `save` leaves no `.tmp`.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit** "Save each session's transcript, cues and suggestions".

### Task 4: Pipeline finds instead of cuts

**Files:**
- Modify: `teddyclip/cli.py` (`process_recording`, `process_inbox`, `main`), `TeddyClip.bat`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces: `process_recording(path: Path, cfg: Config, cut: bool = False) -> Path` (still returns the clip folder, now created empty); `process_inbox(cfg, only=None, cut: bool = False) -> int`; CLI `--cut-all` on both the bare command and `process`.

- [ ] **Step 1: Failing tests:** default run leaves the clip folder empty, writes `session.json` with suggestions, `cues.laughter`/`cues.yelling` of the right length and the transcript segments, and moves the original to Finished; `cut=True` also cuts every suggestion and lists each in `made`; `--cut-all` reaches `process_recording`. Update existing tests that expect clip files to pass `cut=True`; `test_process_outside_the_inbox_keeps_the_original` now expects no copy in Finished and `session.json` pointing at the original.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.** After `select`: `file_original` (band 0.90 to 0.97, "Filing the original"), then `make_preview` into the session folder when `not window_playable(recording)` (band 0.97 to 1.00, "Making a preview the window can play"), then `session.save(build(...))` with `yelling = np.maximum(shout, jumps)`, `write_moments_csv` as now, and with `cut` the existing `write_clips` plus `record_made` per clip. Print "Found N moments, suggesting M clips". `TeddyClip.bat` passes `--cut-all` (the console has no editor).
- [ ] **Step 4: Full suite passes.**
- [ ] **Step 5: Commit** "Find clips saves suggestions instead of cutting".

### Task 5: Server routes and cutting

**Files:**
- Create: `teddyclip/editing.py`
- Modify: `teddyclip/ui.py` (routes, `state`, `archive_session`, job names)
- Test: `tests/test_editing.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: Task 3.
- Produces:
  - `editing.CutError(ValueError)` with a plain message for the user
  - `editing.cut_clip(cfg, session: str, start: float, end: float, title: str, replace: str | None = None) -> Path` (one at a time via a module lock; validates, `clip_name` style name `0h05m41s - <safe title>.mp4`, unique unless it equals `replace`, cuts from `data["recording"]`, `record_made`)
  - `editing.safe_title(title: str, fallback: str) -> str`
  - `GET /edit` serves `teddyclip/editor.html`; `GET /api/session/<name>` returns the session plus `made[i].url` and `recording_url`; `GET /media/recording/<name>`; `POST /api/cut {session, start, end, title, replace?}` returns `{"file", "url"}` or 400 with `{"error"}`
  - `state()` sessions gain `suggestions: [{id, start, end, kind, title, made}]` and `editable: bool`, and each clip gains `edit: bool`

- [ ] **Step 1: Failing tests** (`test_editing.py` with `tiny_video` as the recording and a session saved through Task 3): a valid cut makes the file and a `made` entry; `start >= end`, length over 600 s, negative start, unknown session, and a deleted recording each raise `CutError` with a plain message; the same title twice gives " (2)"; `replace` overwrites that file only; `safe_title('a:b?"c/d')` is valid on Windows and `safe_title("   ", "fallback words")` uses the fallback; a cut works while `ui.Job` is running. In `test_ui.py`: `/api/session/<name>` (200, 404 for unknown, rejects `..`); `/media/recording/<name>` with Range, 404 after the file is deleted; `/api/cut` returns 200 with a file and 400 with `error` for a bad range; `/edit` serves HTML; `state()` lists suggestions with `made` set after a cut; unarchive into a taken name moves the session folder along with the clip folder.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.** Session lookup by `_plain_name`. The job names become "Finding clips" and "Finding clips (automatic)".
- [ ] **Step 4: Full suite passes.**
- [ ] **Step 5: Commit** "Serve sessions and cut chosen ranges".

### Task 6: Main screen

**Files:**
- Modify: `teddyclip/ui.html`

**Interfaces:**
- Consumes: Task 5 `state()` fields and `/edit?session=<name>&s=<id>` / `&clip=<file>`.

- [ ] **Step 1:** Button and copy say Find clips (button, auto switch text, empty states, help text). Each editable session shows a suggestions list (kind badge, title, "at 5:44 · 59s", a Made tag when made, a Review button linking to the editor) above its clip grid, and each clip with `edit` gets an Edit button. Non-editable sessions render as today.
- [ ] **Step 2: Verify in the browser pane** on a server started on port 8766 against a temp root seeded with one session: suggestions list, Review opens `/edit`, legacy session unchanged.
- [ ] **Step 3: Commit** "List suggestions on the main screen".

### Task 7: Editor page

**Files:**
- Create: `teddyclip/editor.html`

**Interfaces:**
- Consumes: `/api/session/<name>`, `/media/recording/<name>`, `POST /api/cut`.

- [ ] **Step 1: Build the page** per the approved mockup and the main page's mid-century styles: header (Back, session name, previous/next suggestion, "Suggestion n of N"); player; whole-recording strip (suggestion blocks, made blocks, laughter and yelling ticks drawn on a canvas, click to seek); zoomed strip for the current range plus 20 s either side with draggable start and end edges and a playhead; Start and End -5s/+5s; Play clip (plays start to end, then pauses); title box; Create clip (or Update clip when editing a made clip) with a "Cutting..." state and the error dialog on failure; transcript list with search (case-insensitive, highlights matches, Enter jumps to the next), follows playback, lines inside the range highlighted, laughter or yelling label on lines whose seconds pass 0.5, click to seek; Start clip here and End clip here at the playhead. Without `s` or `clip`, it opens on the first suggestion, or on 0:00 to 0:30 when there is none. Missing recording shows a message with Open folder.
- [ ] **Step 2: Verify in the browser pane** on the Lego session: transcript search finds "kill you", dragging and ±5s change the range text, Play clip stops at the end, Create clip makes a playable file that appears on the main screen, Update clip replaces it.
- [ ] **Step 3: Commit** "Add the clip editor".

### Task 8: Docs, install, review

**Files:**
- Modify: `README.md`, `docs/design.md`, `docs/obs-setup.md`

- [ ] **Step 1:** Docs describe Find clips, suggestions, the editor and `--cut-all`; drop the chapter-marker copy.
- [ ] **Step 2:** Full suite passes; copy `teddyclip/*.py`, `teddyclip/*.html`, `prompts/*.txt`, `TeddyClip.bat` into `C:\Users\wsmith\TeddyClip-app\`.
- [ ] **Step 3:** One fresh reviewer over the whole change against the spec and this plan; fix what it confirms.
- [ ] **Step 4: Commit and push.**
