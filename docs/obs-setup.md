# OBS setup for TeddyClip

Four settings in OBS make TeddyClip work better. All of them are optional. The first one (the recording path) helps most, because recordings then land in TeddyClip's Raw recordings folder on their own; without it you add them with **Add recordings**. Menu names are from a recent OBS Studio (30.2 or newer) and may differ slightly in other versions.

## 1. Recording path (recommended)

Point OBS at TeddyClip's Raw recordings folder so recordings land there on their own.

1. Open OBS, then Settings > Output.
2. Under Recording, set **Recording Path** to:
   `C:\Users\<you>\TeddyClip\1 - Raw recordings`
3. In TeddyClip, turn on **Make clips automatically** and type the game you are playing in **Game for new recordings**. Each recording is then clipped as soon as OBS finishes it, filed under that game. The game name switches on screen-text detection (Elden Ring and Dark Souls look for YOU DIED, GTA and Red Dead for WASTED, Counter-Strike for ROUND WON, and so on); change it when you switch games.

Automatic mode waits while any recording in that folder is still being written, so it does not slow your game down while you are still recording. It works while the TeddyClip window is open.

If you would rather sort by hand, set the Recording Path to a folder named after the game inside Raw recordings (for example `1 - Raw recordings\Elden Ring`) and leave automatic mode off.

If you are not sure where the TeddyClip folder is, click **TeddyClip Folders** on the desktop.

TeddyClip only picks up `.mp4` and `.mkv` files, and it waits until OBS has let go of a file and it has not changed for 10 seconds before touching it.

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
4. Open `config.yaml` in the TeddyClip app folder (the one with `TeddyClip.bat` in it) and change the line to:
   ```
   audio_track: 2
   ```

Track 1 is then the full mix (game and voices) and track 2 is only the microphones, which TeddyClip uses to find speech and laughter.

If a recording has no track 2, TeddyClip falls back to track 1. If a recording has no sound at all, TeddyClip stops with a message instead of producing empty results: check that **Audio Track 1** is ticked on the Recording tab, then record again.

## A quick test

Record 30 seconds, say "clip that" once, and stop. If OBS records into `1 - Raw recordings`, it shows up in TeddyClip by itself; otherwise use **Add recordings**. Click **Make clips** (or let automatic mode start it). A recording that short will not give much, but it shows that the path, the audio and the folders are all working before you record a whole session.
