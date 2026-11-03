# Real-footage checklist

TeddyClip was built and tested on made-up test videos. This checklist is for the first real sessions: it finds out what works, what needs tuning, and what to write down. Work through it in order and note the answers (a text file next to the clips is fine).

## 1. Check the setup

- [ ] Run `.venv\Scripts\teddyclip check` and read every line.
- [ ] **GPU transcription:** the CUDA line says `[ok]`. For an NVIDIA card this needs the GPU libraries (`.venv\Scripts\pip install -e .[gpu]`) and an up-to-date NVIDIA driver. If the line says whisper will use the CPU, read the reason on it, fix that, and run the check again. Without the GPU libraries everything still works on the CPU, just slower. Note that the GPU setup has not yet been tested on a real GPU, so write down exactly what the line says.
- [ ] **NVENC:** the line says clips are encoded on the NVIDIA GPU. If it says CPU, clips still work but cutting is slower.
- [ ] **Ollama:** the line says it is running and has your model.
- [ ] **Folders:** the line shows the TeddyClip folder you expect.

## 2. Process one real session

Use a real recording of a few hours, ideally one where you remember saying "clip that".

- [ ] **Before the first run, copy the original recording somewhere outside the inbox** (for example `C:\TeddyClip-test`). TeddyClip moves the original into `Done` and adds chapters to it, and a later run on that file would mistake the chapters for OBS markers. The copy is your clean original for re-runs and for step 7.
- [ ] Put the recording in `1 Inbox\<Game>` and double-click `TeddyClip.bat`.
- [ ] Write down the recording length and how long the run took. Compare the speed of the transcribing step with what you expect from the GPU (a GPU should be many times faster than real time; the CPU is much slower).
- [ ] While it runs, watch Task Manager > Performance > GPU. Confirm the GPU is busy during transcribing and while clips are cut (the "Video Encode" graph moves when NVENC is used).
- [ ] **VRAM:** whisper and Ollama run one after the other. Confirm dedicated GPU memory is not full at the hand-over, and that nothing fails with an out-of-memory message. Then try a batch of two or three recordings in the inbox and confirm the later ones finish as well as the first. If memory runs out, note which model and which card (6 GB or 12 GB) and set `whisper_model` to something smaller in `config.yaml`.
- [ ] **Ollama requests:** TeddyClip sends `think: false` to Ollama so the model answers directly. Confirm there are no errors about this with your chosen model, that titles are actually produced (not a transcript snippet or the word "moment"), and that the run does not print "continuing without AI titles".
- [ ] Check that the original moved to `Done` with its chapters, and that it still plays.

## 3. Did every "clip that" produce a clip?

This matters most.

- [ ] Count how many times you remember saying "clip that" (or use the OBS marker key).
- [ ] Filter `moments.csv` for `kind` = `trigger` (and `marker`) and compare. Every one should be there with `keep` = yes.
- [ ] Open each of those clips. Does the clip end just before "clip that" is said, and does it hold the funny part?
- [ ] For any you said that are missing, find the spot in the recording and note what the transcript heard. Add that wording to `triggers` in `config.yaml` (for example a spelling like "clipped that", or a close sound-alike).
- [ ] **False triggers:** the phrase "clip" can come up in normal talk, for example a Counter-Strike magazine or a clip of ammo. Look for clips that start with `Clip that - ` but where nobody asked for a clip. Note the game, what was said, and how often it happens. If it is a problem, remove the loosest phrases (`clip it`, `clip this`) from `triggers` and keep only `clip that`.

## 4. Rate the clips

- [ ] Watch the 10 clips with the highest `score` in `moments.csv`. Rate each as good, fine or bad.
- [ ] Write down any great moment that is in `moments.csv` with `keep` = no, or not there at all. Note whether it was loud, a quiet joke, or an on-screen event.
- [ ] Look at the `why` column for the bad ones to see which signal picked them.
- [ ] If too many clips are loud but boring, lower `loudness` and `voice_jump` in `weights`. If quiet jokes are missing, raise `joke_sweep`. Change one thing at a time and run again.

## 5. Game screen text

- [ ] For a Souls-style session (Elden Ring, Dark Souls) in a folder with that game's name, confirm every YOU DIED you can remember shows up in `moments.csv` with an event listed, and that a clip exists around it.
- [ ] Note any game where the on-screen words are different from the ones in `lexicons` and add them to `config.yaml`.

## 6. Resolve markers

- [ ] In DaVinci Resolve, put the original recording from `Done` on a timeline that starts at 01:00:00:00.
- [ ] In the Media Pool, right-click the timeline and choose Timelines > Import > Timeline Markers from EDL, and pick `Resolve markers.edl` from the clip folder.
- [ ] Confirm the markers land on the right moments (compare two or three against their clips), have the right colors, and show the clip titles.
- [ ] If markers are all off by a fixed amount, your timeline probably does not start at 01:00:00:00. Set `resolve: timeline_start` to match, then make the markers again by running `.venv\Scripts\teddyclip process "<path to the copy>"` on your copy of the original (see step 7).
- [ ] Note your Resolve version.

## 7. Try two AI models

- [ ] Use the copy of the original recording you made before the first run (step 2). Do not reuse the file in `Done`: it has chapters, which would be read as OBS markers and force extra clips, spoiling the comparison.
- [ ] For the first model, make sure `config.yaml` says `qwen3:4b` (the default) and run `.venv\Scripts\teddyclip process "<path to the copy>"`. Files outside the inbox are left in place, so the copy stays untouched. Note the name of the clip folder it makes.
- [ ] Run `ollama pull gemma3:4b`, set `llm: model: gemma3:4b` in `config.yaml`, and run the same `teddyclip process "<path to the copy>"` command again. The second clip folder gets a ` (2)` on its name.
- [ ] Compare the titles and scores of the top clips in the two `moments.csv` files. Record which one titled better and which found more quiet jokes, and keep that model in `config.yaml`.
- [ ] Note the speed difference and any errors from either model.

## What to write down at the end

- Which model, which Whisper model, and how long a 4 hour session took end to end.
- Whether "clip that" was heard every time, which variants to add, and any false triggers.
- Your weights changes and why.
- Your Resolve version and whether the EDL import worked.
- GPU, VRAM and any out-of-memory problems.
