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
3. **Pick moments** by sending the transcript and signal timeline to an LLM, which returns candidate clips with titles and reasons.
4. **Review** the candidate list, keep or drop each one, and adjust times.
5. **Render** 16:9 clips and a highlight video with chapter timestamps, using NVIDIA NVENC when available.

## Roadmap

- 9:16 Shorts with burned-in, word-synced captions
- Facecam layouts for Shorts
- Local web UI for reviewing clips
- More per-game detectors
- Compilations ("died to this boss 12 times, then won")

## License

[MIT](LICENSE)
