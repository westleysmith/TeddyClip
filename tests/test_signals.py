import wave

import numpy as np
import pytest

from teddyclip.signals import audio_features, contributions, find_triggers, fuse, pct, peak_windows, voice_jump
from teddyclip.transcribe import Word


def W(t, s):
    return Word(t, t + 0.3, s)


DEFAULT_TRIGGERS = ["clip that", "clip it", "clip this"]


# "clipped that" is a likely Whisper mishear of "clip that" (the p runs into the th).
@pytest.mark.parametrize("said", [["clip", "that"], ["Clip", "that!"], ["clip,", "that"], ["CLIP", "THAT."],
                                  ["clipped", "that"], ["cliip", "that"]])
def test_trigger_variants_match(said):
    words = [W(10, "oh"), W(11, said[0]), W(11.3, said[1])]
    assert find_triggers(words, ["clip that"]) == [11]


@pytest.mark.parametrize("said", [["clip", "it"], ["Clip", "this!"], ["clipped", "this"]])
def test_other_default_triggers_match(said):
    assert find_triggers([W(5, said[0]), W(5.3, said[1])], DEFAULT_TRIGGERS) == [5]


# Ordinary talk that the old n-gram matching took for a trigger. This supersedes
# the earlier test that let "flip that" fire.
@pytest.mark.parametrize("said", [
    ["clip", "is"], ["clip", "in"], ["clip", "the"], ["clip", "a"], ["clip", "to"], ["clip", "got"],
    ["clip", "what"], ["clipped", "it"], ["clips", "that"], ["flip", "that"], ["chip", "that"],
    ["dip", "that"], ["tip", "that"], ["zip", "that"], ["i", "that"], ["clipping", "that"],
])
def test_ordinary_talk_is_not_a_trigger(said):
    words = [W(10, "oh"), W(11, said[0]), W(11.3, said[1]), W(11.6, "now")]
    assert find_triggers(words, DEFAULT_TRIGGERS) == []


@pytest.mark.parametrize("first", ["clip.", "Clip!", "clip?"])
def test_trigger_does_not_match_across_a_sentence_break(first):
    assert find_triggers([W(11, first), W(11.3, "That")], DEFAULT_TRIGGERS) == []


def test_trigger_does_not_match_across_a_long_gap():
    assert find_triggers([Word(1, 1.3, "clip"), Word(21.3, 21.6, "that")], DEFAULT_TRIGGERS) == []


def test_trigger_words_may_be_up_to_one_second_apart():
    assert find_triggers([Word(1, 1.3, "clip"), Word(2.3, 2.6, "that")], ["clip that"]) == [1]
    assert find_triggers([Word(1, 1.3, "clip"), Word(2.4, 2.7, "that")], ["clip that"]) == []


def test_trigger_does_not_match_unrelated():
    assert find_triggers([W(1, "chip"), W(1.3, "bag")], ["clip that"]) == []


def test_triggers_within_5s_collapse():
    words = [W(1, "clip"), W(1.3, "that"), W(3, "clip"), W(3.3, "that"), W(20, "clip"), W(20.3, "it")]
    assert find_triggers(words, ["clip that", "clip it"]) == [1, 20]


def test_pct_and_fuse():
    a = np.array([0, 0, 10, 0.])
    b = np.array([0, 5, 0, 0.])
    s = fuse({"a": a, "b": b}, {"a": 1.0, "b": 0.5})
    assert s.argmax() == 2 and s[1] > s[0] and np.all((0 <= s) & (s <= 1))


def test_pct_ties_share_the_lowest_rank():
    assert pct(np.array([3., 3., 3.])).tolist() == [0.0, 0.0, 0.0]
    assert pct(np.zeros(0)).size == 0


def test_fuse_pads_to_longest_and_ignores_unweighted_signals():
    s = fuse({"a": np.array([0., 1.]), "b": np.array([0., 1., 2., 3.])}, {"a": 1.0, "b": 1.0, "c": 1.0})
    assert s.size == 4
    assert fuse({"a": np.array([0., 1.])}, {}).tolist() == [0.0, 0.0]


def test_contributions_are_what_fuse_combines():
    signals = {"a": np.array([0, 0, 10, 0.]), "b": np.array([0, 5, 0, 0.]), "c": np.array([1., 2.])}
    weights = {"a": 1.0, "b": 0.5, "c": 2.0}
    parts = contributions(signals, weights)
    assert set(parts) == {"a", "b", "c"} and all(p.size == 4 for p in parts.values())
    assert parts["b"].tolist() == pytest.approx([0, 0.5, 0, 0])
    assert parts["c"].tolist() == pytest.approx([0, 1.0, 0, 0])   # weight clipped to 1, padded with zeros
    expected = 1 - np.prod([1 - p for p in parts.values()], axis=0)
    assert fuse(signals, weights) == pytest.approx(expected)


def test_peak_windows_clamp_and_spacing():
    s = np.zeros(300)
    s[5] = 1
    s[150] = 1
    s[160] = 0.9
    wins = peak_windows(s, percentile=90)
    assert wins[0][0] == 0 and len(wins) == 2
    assert wins[0][3] == 5.0
    assert wins[1] == (110.0, 165.0, 1.0, 150.0)  # 40 s of lead-in, 15 after


def test_peak_windows_clamps_end_and_needs_a_positive_peak():
    s = np.zeros(100)
    s[95] = 1
    assert peak_windows(s) == [(55.0, 100.0, 1.0, 95.0)]
    assert peak_windows(np.zeros(100)) == []


def test_a_calm_video_does_not_get_its_calmest_peaks_clipped():
    s = np.zeros(300)
    s[50], s[200] = 0.2, 0.9  # a mild bump and a real moment
    assert [w[3] for w in peak_windows(s)] == [200.0]


def test_voice_jump_flags_an_outburst():
    x = np.full(200, 0.1)
    x[100:104] = 0.35  # a few seconds of yelling
    assert voice_jump(x)[101] > 0.5 and voice_jump(x)[50] == 0


def test_voice_jump_ignores_one_stressed_word():
    x = np.full(200, 0.1)
    x[100] = 0.35  # one loud second, then back to normal talking
    assert voice_jump(x).max() < 0.2


def test_a_loud_game_sound_with_nobody_talking_is_not_a_voice_jump():
    from teddyclip.signals import talking_seconds
    from teddyclip.transcribe import Word

    x = np.full(200, 0.1)
    x[50:54] = 0.4    # an explosion, nobody says anything
    x[150:154] = 0.4  # someone yelling
    words = [Word(float(t) + 0.1, float(t) + 0.8, "w") for t in range(0, 200, 2) if not 46 <= t <= 58]
    words += [Word(150.0, 154.0, "NOOO")]
    vj = voice_jump(x, talking_seconds(words, 200))
    assert vj[50:54].max() == 0 and vj[151] > 0.5


def test_talking_seconds_marks_every_second_a_word_covers():
    from teddyclip.signals import talking_seconds
    from teddyclip.transcribe import Word

    assert talking_seconds([Word(1.2, 3.5, "hey"), Word(9.5, 12.0, "past the end")], 10).tolist() == \
        [False, True, True, True, False, False, False, False, False, True]


def test_absolute_signals_are_not_ranked_within_the_video():
    calm = np.full(100, 0.05)
    calm[10] = 0.1  # the "loudest" second of a calm video
    ranked = contributions({"v": calm}, {"v": 1.0})["v"]
    fixed = contributions({"v": calm}, {"v": 1.0}, absolute={"v"})["v"]
    assert ranked[10] == pytest.approx(1.0) and fixed[10] == pytest.approx(0.1)


def test_voice_jump_empty():
    assert voice_jump(np.zeros(0)).size == 0


def _write_wav(path, samples):
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(pcm.tobytes())


def test_audio_features_loud_second_has_highest_spike(tmp_path):
    t = np.arange(16000) / 16000
    quiet = 0.02 * np.sin(2 * np.pi * 220 * t)
    loud = 0.8 * np.sin(2 * np.pi * 220 * t)
    wav = tmp_path / "a.wav"
    _write_wav(wav, np.concatenate([quiet] * 5 + [loud] + [quiet] * 5))
    feats = audio_features(wav)
    assert set(feats) == {"loudness", "spike", "burst", "noisiness"}
    assert all(v.size == 11 for v in feats.values())
    assert feats["spike"].argmax() == 5
    assert feats["loudness"].argmax() == 5


def test_audio_features_under_one_second_is_empty(tmp_path):
    wav = tmp_path / "short.wav"
    _write_wav(wav, np.zeros(1000))
    feats = audio_features(wav)
    assert set(feats) == {"loudness", "spike", "burst", "noisiness"}
    assert all(v.size == 0 for v in feats.values())
