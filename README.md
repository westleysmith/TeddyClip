# TeddyClip

Turn hours of couch co-op gameplay into a short list of the best moments.

TeddyClip is a personal auto-clipper for long gaming recordings with commentary. It finds highlight candidates so a human reviews a few minutes of picks instead of scrubbing hours of footage, then renders the approved moments as clips and a cut-down highlight video.

> Status: early design. Nothing runs yet.

## How it will work

1. **Transcribe** the recording with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (word-level timestamps, cached).
2. **Find signals** across the whole video:
   - Say **"clip that"** out loud during a session and that moment is always included.
   - Optional [OBS](https://obsproject.com/) chapter-marker hotkey as a clip button.
   - Loudness spikes, bursts of shouting or laughing, and quiet-then-loud reactions.
   - Optional per-game screen detectors (for example a "YOU DIED" screen).
3. **Pick moments** with a small local AI model (via Ollama) that finds quiet jokes in the transcript and titles each moment. No cloud, no cost.
4. **Cut clips** named by timestamp and what happened, plus DaVinci Resolve markers and chapters on the original recording.
5. **Review** by deleting the clips you don't want, then build a highlight video with YouTube chapters. NVIDIA NVENC is used when available.

## Roadmap

- 9:16 Shorts with burned-in, word-synced captions
- Facecam layouts for Shorts
- Local web UI for reviewing clips
- More per-game detectors
- Compilations ("died to this boss 12 times, then won")

## Built on

TeddyClip adapts code from [Clips Kitty](https://github.com/ColinGPT9/clips-studio), a full-featured open-source clipper by ColinGPT9, and trims it down to one job: long couch co-op recordings in, clips and editor markers out. It also uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [PANNs](https://github.com/qiuqiangkong/panns_inference), [RapidOCR](https://github.com/RapidAI/RapidOCR), [Ollama](https://ollama.com) and [FFmpeg](https://ffmpeg.org). See [NOTICE](NOTICE) for details.

The full design is in [docs/design.md](docs/design.md).

## License

[AGPL-3.0-or-later](LICENSE)
