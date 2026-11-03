import json
from types import SimpleNamespace

import pytest

import teddyclip.transcribe as transcribe_mod
from teddyclip.transcribe import Segment, Word, all_words, collapse_repetition_loops, transcribe


@pytest.fixture(autouse=True)
def _fresh_model():
    transcribe_mod.release()
    yield
    transcribe_mod.release()


def _raw_segment(start, end, text, words):
    return SimpleNamespace(
        start=start, end=end, text=f" {text}",
        words=[SimpleNamespace(start=s, end=e, word=f" {w}") for s, e, w in words],
    )


class FakeModel:
    """Stands in for WhisperModel; records the kwargs transcribe was called with."""

    def __init__(self, device="cpu", error=None):
        self.model = SimpleNamespace(device=device)
        self.error = error
        self.kwargs = None

    def transcribe(self, path, language=None, vad_filter=False, beam_size=5,
                   condition_on_previous_text=True, word_timestamps=False, hotwords=None):
        self.kwargs = dict(vad_filter=vad_filter, beam_size=beam_size,
                           condition_on_previous_text=condition_on_previous_text,
                           word_timestamps=word_timestamps, hotwords=hotwords)
        if self.error:
            raise self.error
        segs = [_raw_segment(0.0, 1.0, "clip that", [(0.0, 0.4, "clip"), (0.4, 1.0, "that")])]
        return iter(segs), SimpleNamespace(duration=1.0, language="en")


def test_cache_hit_skips_model(tmp_path, monkeypatch):
    (tmp_path / "transcript.json").write_text(json.dumps([{"start": 0, "end": 1, "text": "clip that",
        "words": [{"start": 0, "end": 0.4, "text": "clip"}, {"start": 0.4, "end": 1, "text": "that"}]}]))
    monkeypatch.setattr(transcribe_mod, "_load_model", lambda *a, **k: pytest.fail("model loaded"))
    segs = transcribe(tmp_path / "a.wav", tmp_path)
    assert segs[0].words[1].text == "that"


def test_repetition_loops_collapse():
    segs = [Segment(i, i + 1, "thank you", []) for i in range(6)]
    assert len(collapse_repetition_loops(segs)) < 6


def test_short_repeats_are_kept():
    segs = [Segment(i, i + 1, "yes", []) for i in range(2)] + [Segment(2, 3, "no", [])]
    assert len(collapse_repetition_loops(segs)) == 3


def test_loop_inside_one_segment_collapses():
    words = [Word(i * 0.7, i * 0.7 + 0.6, w) for i, w in enumerate(["We", "are", "ready."] * 20)]
    seg = Segment(0.0, 42.0, " ".join(["We are ready."] * 20), words)
    out = collapse_repetition_loops([seg])
    assert out[0].text == "We are ready."
    assert len(out[0].words) == 3
    assert seg.text.count("ready") == 20  # the input is not mutated


def test_all_words_flattens_in_order():
    segs = [Segment(0, 1, "a b", [Word(0, 0.5, "a"), Word(0.5, 1, "b")]),
            Segment(1, 2, "c", [Word(1, 2, "c")])]
    assert [w.text for w in all_words(segs)] == ["a", "b", "c"]


def test_transcribe_passes_options_and_writes_cache(tmp_path, monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(transcribe_mod, "_load_model", lambda *a, **k: model)
    segs = transcribe(tmp_path / "a.wav", tmp_path, hotwords=["Teddy", "clip"])
    assert model.kwargs == dict(vad_filter=True, beam_size=1, condition_on_previous_text=False,
                                word_timestamps=True, hotwords="Teddy clip")
    assert [w.text for w in segs[0].words] == ["clip", "that"]
    cached = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert cached[0]["words"][0] == {"start": 0.0, "end": 0.4, "text": "clip"}


def test_hotwords_omitted_when_not_given(tmp_path, monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(transcribe_mod, "_load_model", lambda *a, **k: model)
    transcribe(tmp_path / "a.wav", tmp_path)
    assert model.kwargs["hotwords"] is None


def test_gpu_failure_mid_run_retries_on_cpu(tmp_path, monkeypatch):
    gpu = FakeModel(device="cuda", error=RuntimeError("Library cublas64_12.dll is not found"))
    cpu = FakeModel(device="cpu")
    loads = []

    def fake_load(model_size, device="auto"):
        loads.append(device)
        return cpu if device == "cpu" else gpu

    monkeypatch.setattr(transcribe_mod, "_load_model", fake_load)
    segs = transcribe(tmp_path / "a.wav", tmp_path)
    assert loads == ["auto", "cpu"]
    assert segs[0].text == "clip that"


def test_unrelated_runtime_error_is_not_swallowed(tmp_path, monkeypatch):
    gpu = FakeModel(device="cuda", error=RuntimeError("something else broke"))
    monkeypatch.setattr(transcribe_mod, "_load_model", lambda *a, **k: gpu)
    with pytest.raises(RuntimeError, match="something else"):
        transcribe(tmp_path / "a.wav", tmp_path)


@pytest.mark.slow
def test_real_transcription(tiny_speech_wav, tmp_path):  # fixture uses Windows SAPI to say "clip that"
    assert "clip" in " ".join(w.text.lower() for w in all_words(transcribe(tiny_speech_wav, tmp_path)))


def test_collapsed_run_keeps_first_copy_only():
    segs = [Segment(0, 1, "hello", [])] + [Segment(i, i + 1, "thank you.", []) for i in range(1, 7)]
    out = collapse_repetition_loops(segs)
    assert [s.text for s in out] == ["hello", "thank you."]
    assert out[1].start == 1
