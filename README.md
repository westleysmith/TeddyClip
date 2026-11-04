# TeddyClip

Turn hours of couch co-op gameplay into a short list of the best moments.

TeddyClip is a personal auto-clipper for long gaming recordings with commentary. It finds highlight candidates so a human reviews a few minutes of picks instead of scrubbing hours of footage, then renders the approved moments as clips and a cut-down highlight video. Everything runs on your own PC. Nothing is uploaded and nothing costs money.

> Status: v1: works end to end; tuning on real footage.

## How it works

1. **Transcribe** the recording with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (word-level timestamps, cached).
2. **Find signals** across the whole video:
   - Say **"clip that"** out loud during a session and that moment is always included. The clip ends just before you say it.
   - Optional [OBS](https://obsproject.com/) chapter-marker hotkey as a clip button.
   - Loudness spikes, bursts of shouting or laughing, and quiet-then-loud reactions.
   - Optional per-game screen detectors (for example a "YOU DIED" screen), chosen by the game folder name.
3. **Pick moments** with a small local AI model (via Ollama) that finds quiet jokes in the transcript and titles each moment. No cloud, no cost. If Ollama is not running, TeddyClip carries on without AI titles.
4. **Cut clips** named by timestamp and what happened, write a `moments.csv` and a DaVinci Resolve marker file, then move the original recording to `Done` with chapters added.
5. **Review** by deleting the clips you don't want, then build a highlight video with YouTube chapters.

TeddyClip uses the graphics card when it can, whatever the brand: transcription runs on NVIDIA cards with faster-whisper and on AMD and Intel graphics with [whisper.cpp](https://github.com/ggml-org/whisper.cpp) through Vulkan, and clips are cut with the card's video encoder (NVIDIA NVENC, AMD AMF or Intel Quick Sync). Without a usable graphics card everything still works on the CPU, more slowly.

## Easy install (Windows, recommended)

No typing needed. On Windows 10 or 11:

1. Download [`Install TeddyClip.bat`](https://raw.githubusercontent.com/westleysmith/TeddyClip/main/Install%20TeddyClip.bat) (right-click the link, choose "Save link as"), or get the file from whoever set TeddyClip up for you.
2. Double-click it. If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**. If it asks whether the app may make changes, click **Yes**.
3. Type your two names when it asks (they go in clip titles), then leave the window open. The first install downloads a few GB and can take 20 to 40 minutes.
4. When it says **All done!**, two shortcuts are on your desktop:
   - **TeddyClip** opens TeddyClip in its own window. Everything happens there.
   - **TeddyClip Folders** opens the folder where recordings go in and clips come out.

It installs Python 3.12, FFmpeg and Ollama (with winget), puts TeddyClip in `%LOCALAPPDATA%\TeddyClip-app`, sets up transcription on the graphics card (NVIDIA, AMD or Intel), and downloads the AI models so the first run starts straight away. Run it again any time to update TeddyClip; your settings in `config.yaml` are kept.

## Manual install (Windows)

The same steps by hand, for developers. An NVIDIA GPU makes it faster but is not required. Everything below is done once.

1. **Python 3.12** from [python.org](https://www.python.org/downloads/release/): pick the latest 3.12 release (3.12, not newer: one of the libraries TeddyClip uses does not install on 3.13 or later yet). Tick "Add python.exe to PATH" in the installer.
2. **FFmpeg.** Open a Command Prompt or PowerShell window and run:
   ```
   winget install Gyan.FFmpeg
   ```
   Then close that window and open a new one, so the new program is found.
3. **Ollama** from [ollama.com](https://ollama.com). After it installs, run:
   ```
   ollama pull qwen3:4b
   ```
   `qwen3:4b` is the default and a starting point: other small models may title your clips better, and the [real-footage checklist](docs/real-footage-checklist.md) walks through comparing them.
4. **Get TeddyClip.** Either `git clone https://github.com/westleysmith/TeddyClip.git`, or use Code > Download ZIP on the GitHub page and unzip it. Put the folder somewhere ordinary, such as `C:\TeddyClip-app`, rather than in a cloud-synced folder like Google Drive or OneDrive.
5. **Install it.** Open a command window in the TeddyClip folder: open the folder in File Explorer, click the address bar at the top, type `cmd` and press Enter. Then run these three commands in it, one after the other:
   ```
   py -3.12 -m venv .venv
   .venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
   .venv\Scripts\pip install -e .
   ```
   The second command installs the small CPU build of PyTorch, which is all TeddyClip needs.
6. **NVIDIA graphics card (for example an RTX 3060): add the GPU libraries.** Run this as an extra step:
   ```
   .venv\Scripts\pip install -e .[gpu]
   ```
   GPU transcription needs these libraries plus an up-to-date NVIDIA driver. Without them everything still works, but transcription runs on the CPU, which is slower. If you have no NVIDIA card, skip this step. (This has not yet been tested on a real GPU; the [real-footage checklist](docs/real-footage-checklist.md) covers confirming it.)
7. **Check the setup:**
   ```
   .venv\Scripts\teddyclip check
   ```
   It prints a list of `[ok]`, `[info]` and `[fail]` lines. Fix anything marked `[fail]` using the hint on that line, and run it again. If it says whisper will use the CPU, TeddyClip still works, just more slowly; the line says why (for example the GPU libraries from step 6 are missing).
8. **Run it:** double-click `TeddyClip.bat`.

The first real run downloads the whisper speech model and the laughter and shout model (PANNs weights), so it takes longer and needs internet once. After that nothing is downloaded again.

## Daily use

1. Record your session in OBS. Set it up once using the [OBS setup guide](docs/obs-setup.md). While you play, say **"clip that"** out loud whenever something is worth keeping. Every one of those moments is guaranteed a clip.
2. Double-click **TeddyClip** on the desktop or in the Start menu. It opens in its own window. Close the window when you are done; that quits TeddyClip. (Prefer your web browser? `Open TeddyClip.bat` in the app folder shows the same page there.)
3. Click **Add recordings** and put your recordings in the folder that opens (`1 Inbox`). You can drop them straight in, or inside a folder named after the game (for example `1 Inbox\Elden Ring`). The folder name is used in the clip folder name, and for some games it turns on screen-text detection such as YOU DIED.
4. Click **Make clips**. The page shows what it is doing. A 4 hour session takes a while, so leave it running. Recordings OBS is still writing are left alone.
5. Watch the clips on the page and click **Delete** on the ones you don't want (they go to the Recycle Bin, so nothing is lost by accident).
6. Click **Make highlight**. The clips you kept are joined in time order into `3 Highlights`, with a YouTube chapters file next to it, and the highlight appears on the page.

**Hands-free:** point OBS's recording folder at `1 - Raw recordings` and turn on **Make clips automatically** in the window, with the game you are playing. Recordings are then clipped as soon as OBS finishes them, while the TeddyClip window is open. See the [OBS setup guide](docs/obs-setup.md).

Prefer no browser? `TeddyClip.bat` does step 4 in a console window, and dragging a clip folder onto `Highlight.bat` does step 6.

### What gets made

```
TeddyClip\                            created on first run, default C:\Users\<you>\TeddyClip
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
     2026-11-01 Elden Ring.mp4        the original, with chapters added
  .cache\                             transcripts, AI answers, model files
```

- **Clips** are named `<hours>h<minutes>m<seconds>s - <title>.mp4` after where they start in the recording. Clips that came from saying "clip that" have `Clip that - ` in front of the title. Clips from an OBS marker key have no prefix, but their `kind` in `moments.csv` is `marker`.
- **`moments.csv`** lists every moment TeddyClip found, including the ones it did not turn into clips. Open it in Excel. The `keep` column says yes or no, `score` is how strong the moment is, `why` explains the pick, and `file` is the clip's file name. This is the place to look when a clip surprised you, or to find a good moment that was left out.
- **`Resolve markers.edl`** puts every clip as a colored marker on your full recording in DaVinci Resolve (red for "clip that" and OBS markers, yellow for laughter, blue for jokes, purple for game screen text, green for loud moments). To use it, put the original recording from `Done` on a timeline starting at 01:00:00:00 (Resolve's default), then in the Media Pool right-click the timeline and choose Timelines > Import > Timeline Markers from EDL. The marker name is the clip title. The marker file has no room for the reason, so the reason is only in `moments.csv`.
- **The original** is moved from the inbox to `Done` with chapters added, one per kept moment, so you can jump between them in a video player. It keeps its file type (an `.mkv` stays `.mkv`). The inbox copy is only removed once the new copy is checked to be the same length.
- **The highlight video** joins the clips without re-encoding, so it keeps the recording's resolution and quality. `chapters.txt` is a list you can paste into a YouTube description. YouTube only accepts it with at least 3 chapters that are each at least 10 seconds long; if that is not true the file says so instead.

## Settings

Everything works with no changes except the names. The settings are in `config.yaml` in the TeddyClip app folder, next to `TeddyClip.bat`. Open it in Notepad to change a setting. If you break it, delete the line you changed or the whole file to go back to the defaults.

| Setting | What it does |
|---|---|
| `root` | Where `1 Inbox`, `2 Clips`, `3 Highlights` and `Done` live. Default `C:\Users\{user}\TeddyClip`. |
| `people` | The names used in clip titles. Change `Friend` to your friend's real name. |
| `triggers` | The phrases that always make a clip. Add any variants the transcript mishears. |
| `audio_track` | Which OBS audio track holds your microphones (for example `2`). Leave as `null` to use track 1. See the [OBS setup guide](docs/obs-setup.md). |
| `whisper_model` | `auto` picks a large model on a GPU (with the GPU libraries installed) and a small one on the CPU. |
| `whisper_device` | `auto` transcribes on the graphics card when it works (NVIDIA with faster-whisper, any other card with whisper.cpp through Vulkan), otherwise the CPU. `cpu` never touches the graphics card. |
| `language` | The language you speak, default `en`. Set it to `null` to let whisper guess, which often goes wrong when a recording starts with game music. |
| `llm: model` | The Ollama model for jokes and titles, or `none` to turn the AI off. |
| `clips:` | `min_seconds` and `max_seconds` (clip length, default 20 to 120), `max_clips` (default 40), `pre_trigger_seconds` (how far back a "clip that" clip starts, default 45). |
| `weights` | How much each signal counts: laughter, joke_sweep, loudness, voice_jump, screen_text. |
| `games` and `lexicons` | Which on-screen words to look for in which game, picked from the inbox folder name. |
| `resolve: timeline_start` | The start timecode of your Resolve timeline, default `01:00:00:00`. |

## Troubleshooting

- **`teddyclip check` says ffmpeg is not found.** Close the window and open a new one after `winget install Gyan.FFmpeg`. If it still fails, restart the PC.
- **A recording failed.** It stays in `1 Inbox`. The message on screen says why. Fix it and run `TeddyClip.bat` again.
- **"has no sound track."** OBS recorded that file without audio. See the audio track part of the [OBS setup guide](docs/obs-setup.md) and record again.
- **A run crashes during transcription on a GPU PC.** Set `whisper_device: cpu` in `config.yaml` and run it again. Transcribing is slower on the CPU, but everything else is the same.
- **Nothing happens for a recording.** TeddyClip waits until a file has not changed for 60 seconds, so a recording that just finished may need a minute. Run it again.

Once you have run a real session, work through the [real-footage checklist](docs/real-footage-checklist.md) to tune it.

## Roadmap

- 9:16 Shorts with burned-in, word-synced captions
- Facecam layouts for Shorts
- More on the TeddyClip page: trim clips and edit titles
- More per-game detectors
- Compilations ("died to this boss 12 times, then won")

## Built on

TeddyClip adapts code from [Clips Kitty](https://github.com/ColinGPT9/clips-studio), a full-featured open-source clipper by ColinGPT9, and trims it down to one job: long couch co-op recordings in, clips and editor markers out. It also uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [PANNs](https://github.com/qiuqiangkong/panns_inference), [RapidOCR](https://github.com/RapidAI/RapidOCR), [Ollama](https://ollama.com) and [FFmpeg](https://ffmpeg.org). See [NOTICE](NOTICE) for details.

The full design is in [docs/design.md](docs/design.md).

## License

[AGPL-3.0-or-later](LICENSE)
