# OBS setup for TeddyClip

Four settings in OBS make TeddyClip work better. Only the last one (the recording path) is needed; the rest are optional but recommended. Menu names are from a recent OBS Studio (30.2 or newer) and may differ slightly in other versions.

## 1. Recording path (needed)

Point OBS at the TeddyClip inbox so recordings land there on their own.

1. Open OBS, then Settings > Output.
2. Under Recording, set **Recording Path** to your inbox, plus a folder named after the game. For example:
   `C:\Users\<you>\TeddyClip\1 Inbox\Elden Ring`
3. Change the last folder name when you switch games. The folder name is used in the clip folder name, and some games get screen-text detection from it (Elden Ring and Dark Souls look for YOU DIED, GTA and Red Dead for WASTED, Counter-Strike for ROUND WON, and so on). A recording dropped straight into `1 Inbox` still works; it just has no game.

If you are not sure where your inbox is, run `teddyclip check`: it prints the TeddyClip folder.

TeddyClip only picks up `.mp4` and `.mkv` files, and it waits until OBS has stopped writing a file for 60 seconds before touching it.

## 2. Recording format: Hybrid MP4 (recommended)

1. Settings > Output > Recording.
2. Set **Recording Format** to **Hybrid MP4**.

Hybrid MP4 does not lose the whole recording if OBS or the PC crashes, and it is the format that supports chapter markers (next step). If you would rather not use it, plain MP4 or MKV also work; you just will not have the marker hotkey.

If you record MKV, turn off Settings > Advanced > Recording > **Automatically remux to mp4**. Otherwise OBS leaves two copies of every recording in the inbox; TeddyClip processes the .mp4 and skips the .mkv, which then just takes up space.

## 3. A clip button: Add Chapter Marker (optional)

Saying "clip that" out loud already guarantees a clip. A hotkey is a quiet alternative for moments when you do not want to talk, and it works even if the words are misheard.

1. Settings > Hotkeys.
2. Find **Add Chapter Marker** and give it a key that is easy to hit but hard to hit by accident (for example a spare key on the keyboard, or a mouse side button if OBS offers it).
3. Press it during a recording right after something worth keeping happens.

Each marker becomes a clip that ends at the marker, the same as "clip that". This only works with the Hybrid MP4 format from step 2.

## 4. Separate microphone track (optional)

By default TeddyClip listens to the whole recording, including the game sound. Game sound can drown out voices and confuse the laughter and shout detection. Recording your microphones alone on their own track fixes that. The clips themselves always use the full mix on track 1, so nothing changes in what you watch.

1. Settings > Output, and set **Output Mode** to **Advanced**.
2. On the **Recording** tab, tick **Audio Track 1** and **Audio Track 2**.
3. In the main OBS window, in the Audio Mixer, click the three dots (or the gear) on each source and choose **Advanced Audio Properties**. In the **Tracks** columns:
   - Game or desktop audio: track **1** only.
   - Each microphone: tracks **1** and **2**.
4. Open `config.yaml` in the TeddyClip folder and change the line to:
   ```
   audio_track: 2
   ```

Track 1 is then the full mix (game and voices) and track 2 is only the microphones, which TeddyClip uses to find speech and laughter.

If a recording has no track 2, TeddyClip falls back to track 1. If a recording has no sound at all, TeddyClip stops with a message instead of producing empty results: check that **Audio Track 1** is ticked on the Recording tab, then record again.

## A quick test

Record 30 seconds, say "clip that" once, stop, and drop the file into `1 Inbox`. Run `TeddyClip.bat`. A recording that short will not give much, but it shows that the path, the audio and the folders are all working before you record a whole session.
