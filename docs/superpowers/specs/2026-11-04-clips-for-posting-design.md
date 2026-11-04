# Clips for posting: YouTube links, shapes and captions

Date: 2026-11-04. Status: design approved in chat, waiting for spec review.

## Why

Teddy and friends post a gaming podcast, *Please Insert A Disc*, on YouTube: hour-long episodes that cut between a wide camera shot of the hosts and full-screen gameplay (episode 12: 58 minutes, Melee, 51 views). They want clips of each episode to post on TikTok, YouTube Shorts and Instagram to grow the channel, like OpusClip does, but free and on their own PC. Posting stays manual.

TeddyClip already finds the moments and has the editor. Missing: starting from a YouTube link, clip shapes other than the original, framing a wide shot into a tall one, and captions burned into the clip.

## What changes for the user

1. **Add recordings** also takes a YouTube link (their own videos). TeddyClip downloads it into `1 - Raw recordings\<game>\` and Find clips works as usual.
2. When the video has English captions on YouTube (auto or hand-made), TeddyClip uses them as the transcript and skips its own transcription.
3. In the editor, each clip gets three new controls, with a live preview of the result:
   - **Shape:** Original 16:9, Vertical 9:16, Square 1:1, Portrait 4:5.
   - **Framing** (not for 16:9): **Fit** shows the whole picture with a blurred copy behind it; **Fill** crops to the shape, with a slider to slide the crop left or right.
   - **Captions:** on or off.
4. **Create clip** renders the clip that way. Non-16:9 clips carry the shape in the file name (`0h05m41s - title (vertical).mp4`, `(square)`, `(4x5)`), so versions of one moment sit side by side. Edit reopens a clip with its shape, framing and captions.

Defaults when a clip is opened: shape Vertical 9:16, framing Fit, captions on. Picking 16:9 turns captions off; the other shapes turn them back on. Teddy can change any of them.

## Part 1: YouTube links

### Download

- New module `teddyclip/youtube.py`, adapted from Clips Kitty's `sources/youtube.py` and `sources/ytdlp_common.py` (credited in the file header and NOTICE). It uses the yt-dlp Python package (`yt-dlp` added to `pyproject.toml`).
- Format: H.264 at up to 1080p with M4A audio, merged to MP4 (Clips Kitty's format string), with ffmpeg found by `media.find_tool` and passed as `ffmpeg_location`. Live streams and upcoming premieres are refused with a plain message.
- Reliability, from Clips Kitty: retries per fragment, 10 MB chunks, a socket timeout, and one retry over IPv4 when YouTube answers with its bot check. Errors map to plain messages: private or removed video, age-restricted, bot check, no internet, and "YouTube changed something: run Install TeddyClip again to update the downloader".
- Saved as `1 - Raw recordings\<game>\<upload date> <title>.mp4` (title made safe for Windows, " (2)" when taken). The download runs as a TeddyClip job with progress ("Downloading from YouTube 42%").
- The installer runs `pip install --upgrade yt-dlp` on every run, so re-running it is the fix when YouTube breaks the downloader.

### YouTube's captions as the transcript

- The same yt-dlp call asks for English subtitles in `json3`, preferring hand-made over automatic (`subtitleslangs` `en` then `en-*`, `writesubtitles` and `writeautomaticsub`).
- `json3` events carry segments with per-word offsets; they are converted to TeddyClip's `Segment(start, end, text, words)`.
- The result is written as `transcript.json` into the recording's transcript cache (`.cache/<file name>-<size>-<mtime>/`), the exact place `transcribe()` already checks first. The pipeline does not change: it finds a transcript and skips Whisper.
- `config.yaml` gets `youtube_captions: true`; set it to `false` to always transcribe with Whisper instead.
- No English captions: nothing is written and TeddyClip transcribes as usual.

## Part 2: shapes, framing and captions

### Data

- `session.json` gains `words`: every transcribed word as `[start, end, text]` (seconds, 2 decimals), so the editor can preview captions and the cut can build them. About 1 MB for a 4 hour session.
- `made` entries gain `shape`, `framing`, `position` (0 to 1, Fill only) and `captions` (true or false).
- `POST /api/cut` takes the same four fields, validated: shape in `16:9`, `9:16`, `1:1`, `4:5`; framing `fit` or `fill`; position 0 to 1; captions boolean.

### Rendering (`teddyclip/framing.py`)

Output sizes: 16:9 keeps the recording's size (as today); 9:16 is 1080x1920, 1:1 is 1080x1080, 4:5 is 1080x1350.

- **Fill:** `crop=W:H:X:0` sized to the shape's aspect from the full source height (or full width when the source is taller), X = position times the spare width, even numbers, then `scale` to the output size and `setsar=1`.
- **Fit:** Clips Kitty's fit-with-blur graph (`video/cropper.py` `_render_fit_blur`): the background is the frame scaled to cover, shrunk to 1/8 before `gblur` (cheap), scaled back up; the foreground is the frame scaled to the output width; overlaid in the middle.
- Encoded with the existing encoder choice and CPU fallback, `-pix_fmt yuv420p`, and the same audio handling as `media.cut`, written through `media._writing`.
- One framing applies to the whole clip.

### Captions (`teddyclip/captions.py`)

- Adapted from Clips Kitty's `video/captions.py` (credited): words inside the clip grouped three at a time into lines; an ASS subtitle file with one event per word that shows the whole line with the current word highlighted, held until the next word, so there are no blank frames.
- Style: Fredoka (bundled; libass finds it through `fontsdir`), bold, upper case, white with a dark outline and soft shadow, the current word in TeddyClip orange (#d4612a) and scaled to 115% ("pop"). Size 84 at 1920 high, scaled by output height.
- Position: Fill puts captions in the lower third; Fit puts them just under the picture.
- Burned in with ffmpeg's `subtitles` filter. ffmpeg runs in a temporary folder holding the `.ass` file and a copy of the font, so the filter takes bare file names (no Windows path escaping).
- Words with no timing inside a segment are spread evenly over the segment.

### Editor (`teddyclip/editor.html`)

- New controls under the clip strip: Shape (four buttons), Framing (Fit or Fill, shown when the shape is not 16:9), a position slider (shown for Fill), Captions (on or off).
- Live preview: for a non-16:9 shape the player area shows a canvas at the output shape that draws the playing video every frame, cropped or fitted over a blurred copy exactly as the render will, and draws the captions from `words` in the same style. 16:9 shows the plain player, with captions drawn over it when they are on. The real `<video>` keeps playing underneath for sound and timing.
- Create clip and Update clip send the shape, framing, position and captions.

## Errors

- Download problems show in the add dialog in plain words (see Download); nothing half-downloaded is left in Raw recordings.
- A clip whose captions cannot be rendered (ffmpeg without libass) fails with "Captions could not be added: this ffmpeg has no subtitle support. Turn captions off or reinstall TeddyClip."
- No words in the clip with captions on: the clip is made without captions, and the editor says "No speech in this clip, so there are no captions".

## Testing

- `json3` to `Segment` conversion (hand-made and automatic tracks, word offsets, music markers dropped), and that the cache file is what `transcribe()` reads.
- The download wrapper with a fake `YoutubeDL`: format and options, the IPv4 retry, error messages, refusing live streams, file naming.
- Caption lines and ASS events: grouping, highlight per word, timing without gaps, position for Fill and Fit, scaling per shape.
- Render `tiny_video` to all four shapes, Fill (position 0, 0.5, 1) and Fit, with and without captions; check the output size, length and that it plays (H.264, yuv420p).
- `/api/cut` validation of the new fields, and `made` entries storing them.
- In the app: paste the episode 12 link, check the download and that transcription was skipped, then make a vertical Fit clip with captions and a square Fill clip, and check the preview matches the files.

## Not in this change

Posting to TikTok, YouTube or Instagram; automatic face tracking (Clips Kitty's needs two more AI models); changing the framing partway through a clip; editing caption words; stacked facecam-over-gameplay layouts; caption languages other than English.
