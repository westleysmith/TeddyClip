# Clip editor: review suggestions on the original recording

Date: 2026-11-04. Status: design approved in chat, waiting for spec review.

## Why

Clips cut automatically often start at the wrong moment. On the Lego Star Wars test, the laugh the tagger heard came about 40 s after the setup began, so the clip started at the reaction and missed the joke. Teddy is the main user and is not technical. He needs to see what was said around a moment, nudge where the clip starts and ends, and only then make the clip.

## What changes for the user

1. **Find clips** (the button that used to say Make clips) analyzes the ticked raw recordings exactly as today, but cuts nothing. It saves suggestions. Automatic mode does the same.
2. Each session on the main screen lists its **suggestions** (kind badge, title, "at 5:44 · 59s", a Review button) and, below them, the **clips already made** (playable cards, as today, each with an Edit button).
3. Review or Edit opens the **editor** on that moment (layout approved in chat):
   - Left: the original recording in a large player. Under it, a strip for the whole recording that shows every suggestion as a block and laughter and yelling as ticks; clicking it seeks there. Under that, a zoomed strip for the current clip (20 s either side) with draggable start and end edges, plus Start -5s/+5s and End -5s/+5s buttons, a Play clip button, a title box, and **Create clip**.
   - Right: the transcript, which scrolls with playback and highlights the lines inside the clip, with a search box over the whole recording and laughter or yelling labels on lines. Clicking a line seeks there; Start clip here and End clip here set the edges from the current line.
   - Top: Back, the session name, and arrows to step through the suggestions.
4. Teddy can make a clip anywhere: search the transcript or click the whole-recording strip, then set start and end. It does not have to come from a suggestion.
5. **Create clip** cuts the range from the original into `2 - Clips/<session>/` with the usual name (`0h05m41s - <title>.mp4`). That suggestion then shows as made. Editing a made clip and pressing Create clip again replaces that file.
6. "Clip that" and OBS marker moments are suggestions like the rest (listed first, with their badge). Nothing is cut without a confirm.
7. Make highlight works as today, from the clips in the session's clip folder.
8. Sessions made before this change keep showing their clips as today, without suggestions or the editor.

## Folders

- `1 - Raw recordings`: unchanged (waiting to be analyzed).
- `2 - Clips/<session>/`: created when the session is found (empty until clips are made), so Archive and Restore keep working on folders as they do now. Holds only clips.
- `4 - Finished recordings`: the original is **moved** there after analysis, without the chapter-marker copy (the editor replaces it, and the copy doubled disk use on long recordings). A recording processed from outside Raw recordings (command line) stays where it is and is referenced in place.
- `.cache/sessions/<session>/`: TeddyClip's own files, `session.json` (below), the legacy `moments.csv`, and a `preview.mp4` when one is needed.

## Session file

`.cache/sessions/<session>/session.json`, written at the end of analysis and updated when clips are made:

```json
{
  "version": 1,
  "name": "2026-11-04 Lego Star Wars",
  "recording": "C:/Users/<you>/TeddyClip/4 - Finished recordings/2026-11-04 Lego Star Wars.mp4",
  "preview": null,
  "duration": 599.4,
  "segments": [{"start": 345.1, "end": 347.0, "text": "Now for the game to end I have to kill you."}],
  "cues": {"laughter": [0, 0, 0.68], "yelling": [0, 0.49, 0]},
  "suggestions": [{"id": 1, "start": 341.2, "end": 400.1, "kind": "laughter", "score": 10.0,
                   "title": "...", "why": "...", "events": []}],
  "made": [{"file": "0h05m41s - Worst ending ever.mp4", "start": 341.2, "end": 400.1,
            "title": "Worst ending ever", "suggestion": 1}]
}
```

- `cues` hold one value per second, rounded to 2 decimals: `laughter` is the PANNs laughter strength, `yelling` the higher of the shout strength and the voice jump. A 4 hour recording is about 30k numbers, well under 1 MB with the transcript.
- `suggestions` are the moments `select` keeps today, in time order.
- Written with a temp file and `os.replace`, so a crash never leaves half a file.

## Playback

The editor plays the original through the local server, so it must be a format Edge WebView2 can play.

- MP4 or MOV with H.264 (the OBS default, and the test file): played as is.
- MKV with H.264: remuxed to MP4 as part of the move to Finished recordings (no re-encode, seconds to a few minutes). The duration is checked against the original before the MKV is removed, as `archive_original` does today.
- Other video codecs (H.265, AV1): a 720p H.264 `preview.mp4` is made in the session folder with the hardware encoder, and the editor plays that. Cuts always come from the original, so clip quality is unaffected.

## Server

New routes in `ui.py`, same origin checks as today:

- `GET /edit?session=<name>&s=<suggestion id>` (or `&clip=<file>`): the editor page, `teddyclip/editor.html`.
- `GET /api/session/<name>`: the session file plus a media URL for each made clip.
- `GET /media/recording/<name>`: the session's preview if it has one, else its recording, with Range support. The path comes only from `session.json`, never from the request.
- `POST /api/cut {session, start, end, title, replace?}`: checks `0 <= start < end <= duration` and a length of 1 s to 10 min, turns the title into a safe file name (as `clip_name` does), cuts with `media.cut` from the original, and records it in `made`. With `replace` (an existing file in that session's folder), that file is replaced. Cuts run one at a time on their own small queue, separate from the analysis job, so Teddy can make clips from one session while another is still being analyzed. The page shows a short "Cutting..." state on the button.

`state()` lists, per session, its suggestions (each marked made or not) and its clips. Sessions with no `session.json` are listed as today.

## Pipeline

- `process_recording(path, cfg, cut=False)`: unchanged up to `select`. Then it writes `session.json` and `moments.csv`, moves the original (with the MKV remux or preview when needed), deletes the WAVs, and stops. With `cut=True` it also cuts every suggestion as today.
- The command line gets `--cut-all` for the old behavior (and the existing tests that expect clip files use it).
- The progress bar loses its "Cutting clips" band. "Filing the original" covers the move, plus the remux or preview when one is needed.

## Errors

- The recording is missing (moved or deleted by hand): the editor says so and offers Open folder. Suggestions stay listed.
- A cut fails (disk full, ffmpeg error): the button shows the reason in the usual dialog. No half-written file is left (cuts already write to a temporary name).
- A suggestion's range runs past the end of a truncated recording: clamped to the duration.

## Testing

- Unit: `session.json` contents and its atomic write; the playback decision for MP4/H.264, MKV/H.264 and H.265 inputs (small synthetic files); `/api/session`, `/media/recording` (Range, and no path from the request); `/api/cut` validation (bad ranges, unknown session, unsafe titles, `replace` outside the folder) and its output file and `made` entry; `state()` for new and legacy sessions; `process_recording` cuts nothing by default and everything with `cut=True`.
- In the app, on the Lego recording: open a suggestion, search the transcript, drag an edge, Play clip, Create clip, then confirm the file appears in the session and plays.

## Not in this change

Thumbnail filmstrips, waveforms, low-res proxies for H.264 sources, keyboard shortcuts, cutting out the middle of a clip, and undo. Add them later if reviewing feels slow.
