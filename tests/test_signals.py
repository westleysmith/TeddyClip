import wave

import numpy as np
import pytest

from teddyclip.signals import audio_features, find_triggers, fuse, pct, peak_windows, voice_jump
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


def test_peak_windows_clamp_and_spacing():
    s = np.zeros(300)
    s[5] = 1
    s[150] = 1
    s[160] = 0.9
    wins = peak_windows(s, percentile=90)
    assert wins[0][0] == 0 and len(wins) == 2
    assert wins[1] == (130.0, 165.0, 1.0)


def test_peak_windows_clamps_end_and_needs_a_positive_peak():
    s = np.zeros(100)
    s[95] = 1
    assert peak_windows(s) == [(75.0, 100.0, 1.0)]
    assert peak_windows(np.zeros(100)) == []


def test_voice_jump_flags_sudden_loud():
    x = np.full(200, 0.1)
    x[100] = 0.35
    assert voice_jump(x)[100] > 0.5 and voice_jump(x)[50] == 0


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
